"""Clean the warehouse into analysis-ready tables and publish them as CSV.

Pipeline step 2 of 4:  load -> clean -> query -> report.

WHAT THIS SCRIPT DOES
----------------------
1. Materialises the cleaned, analysis-ready order / payment / line-item
   tables from the warehouse.
2. Writes the derived analysis extracts (monthly financials, payment-method
   economics, seller concentration, reconciliation exceptions, KPI scorecard).
3. Writes the Power BI star-schema CSVs that the `.pbit` model consumes.
4. Applies the cleaning RULES that the source data actually requires, and
   records each one in `data/processed/cleaning_log.csv`.

CLEANING RULES APPLIED (and nothing else)
------------------------------------------
    R1  payment_installments = 0 -> NULL. Applied at load time; it is a
        meaningless instalment count and only appears on untyped payments.
    R2  Timestamps parsed to ISO-8601 text. Applied at load time.
    R3  Categorical text trimmed and lower-cased. Applied at load time.
    R4  No row is deleted. 775 orders carry cash but no line items; they are
        RETAINED and flagged (`line_item_count = 0`) because deleting them
        would hide R$162,592 of collected cash from every financial total.
    R5  No amount is edited. Payment values, prices and freight are used
        exactly as published; the reconciliation break is REPORTED rather
        than silently adjusted.
    R6  Customers are keyed on customer_unique_id, not customer_id, because
        2,997 real customers are split across several customer_id values.

Usage:
    python src/clean_data.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

# The order-level columns that the financial analysis depends on.
ORDER_COLUMNS = [
    "order_id", "customer_id", "customer_unique_id", "customer_state",
    "order_status", "status_class", "order_purchase_timestamp", "purchase_date",
    "purchase_month", "purchase_year", "purchase_quarter",
    "order_approved_at", "order_delivered_carrier_date",
    "order_delivered_customer_date", "order_estimated_delivery_date",
    "delivery_days", "days_late_vs_promise",
    "line_item_count", "seller_count", "product_count",
    "gmv", "freight_total", "expected_charge", "cash_collected", "recon_delta",
    "recon_break_flag", "payment_count", "max_installments", "installment_months",
    "primary_payment_type", "card_value", "boleto_value", "debit_card_value",
    "voucher_value", "undefined_value",
    "refund_exposure_value", "net_revenue", "settlement_float_value",
    "review_count", "worst_review_score", "avg_review_score",
    "duplicate_review_flag", "disputed_flag",
]

PAYMENT_COLUMNS = [
    "order_id", "payment_sequential", "payment_type", "payment_installments",
    "payment_value", "order_status", "status_class", "order_purchase_timestamp",
    "purchase_month", "purchase_year", "customer_state", "customer_unique_id",
    "refund_exposure_value", "voucher_value", "installment_credit_value",
]

ITEM_COLUMNS = [
    "order_id", "order_item_id", "product_id", "seller_id", "price",
    "freight_value", "line_charge", "product_category_name", "category_english",
    "product_weight_g", "seller_state", "seller_city", "order_status",
    "order_purchase_timestamp", "purchase_month", "purchase_year",
    "freight_over_price_flag", "large_line_flag",
]

CLEANING_LOG = [
    {
        "rule_id": "R1",
        "rule": "payment_installments = 0 set to NULL",
        "scope": "payments",
        "rationale": "Zero is not a meaningful instalment count; it appears only on untyped payments.",
        "action": "value nulled, row retained",
        "reversible": "yes - original value is recoverable from the raw CSV",
    },
    {
        "rule_id": "R2",
        "rule": "timestamps parsed to ISO-8601 'YYYY-MM-DD HH:MM:SS'",
        "scope": "orders, order_items, reviews",
        "rationale": "Source timestamps arrive in several formats; SQLite and Power BI need one.",
        "action": "value rewritten in place",
        "reversible": "yes - raw CSV retained",
    },
    {
        "rule_id": "R3",
        "rule": "categorical text trimmed and lower-cased",
        "scope": "orders, payments, customers, sellers, products",
        "rationale": "Removes stray whitespace and case variants that would split a category.",
        "action": "value rewritten in place",
        "reversible": "yes - raw CSV retained",
    },
    {
        "rule_id": "R4",
        "rule": "no row deleted, including 775 orders with cash and no line items",
        "scope": "orders",
        "rationale": "Deleting them would hide R$162,592 of collected cash from every total.",
        "action": "rows retained and flagged via line_item_count = 0",
        "reversible": "n/a - nothing removed",
    },
    {
        "rule_id": "R5",
        "rule": "no amount edited; reconciliation breaks reported, not adjusted",
        "scope": "payments, order_items",
        "rationale": "An unexplained difference is a finding to escalate, not a rounding error to hide.",
        "action": "flagged via recon_break_flag",
        "reversible": "n/a - nothing adjusted",
    },
    {
        "rule_id": "R6",
        "rule": "customers keyed on customer_unique_id rather than customer_id",
        "scope": "all customer-level aggregations",
        "rationale": "2,997 real customers are split across several customer_id values; counting on customer_id overstates the base by 3.5%.",
        "action": "aggregation key changed",
        "reversible": "yes - both keys are published",
    },
    {
        "rule_id": "R7",
        "rule": "partial boundary months excluded from trend and year-on-year analysis",
        "scope": "monthly and YoY extracts",
        "rationale": "The dataset opens with 4 orders (Sep 2016) and closes with 4 (Oct 2018); comparing them with full months would manufacture growth.",
        "action": f"window restricted to {config.CLEAN_WINDOW_LABEL}",
        "reversible": "yes - the full series is published alongside",
    },
]


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    print(f"[clean_data] wrote {path.name}: {len(df):,} rows")


def main() -> None:
    conn = sqlite3.connect(config.DB_PATH)

    # ------------------------------------------------------- cleaned entities
    orders = pd.read_sql_query(
        f"SELECT {', '.join(ORDER_COLUMNS)} FROM fact_order_financials ORDER BY order_id", conn
    )
    payments = pd.read_sql_query(
        f"SELECT {', '.join(PAYMENT_COLUMNS)} FROM v_payment_detail ORDER BY order_id, payment_sequential", conn
    )
    items = pd.read_sql_query(
        f"SELECT {', '.join(ITEM_COLUMNS)} FROM v_item_financials ORDER BY order_id, order_item_id", conn
    )
    _write(orders, config.PROCESSED_FILES["clean_orders"])
    _write(payments, config.PROCESSED_FILES["clean_payments"])
    _write(items, config.PROCESSED_FILES["clean_order_items"])

    # ------------------------------------------------------- monthly extract
    monthly = pd.read_sql_query(
        """
        SELECT purchase_month,
               COUNT(*)                        AS orders,
               COUNT(DISTINCT customer_unique_id) AS active_customers,
               ROUND(SUM(gmv),2)               AS gmv,
               ROUND(SUM(freight_total),2)     AS freight_collected,
               ROUND(SUM(cash_collected),2)    AS cash_collected,
               ROUND(SUM(refund_exposure_value),2) AS refund_exposure,
               ROUND(SUM(net_revenue),2)      AS net_revenue,
               ROUND(SUM(settlement_float_value),2) AS settlement_float,
               ROUND(SUM(cash_collected)/COUNT(*),2) AS average_order_value,
               ROUND(100.0*SUM(refund_exposure_value)/SUM(cash_collected),3) AS refund_exposure_pct,
               ROUND(100.0*SUM(freight_total)/SUM(gmv),2)  AS freight_ratio_pct,
               ROUND(SUM(recon_break_flag),0)  AS reconciliation_breaks,
               CASE WHEN COUNT(*) < 100 THEN 'partial' ELSE 'full' END AS month_coverage
        FROM fact_order_financials
        GROUP BY purchase_month
        ORDER BY purchase_month
        """,
        conn,
    )
    monthly["mom_cash_growth_pct"] = (
        monthly["cash_collected"].pct_change() * 100
    ).round(2)
    _write(monthly, config.PROCESSED_FILES["monthly_financials"])

    # ------------------------------------------- payment method economics
    method = pd.read_sql_query(
        """
        WITH params(payment_type, pct_rate, fixed_fee) AS (
            VALUES ('credit_card', 0.029, 0.00),
                   ('debit_card', 0.015, 1.50),
                   ('boleto',       0.000, 3.00),
                   ('voucher',      0.000, 0.00),
                   ('not_defined',  0.000, 0.00)
        ),
        funding(rate) AS (VALUES (0.0199)),
        pay AS (
            SELECT p.payment_type, p.payment_value,
                   COALESCE(p.payment_installments,1) AS installments,
                   pa.pct_rate, pa.fixed_fee, f.rate AS funding_rate
            FROM payments p
            JOIN params pa ON pa.payment_type = p.payment_type
            CROSS JOIN funding f
        )
        SELECT payment_type,
               COUNT(*)                    AS payment_rows,
               COUNT(DISTINCT payment_value) AS distinct_values,
               ROUND(SUM(payment_value),2) AS gross_value,
               ROUND(100.0*SUM(payment_value)/(SELECT SUM(payment_value) FROM payments),3) AS pct_of_value,
               ROUND(AVG(payment_value),2) AS average_payment_value,
               ROUND(AVG(installments),3)  AS average_installments,
               SUM(installments)           AS installment_months,
               ROUND(SUM(payment_value*pct_rate + fixed_fee),2) AS modelled_acquiring_cost,
               ROUND(SUM(CASE WHEN payment_type='credit_card'
                              THEN payment_value*funding_rate*(installments-1) ELSE 0 END),2) AS modelled_installment_funding_cost,
               ROUND(SUM(payment_value*pct_rate + fixed_fee
                         + CASE WHEN payment_type='credit_card'
                                THEN payment_value*funding_rate*(installments-1) ELSE 0 END),2) AS modelled_total_cost,
               ROUND(100.0*SUM(payment_value*pct_rate + fixed_fee
                         + CASE WHEN payment_type='credit_card'
                                THEN payment_value*funding_rate*(installments-1) ELSE 0 END)
                     /NULLIF(SUM(payment_value),0),3) AS modelled_cost_pct_of_value
        FROM pay
        GROUP BY payment_type
        ORDER BY gross_value DESC
        """,
        conn,
    )
    _write(method, config.PROCESSED_FILES["payment_method_financials"])

    # ------------------------------------------------- seller concentration
    sellers = pd.read_sql_query(
        """
        WITH s AS (SELECT seller_id, SUM(price) AS gmv FROM order_items GROUP BY seller_id),
             ranked AS (SELECT seller_id, gmv, RANK() OVER (ORDER BY gmv DESC) AS rnk,
                               SUM(gmv) OVER () AS total FROM s),
             with_pct AS (
                SELECT r.seller_id, r.rnk, r.gmv, r.total,
                       100.0*r.gmv/r.total AS pct_of_total_gmv,
                       SUM(CASE WHEN r2.rnk <= r.rnk THEN r2.gmv ELSE 0 END) OVER (ORDER BY r.rnk)
                          AS cumulative_gmv
                FROM ranked r JOIN ranked r2 ON r2.rnk <= r.rnk
                GROUP BY r.seller_id, r.rnk, r.gmv, r.total
             )
        SELECT w.seller_id, p.seller_state, w.rnk AS gmv_rank, ROUND(w.gmv,2) AS seller_gmv,
               ROUND(w.pct_of_total_gmv,4) AS pct_of_total_gmv,
               ROUND(100.0*w.cumulative_gmv/w.total,3) AS cumulative_pct_of_gmv
        FROM with_pct w
        LEFT JOIN v_seller_performance p ON p.seller_id = w.seller_id
        ORDER BY w.rnk
        """,
        conn,
    )
    _write(sellers, config.PROCESSED_FILES["seller_concentration"])

    # ---------------------------------------------- reconciliation exceptions
    breaks = pd.read_sql_query(
        """
        SELECT order_id, order_status, status_class, primary_payment_type,
               ROUND(gmv,2)             AS gmv,
               ROUND(freight_total,2)  AS freight,
               ROUND(expected_charge,2) AS expected_charge,
               ROUND(cash_collected,2)  AS cash_collected,
               ROUND(recon_delta,2)     AS break_amount,
               CASE WHEN line_item_count = 0 THEN 'no line items at all'
                    ELSE 'price/charge mismatch' END AS break_reason,
               CASE WHEN ABS(recon_delta) < 1    THEN 'rounding (< R$1)'
                    WHEN ABS(recon_delta) < 100  THEN 'R$1 - R$100'
                    WHEN ABS(recon_delta) < 1000 THEN 'R$100 - R$1,000'
                    ELSE 'R$1,000+' END AS size_band,
               line_item_count, purchase_date, customer_state, disputed_flag
        FROM fact_order_financials
        WHERE recon_break_flag = 1
        ORDER BY ABS(recon_delta) DESC
        """,
        conn,
    )
    _write(breaks, config.PROCESSED_FILES["reconciliation_breaks"])

    # ------------------------------------------------------- KPI scorecard
    kpi = pd.read_sql_query(
        """
        SELECT 'KPI 01 GMV (merchandise value)' AS kpi, ROUND((SELECT SUM(gmv) FROM fact_order_financials),2) AS value, 'BRL' AS unit, 'measured' AS basis
        UNION ALL SELECT 'KPI 02 Cash collected', ROUND((SELECT SUM(cash_collected) FROM fact_order_financials),2), 'BRL', 'measured'
        UNION ALL SELECT 'KPI 03 Refund exposure', ROUND((SELECT SUM(refund_exposure_value) FROM fact_order_financials),2), 'BRL', 'measured (proxy)'
        UNION ALL SELECT 'KPI 04 Net revenue', ROUND((SELECT SUM(net_revenue) FROM fact_order_financials),2), 'BRL', 'measured'
        UNION ALL SELECT 'KPI 05 Average order value', ROUND((SELECT SUM(cash_collected)/COUNT(*) FROM fact_order_financials),2), 'BRL', 'measured'
        UNION ALL SELECT 'KPI 06 Freight ratio', ROUND((SELECT 100.0*SUM(freight_total)/SUM(gmv) FROM fact_order_financials),2), 'pct of GMV', 'measured'
        UNION ALL SELECT 'KPI 07 Reconciliation break rate', ROUND((SELECT 100.0*SUM(recon_break_flag)/COUNT(*) FROM fact_order_financials),3), 'pct of orders', 'measured'
        UNION ALL SELECT 'KPI 08 Value-weighted instalment depth', ROUND((SELECT SUM(payment_installments*payment_value)/SUM(payment_value) FROM payments WHERE payment_type='credit_card'),3), 'instalments', 'measured'
        UNION ALL SELECT 'KPI 09 Disputed value at risk', ROUND((SELECT SUM(CASE WHEN disputed_flag=1 THEN cash_collected ELSE 0 END) FROM fact_order_financials),2), 'BRL', 'measured (proxy)'
        UNION ALL SELECT 'KPI 10 Seller HHI', ROUND((SELECT SUM(g*g)/((SELECT SUM(seller_gmv) FROM v_seller_performance)*(SELECT SUM(seller_gmv) FROM v_seller_performance)) FROM (SELECT seller_gmv AS g FROM v_seller_performance)),5), 'index', 'measured'
        UNION ALL SELECT 'KPI 11 Settlement float', ROUND((SELECT SUM(settlement_float_value) FROM fact_order_financials),2), 'BRL', 'measured'
        UNION ALL SELECT 'KPI 12 Repeat customer rate', ROUND((SELECT 100.0*COUNT(*)/(SELECT COUNT(DISTINCT customer_unique_id) FROM fact_order_financials) FROM (SELECT customer_unique_id FROM fact_order_financials GROUP BY customer_unique_id HAVING COUNT(*)>1)),3), 'pct of customers', 'measured'
        """,
        conn,
    )
    _write(kpi, config.PROCESSED_FILES["kpi_summary"])

    # --------------------------------------------------------- cleaning log
    log = pd.DataFrame(CLEANING_LOG)
    _write(log, config.PROCESSED_DIR / "cleaning_log.csv")

    conn.close()


if __name__ == "__main__":
    main()
