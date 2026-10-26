"""Load the Olist source CSVs into a SQLite warehouse and build the analytic layer.

Pipeline step 1 of 4:  load -> clean -> query -> report.

WHAT THIS SCRIPT DOES
----------------------
1. Creates the physical schema (`sql/01_schema.sql`).
2. Loads the eight source CSVs verbatim, applying only *type coercion and
   whitespace/case standardisation* - no row is dropped, no amount is edited.
3. Records every load-time rule that changed a value in the
   `dq_cleaning_rules` audit table, together with the number of records it
   touched, so the cleaning decisions are auditable.
4. Builds the analytic views (`sql/02_views.sql`).
5. Runs a referential-integrity check and reports orphan rows.

The script is deterministic: running it twice produces byte-identical
outputs (the database is rebuilt from scratch every time).

Usage:
    python src/build_db.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

TS_COLUMNS = {
    "orders": [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "order_items": ["shipping_limit_date"],
    "reviews": ["review_creation_date", "review_answer_timestamp"],
}

TEXT_TRIM_COLUMNS = {
    "orders": ["order_status"],
    "payments": ["payment_type"],
    "customers": ["customer_city", "customer_state"],
    "sellers": ["seller_city", "seller_state"],
    "products": ["product_category_name"],
    "product_category_translation": [
        "product_category_name",
        "product_category_name_english",
    ],
}

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def log(message: str) -> None:
    print(f"[build_db] {message}")


def read_raw(table: str) -> pd.DataFrame:
    path = config.RAW_DIR / config.RAW_TABLES[table]
    if not path.exists():
        raise FileNotFoundError(
            f"Missing raw file for table '{table}': {path}\n"
            "Run `python src/fetch_data.py` to download the source data."
        )
    return pd.read_csv(path)


def normalise_timestamps(df: pd.DataFrame, cols: list[str]) -> tuple[pd.DataFrame, int]:
    """Parse timestamp columns to ISO-8601 text. Unparseable values become NULL."""
    changed = 0
    for col in cols:
        if col not in df.columns:
            continue
        raw = df[col]
        parsed = pd.to_datetime(raw, errors="coerce")
        formatted = parsed.dt.strftime(TIMESTAMP_FORMAT)
        # Where the source was populated but could not be parsed we keep NULL
        # and count it; where the source was already NULL nothing changes.
        changed += int(((raw.notna()) & (parsed.isna())).sum())
        df[col] = formatted.where(parsed.notna())
    return df, changed


def normalise_text(df: pd.DataFrame, cols: list[str]) -> tuple[pd.DataFrame, int]:
    """Trim surrounding whitespace and lower-case categorical text."""
    changed = 0
    for col in cols:
        if col not in df.columns:
            continue
        before = df[col]
        df[col] = before.astype("string").str.strip().str.lower()
        changed += int((before.astype("string") != df[col]).fillna(False).sum())
    return df, changed


def schema_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def prepare_for_load(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Align a frame to the declared schema so it can be APPENDED to the
    pre-created table.

    Appending (rather than replacing) matters: `to_sql(if_exists="replace")`
    drops and recreates the table, which silently removes the primary keys
    and the secondary indexes declared in `sql/01_schema.sql` and turns every
    correlated subquery into a full table scan.
    """
    out = df[[c for c in columns if c in df.columns]].copy()
    for col in out.columns:
        series = out[col]
        if pd.api.types.is_integer_dtype(series):
            out[col] = series.astype("Int64").astype(object).where(series.notna(), None)
        elif pd.api.types.is_float_dtype(series):
            out[col] = series.astype(float)
        else:
            out[col] = series.astype(object).where(series.notna(), None)
    return out



def build() -> None:
    if config.DB_PATH.exists():
        config.DB_PATH.unlink()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row

    schema_sql = (config.SQL_DIR / "01_schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    log("schema created")

    rules: list[dict] = []
    rule_id = 0

    def add_rule(code, table, description, rule_type, action, rec_in, rec_out, affected):
        nonlocal rule_id
        rule_id += 1
        rules.append(
            dict(
                rule_id=rule_id,
                rule_code=code,
                table_name=table,
                rule_description=description,
                rule_type=rule_type,
                action_taken=action,
                records_in=rec_in,
                records_out=rec_out,
                records_affected=affected,
            )
        )

    frames: dict[str, pd.DataFrame] = {}
    for table in config.RAW_TABLES:
        df = read_raw(table)
        rec_in = len(df)
        frames[table] = df
        log(f"read {table}: {rec_in:,} rows")

    # -- standardisation rules -------------------------------------------------
    for table, cols in TEXT_TRIM_COLUMNS.items():
        frames[table], affected = normalise_text(frames[table], cols)
        if affected:
            add_rule(
                f"R-{table[:3].upper()}-TRIM",
                table,
                "Trim leading/trailing whitespace and lower-case categorical text "
                f"({', '.join(cols)})",
                "standardisation",
                "Value rewritten in place; row retained",
                len(frames[table]),
                len(frames[table]),
                affected,
            )

    for table, cols in TS_COLUMNS.items():
        frames[table], affected = normalise_timestamps(frames[table], cols)
        if affected:
            add_rule(
                f"R-{table[:3].upper()}-TS",
                table,
                "Parse source date strings to ISO-8601 'YYYY-MM-DD HH:MM:SS' text",
                "standardisation",
                "Value rewritten in place; unparseable values set to NULL",
                len(frames[table]),
                len(frames[table]),
                affected,
            )

    # payments.payment_installments: 0 is not a valid instalment count.
    pay = frames["payments"]
    zero_inst = int((pay["payment_installments"] == 0).sum())
    if zero_inst:
        pay.loc[pay["payment_installments"] == 0, "payment_installments"] = pd.NA
        add_rule(
            "R-PAY-INST0",
            "payments",
            "payment_installments = 0 is not a meaningful instalment count "
            "(it appears only on untyped 'not_defined' payments)",
            "standardisation",
            "Set to NULL; the row and its value are retained. NULL instalments are "
            "excluded from instalment-weighted averages but included in value totals",
            len(pay),
            len(pay),
            zero_inst,
        )

    # ------------------------------------------------------------------ load
    load_order = [
        "customers",
        "sellers",
        "products",
        "product_category_translation",
        "orders",
        "order_items",
        "payments",
        "reviews",
    ]
    for table in load_order:
        df = frames[table]
        columns = schema_columns(conn, table)
        prepared = prepare_for_load(df, columns)
        missing = [c for c in columns if c not in prepared.columns]
        if missing:
            raise ValueError(f"Table '{table}' is missing source columns: {missing}")
        prepared.to_sql(table, conn, if_exists="append", index=False)
        loaded = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if loaded != len(df):
            raise ValueError(f"Load mismatch on '{table}': {loaded} != {len(df)}")
        log(f"loaded {table}: {loaded:,} rows")

    # The declared primary keys and indexes must survive the load.
    idx = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
    ).fetchone()[0]
    if idx < 10:
        raise RuntimeError(
            f"Expected the 10 declared indexes to exist, found {idx}. "
            "The load path is replacing tables instead of appending."
        )
    log(f"indexes intact: {idx}")

    # ------------------------------------------------- referential integrity
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    orphan_detail = []
    for row in fk:
        orphan_detail.append(dict(row))
    add_rule(
        "V-FK-ORPHAN",
        "all",
        "Referential integrity check across all declared foreign keys",
        "validation",
        "Reported, not repaired - orphans are quantified in the data-quality report"
        if fk
        else "No action required - no orphan rows found",
        sum(len(f) for f in frames.values()),
        sum(len(f) for f in frames.values()),
        len(fk),
    )
    if fk:
        log(f"WARNING: {len(fk)} orphan rows detected")

    # --------------------------------------------------- load-time validation
    checks = [
        (
            "V-ORD-NOPAY",
            "orders",
            "Orders with no matching row in payments",
            "SELECT COUNT(*) FROM orders o LEFT JOIN payments p ON p.order_id=o.order_id "
            "WHERE p.order_id IS NULL",
        ),
        (
            "V-PAY-NOORD",
            "payments",
            "Payment rows with no matching order",
            "SELECT COUNT(*) FROM payments p LEFT JOIN orders o ON o.order_id=p.order_id "
            "WHERE o.order_id IS NULL",
        ),
        (
            "V-ITEM-NOPROD",
            "order_items",
            "Line items pointing at a product_id that does not exist",
            "SELECT COUNT(*) FROM order_items i LEFT JOIN products p ON p.product_id=i.product_id "
            "WHERE p.product_id IS NULL",
        ),
        (
            "V-ITEM-NOSELLER",
            "order_items",
            "Line items pointing at a seller_id that does not exist",
            "SELECT COUNT(*) FROM order_items i LEFT JOIN sellers s ON s.seller_id=i.seller_id "
            "WHERE s.seller_id IS NULL",
        ),
        (
            "V-ORD-NOITEM",
            "orders",
            "Orders with no line items at all",
            "SELECT COUNT(*) FROM orders o LEFT JOIN order_items i ON i.order_id=o.order_id "
            "WHERE i.order_id IS NULL",
        ),
        (
            "V-ITEM-ORD",
            "order_items",
            "Line items whose order_id does not exist",
            "SELECT COUNT(*) FROM order_items i LEFT JOIN orders o ON o.order_id=i.order_id "
            "WHERE o.order_id IS NULL",
        ),
        (
            "V-TIME-DELIV",
            "orders",
            "Orders delivered before they were purchased (negative cycle time)",
            "SELECT COUNT(*) FROM orders WHERE order_delivered_customer_date IS NOT NULL "
            "AND julianday(order_delivered_customer_date) < julianday(order_purchase_timestamp)",
        ),
        (
            "V-TIME-APPR",
            "orders",
            "Orders approved before they were purchased",
            "SELECT COUNT(*) FROM orders WHERE order_approved_at IS NOT NULL "
            "AND julianday(order_approved_at) < julianday(order_purchase_timestamp)",
        ),
        (
            "V-AMT-ZERO",
            "payments",
            "Payment rows with a value of zero",
            "SELECT COUNT(*) FROM payments WHERE payment_value = 0",
        ),
        (
            "V-AMT-NEG",
            "payments",
            "Payment rows with a negative value",
            "SELECT COUNT(*) FROM payments WHERE payment_value < 0",
        ),
        (
            "V-PRICE-ZERO",
            "order_items",
            "Line items priced at zero",
            "SELECT COUNT(*) FROM order_items WHERE price = 0",
        ),
        (
            "V-FREIGHT-HIGH",
            "order_items",
            "Line items where the freight charge exceeds the merchandise price",
            "SELECT COUNT(*) FROM order_items WHERE freight_value > price",
        ),
        (
            "V-CAT-UNMAPPED",
            "order_items",
            "Products with a category that has no English translation",
            "SELECT COUNT(*) FROM products p LEFT JOIN product_category_translation t "
            "ON t.product_category_name = p.product_category_name "
            "WHERE p.product_category_name IS NOT NULL AND t.product_category_name IS NULL",
        ),
        (
            "V-REV-MULTI",
            "reviews",
            "Orders carrying more than one review row",
            "SELECT COUNT(*) FROM (SELECT order_id FROM reviews GROUP BY order_id "
            "HAVING COUNT(*) > 1)",
        ),
        (
            "V-REV-DUPID",
            "reviews",
            "review_id values recorded against more than one order (a single review "
            "submission duplicated across two orders of the same customer)",
            "SELECT COUNT(*) FROM (SELECT review_id FROM reviews GROUP BY review_id "
            "HAVING COUNT(DISTINCT order_id) > 1)",
        ),
        (
            "V-CUST-SPLIT",
            "customers",
            "customer_unique_id values mapped to more than one customer_id "
            "(identity fragmentation)",
            "SELECT COUNT(*) FROM (SELECT customer_unique_id FROM customers "
            "GROUP BY customer_unique_id HAVING COUNT(*) > 1)",
        ),
    ]
    for code, table, description, sql in checks:
        n = conn.execute(sql).fetchone()[0]
        add_rule(
            code,
            table,
            description,
            "validation",
            "Reported in reports/data_quality.md; excluded from metrics where noted",
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
            n,
        )

    conn.commit()

    # -------------------------------------------------------------- views
    views_sql = (config.SQL_DIR / "02_views.sql").read_text(encoding="utf-8")
    conn.executescript(views_sql)
    log("analytic views created")

    # ------------------------------------------------------- fact materialisation
    # `v_order_financials` is the DEFINITION of the order-level fact: it
    # re-aggregates payments, line items and reviews on every read, which is
    # correct for a view but slow for the ~30 aggregate queries and for the
    # flattened CSV that Power BI and Excel consume. The table below is a
    # materialised snapshot of that view, rebuilt from it on every run so the
    # two can never drift apart. `tests/test_analysis.py` reconciles them.
    conn.execute("DROP TABLE IF EXISTS fact_order_financials")
    conn.execute("CREATE TABLE fact_order_financials AS SELECT * FROM v_order_financials")
    conn.execute("CREATE INDEX idx_fof_order   ON fact_order_financials(order_id)")
    conn.execute("CREATE INDEX idx_fof_month   ON fact_order_financials(purchase_month)")
    conn.execute("CREATE INDEX idx_fof_status  ON fact_order_financials(status_class)")
    conn.execute("CREATE INDEX idx_fof_method  ON fact_order_financials(primary_payment_type)")
    conn.execute("CREATE INDEX idx_fof_cust    ON fact_order_financials(customer_unique_id)")
    conn.commit()
    fact_rows = conn.execute("SELECT COUNT(*) FROM fact_order_financials").fetchone()[0]
    log(f"fact_order_financials materialised: {fact_rows:,} rows")

    conn.executemany(
        """INSERT INTO dq_cleaning_rules
           (rule_id, rule_code, table_name, rule_description, rule_type,
            action_taken, records_in, records_out, records_affected)
           VALUES (:rule_id, :rule_code, :table_name, :rule_description, :rule_type,
                   :action_taken, :records_in, :records_out, :records_affected)""",
        rules,
    )
    conn.commit()

    # -------------------------------------------------------------- sanity
    view_counts = {}
    for view in config.ANALYTIC_VIEWS:
        view_counts[view] = conn.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
    for name, n in view_counts.items():
        log(f"view {name}: {n:,} rows")

    totals = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM orders)                                  AS orders,
            (SELECT COUNT(*) FROM payments)                                AS payments,
            (SELECT COUNT(*) FROM order_items)                             AS line_items,
            (SELECT ROUND(SUM(cash_collected),2) FROM v_order_financials)  AS cash_collected,
            (SELECT ROUND(SUM(gmv),2) FROM v_order_financials)             AS gmv,
            (SELECT ROUND(SUM(freight_total),2) FROM v_order_financials)   AS freight,
            (SELECT SUM(recon_break_flag) FROM v_order_financials)         AS recon_breaks
        """
    ).fetchone()
    log(f"control totals: {dict(totals)}")

    conn.close()
    log(f"database written to {config.DB_PATH}")


if __name__ == "__main__":
    build()
