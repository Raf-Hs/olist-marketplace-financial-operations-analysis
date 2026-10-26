"""Automated checks on the analysis pipeline.

These are not unit tests of Python syntax - they are financial controls.
Each test asserts a number, a relationship or a data-quality result that the
analysis depends on, so that a change in the code that silently alters a
figure fails the build.

Run:
    python -m pytest tests/ -v
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402

DB = config.DB_PATH
METRICS = config.REPORTS_DIR / "key_metrics.json"


@pytest.fixture(scope="module")
def conn() -> sqlite3.Connection:
    if not DB.exists():
        pytest.skip(f"{DB} not built - run src/build_db.py first")
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def metrics() -> dict:
    if not METRICS.exists():
        pytest.skip(f"{METRICS} not built - run src/analyze.py first")
    return json.loads(METRICS.read_text(encoding="utf-8"))


def scalar(conn: sqlite3.Connection, sql: str):
    return conn.execute(sql).fetchone()[0]


# ---------------------------------------------------------------------------
# Structural controls
# ---------------------------------------------------------------------------
def test_source_row_counts_match_the_published_dataset(conn):
    """The eight source tables must hold the published row counts."""
    assert scalar(conn, "SELECT COUNT(*) FROM orders") == 99_441
    assert scalar(conn, "SELECT COUNT(*) FROM customers") == 99_441
    assert scalar(conn, "SELECT COUNT(*) FROM order_items") == 112_650
    assert scalar(conn, "SELECT COUNT(*) FROM payments") == 103_886
    assert scalar(conn, "SELECT COUNT(*) FROM reviews") == 99_224
    assert scalar(conn, "SELECT COUNT(*) FROM products") == 32_951
    assert scalar(conn, "SELECT COUNT(*) FROM sellers") == 3_095


def test_referential_integrity_is_clean(conn):
    """No orphans on any declared foreign key."""
    for sql in [
        "SELECT COUNT(*) FROM order_items i LEFT JOIN orders o ON o.order_id=i.order_id WHERE o.order_id IS NULL",
        "SELECT COUNT(*) FROM order_items i LEFT JOIN products p ON p.product_id=i.product_id WHERE p.product_id IS NULL",
        "SELECT COUNT(*) FROM order_items i LEFT JOIN sellers s ON s.seller_id=i.seller_id WHERE s.seller_id IS NULL",
        "SELECT COUNT(*) FROM payments p LEFT JOIN orders o ON o.order_id=p.order_id WHERE o.order_id IS NULL",
        "SELECT COUNT(*) FROM reviews r LEFT JOIN orders o ON o.order_id=r.order_id WHERE o.order_id IS NULL",
        "SELECT COUNT(*) FROM orders o LEFT JOIN customers c ON c.customer_id=o.customer_id WHERE c.customer_id IS NULL",
    ]:
        assert scalar(conn, sql) == 0


def test_primary_keys_are_unique(conn):
    for table, columns in [
        ("orders", "order_id"),
        ("customers", "customer_id"),
        ("payments", "order_id || '|' || payment_sequential"),
        ("reviews", "review_id || '|' || order_id"),
        ("products", "product_id"),
        ("sellers", "seller_id"),
    ]:
        total = scalar(conn, f"SELECT COUNT(*) FROM {table}")
        distinct = scalar(conn, f"SELECT COUNT(DISTINCT {columns}) FROM {table}")
        assert total == distinct, f"{table} has duplicate keys"


def test_no_negative_or_nan_amounts(conn):
    assert scalar(conn, "SELECT COUNT(*) FROM payments WHERE payment_value < 0") == 0
    assert scalar(conn, "SELECT COUNT(*) FROM order_items WHERE price < 0") == 0
    assert scalar(conn, "SELECT COUNT(*) FROM order_items WHERE freight_value < 0") == 0
    assert scalar(conn, "SELECT COUNT(*) FROM payments WHERE payment_value IS NULL") == 0


def test_fact_table_agrees_with_its_defining_view(conn):
    """The materialised fact must reconcile to v_order_financials."""
    diff = conn.execute(
        """
        SELECT COUNT(*) FROM fact_order_financials f
        JOIN v_order_financials v USING (order_id)
        WHERE ABS(f.cash_collected - v.cash_collected) > 0.005
           OR ABS(f.gmv - v.gmv) > 0.005
           OR f.status_class <> v.status_class
           OR f.recon_break_flag <> v.recon_break_flag
        """
    ).fetchone()[0]
    assert diff == 0


# ---------------------------------------------------------------------------
# Financial identities
# ---------------------------------------------------------------------------
def test_cash_collected_equals_the_sum_of_payments(conn):
    fact = scalar(conn, "SELECT ROUND(SUM(cash_collected),2) FROM fact_order_financials")
    raw = scalar(conn, "SELECT ROUND(SUM(payment_value),2) FROM payments")
    assert abs(fact - raw) < 0.02


def test_gmv_plus_freight_equals_expected_charge(conn):
    diff = scalar(
        conn,
        "SELECT ROUND(SUM(ABS(expected_charge - (gmv + freight_total))),2) "
        "FROM fact_order_financials",
    )
    assert diff < 0.02


def test_net_revenue_is_cash_less_refund_exposure(conn):
    diff = scalar(
        conn,
        "SELECT ROUND(SUM(ABS(net_revenue - (cash_collected - refund_exposure_value))),2) "
        "FROM fact_order_financials",
    )
    assert diff < 0.02


def test_reconciliation_break_flag_matches_the_tolerance(conn):
    """The flag must agree with |cash - expected| >= 0.01, computed independently."""
    mismatches = scalar(
        conn,
        """
        SELECT COUNT(*) FROM fact_order_financials
        WHERE (recon_break_flag = 1 AND ABS(recon_delta) < 0.009)
           OR (recon_break_flag = 0 AND ABS(recon_delta) >= 0.011)
        """,
    )
    assert mismatches == 0


def test_cash_without_merchandise_is_excluded_from_gmv(conn):
    """Orders with no line items must contribute nothing to GMV."""
    value = scalar(
        conn,
        "SELECT ROUND(SUM(gmv),2) FROM fact_order_financials WHERE line_item_count = 0",
    )
    assert value == 0.0


def test_aov_is_cash_over_orders(metrics):
    h = metrics["headline"]
    assert abs(h["aov"] - round(h["cash_collected"] / h["orders"], 2)) < 0.02


# ---------------------------------------------------------------------------
# Headline figures - regression-locked to the analysis
# ---------------------------------------------------------------------------
def test_headline_totals(metrics):
    h = metrics["headline"]
    assert h["orders"] == 99_441
    assert h["unique_customers"] == 96_096
    assert round(h["gmv"], 2) == 13_591_643.70
    assert round(h["cash_collected"], 2) == 16_008_872.12
    assert round(h["freight"], 2) == 2_256_599.44
    assert round(h["refund_exposure"], 2) == 269_735.11
    assert round(h["net_revenue"], 2) == 15_739_137.01


def test_reconciliation_totals(metrics):
    r = metrics["reconciliation"]
    assert r["orders_in_break"] == 1_220
    assert r["paid_orders_without_line_items"] == 772
    assert round(r["cash_without_merchandise"], 2) == 162_591.95
    assert round(r["gross_break_value"], 2) == 170_716.88


def test_refund_exposure_covers_cancelled_and_unavailable_only(metrics):
    total = metrics["refund_exposure_total"]
    assert total["orders"] == 1_234
    assert round(total["refund_exposure"], 2) == 269_735.11
    assert total["orders_without_line_items"] == 767


def test_like_for_like_growth(metrics):
    y = metrics["yoy"]
    assert y["cash_growth_pct"] == 136.98
    assert y["orders_growth_pct"] == 135.07
    assert y["aov_growth_pct"] == 0.81
    assert y["freight_ratio_change_pts"] == 1.08


def test_payment_mix_shares_sum_to_100(metrics):
    total = sum(row["pct_of_value"] for row in metrics["payment_mix"])
    assert abs(total - 100) < 0.05


def test_installment_exposure(metrics):
    i = metrics["installments"]
    assert i["value_on_installment_plans"] == 10_101_491.12
    assert i["pct_of_card_value_on_installments"] == 80.541
    assert i["value_weighted_average_installments"] == 4.967


def test_dispute_rate_rises_with_instalment_depth(metrics):
    """The finding is a monotone gradient; if it stops holding, the claim fails."""
    rows = metrics["dispute_by_installments"]
    rates = [row["dispute_rate_pct"] for row in rows]
    assert rates == sorted(rates), f"dispute rate is not monotone: {rates}"
    assert rates[-1] > rates[0]


def test_seller_concentration_is_low(metrics):
    s = metrics["seller_concentration"]
    assert s["sellers"] == 3_095
    assert s["hhi"] < 0.15, "the market is no longer unconcentrated"
    assert s["top10_pct"] < 20


def test_customer_identity_fragmentation_is_measured(metrics):
    """Customer counts must use customer_unique_id, not customer_id."""
    f = metrics["identity_fragmentation"]
    assert f["customer_rows"] == 99_441
    assert f["unique_customers"] == 96_096
    assert f["customers_split_across_ids"] == 2_997


# ---------------------------------------------------------------------------
# The modelled layer must stay labelled and bounded
# ---------------------------------------------------------------------------
def test_modelled_costs_are_marked_as_modelled(metrics):
    assert metrics["cost_model"]["basis"] == "modelled"
    assert metrics["cost_model"]["installment_funding_cost"] > 0
    assert len(metrics["cost_model"]["sensitivity"]) == 3


def test_sql_cost_model_matches_the_python_cost_model(conn, metrics):
    """The assumption held in config.py must be the one the SQL uses."""
    sql_text = (config.SQL_DIR / "05_payment_mix_and_cost.sql").read_text(encoding="utf-8")
    assert str(config.INSTALLMENT_FUNDING_RATE) in sql_text
    for method, (pct_rate, fixed_fee, _) in config.PAYMENT_COST_MODEL.items():
        assert f"'{method}'" in sql_text, f"{method} is missing from the SQL cost model"
        assert f"{pct_rate:.3f}" in sql_text, f"{method} rate {pct_rate} missing from SQL"
        assert f"{fixed_fee:.2f}" in sql_text, f"{method} fee {fixed_fee} missing from SQL"


def test_cost_model_sensitivity_is_ordered_and_bracketed(metrics):
    rates = [row["rate"] for row in metrics["cost_model"]["sensitivity"]]
    assert rates == sorted(rates)
    assert rates[0] <= config.INSTALLMENT_FUNDING_RATE <= rates[-1]


def test_contribution_margin_is_positive_but_thinner_than_reported_revenue(metrics):
    c = metrics["cost_model"]
    assert c["contribution_after_payment_cost"] > 0
    assert c["contribution_margin_pct"] < 100
    assert c["total_modelled_payment_cost"] < metrics["headline"]["net_revenue"]


# ---------------------------------------------------------------------------
# Deliverables exist and agree with each other
# ---------------------------------------------------------------------------
def test_kpi_summary_csv_matches_the_metrics_json(metrics):
    path = config.PROCESSED_FILES["kpi_summary"]
    if not path.exists():
        pytest.skip("processed KPIs not built")
    kpi = pd.read_csv(path)
    lookup = dict(zip(kpi["kpi"], kpi["value"]))
    assert round(lookup["KPI 02 Cash collected"], 2) == round(
        metrics["headline"]["cash_collected"], 2
    )
    assert round(lookup["KPI 04 Net revenue"], 2) == round(
        metrics["headline"]["net_revenue"], 2
    )
    assert round(lookup["KPI 07 Reconciliation break rate"], 3) == round(
        metrics["headline"]["reconciliation_break_rate_pct"], 3
    )


def test_excel_workbook_exists_with_the_expected_sheets():
    path = config.EXCEL_PATH
    if not path.exists():
        pytest.skip("Excel workbook not built")
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True)
    expected = {
        "README", "KPI Scorecard", "Monthly Financials", "Revenue & Growth",
        "Payment Mix", "Refund Exposure", "Reconciliation", "Seller Concentration",
        "Category Logistics", "Dispute Risk", "Data Quality", "Order Records",
    }
    assert expected.issubset(set(wb.sheetnames))
    wb.close()


def test_powerbi_model_declares_every_measure_the_report_uses():
    """A visual that references a missing measure renders empty."""
    model_path = config.POWERBI_DIR / "MarketplaceFinance" / \
        "MarketplaceFinance.SemanticModel" / "model.bim"
    report_path = config.POWERBI_DIR / "MarketplaceFinance" / \
        "MarketplaceFinance.Report" / "report.json"
    if not model_path.exists() or not report_path.exists():
        pytest.skip("Power BI project not built")

    model = json.loads(model_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    measures = {
        measure["name"]
        for table in model["model"]["tables"]
        for measure in table.get("measures", [])
    }
    columns = {
        f"{table['name']}[{column['name']}]"
        for table in model["model"]["tables"]
        for column in table["columns"]
    }
    available = measures | columns

    missing: list[str] = []
    for section in report["sections"]:
        for visual in section["visualContainers"]:
            config_json = json.loads(visual["config"])
            single = config_json.get("singleVisual", {})
            projections = single.get("projections", {})
            for value in projections.values():
                refs = value if isinstance(value, list) else [value]
                for ref in refs:
                    name = ref["queryRef"]
                    if name not in available and "[" in name:
                        missing.append(name)
    assert not missing, f"visuals reference unknown fields: {sorted(set(missing))}"


def test_powerbi_report_visuals_are_bound_to_fields():
    """Every data visual must bind its fields, or it renders empty.

    Power BI Desktop reads a PBIP report from the PBIR `definition/` folder.
    The legacy `report.json` carries the same information in a
    `singleVisual.projections` block, which the Desktop discards - so the
    binding has to live in `visual.query.queryState`.
    """
    pbir = config.POWERBI_DIR / "MarketplaceFinance" / "MarketplaceFinance.Report" / "definition"
    if not pbir.exists():
        pytest.skip("Power BI PBIR definition not built")

    visual_files = sorted(pbir.glob("pages/*/visuals/*/visual.json"))
    assert visual_files, "no PBIR visuals found"

    bound = 0
    unbound = []
    for path in visual_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        visual = payload.get("visual", {})
        if visual.get("visualType") in ("textbox",):
            continue
        if visual.get("query", {}).get("queryState"):
            bound += 1
        else:
            unbound.append(f"{path.parent.name} ({visual.get('visualType')})")

    assert bound >= 50, f"only {bound} visuals carry field bindings"
    assert not unbound, f"visuals with no field binding: {unbound}"


def test_powerbi_pbir_bindings_reference_real_model_fields():
    """A projection that points at a missing field renders an empty visual."""
    pbir = config.POWERBI_DIR / "MarketplaceFinance" / "MarketplaceFinance.Report" / "definition"
    model_path = config.POWERBI_DIR / "MarketplaceFinance" / \
        "MarketplaceFinance.SemanticModel" / "model.bim"
    if not pbir.exists() or not model_path.exists():
        pytest.skip("Power BI project not built")

    model = json.loads(model_path.read_text(encoding="utf-8"))
    available = set()
    for table in model["model"]["tables"]:
        for column in table["columns"]:
            available.add(f"{table['name']}.{column['name']}")
        for measure in table.get("measures", []):
            available.add(f"{table['name']}.{measure['name']}")

    missing = []
    for path in sorted(pbir.glob("pages/*/visuals/*/visual.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for role in payload.get("visual", {}).get("projections", {}).values():
            for projection in role:
                name = projection["queryRef"]
                if name not in available:
                    missing.append(name)
    assert not missing, f"PBIR bindings point at unknown fields: {sorted(set(missing))}"


def test_no_measure_shares_a_name_with_a_column_in_the_same_table():
    """Power BI refuses to load a model where a measure shadows a column."""
    model_path = config.POWERBI_DIR / "MarketplaceFinance" / \
        "MarketplaceFinance.SemanticModel" / "model.bim"
    if not model_path.exists():
        pytest.skip("Power BI project not built")
    model = json.loads(model_path.read_text(encoding="utf-8"))
    for table in model["model"]["tables"]:
        column_names = {column["name"] for column in table["columns"]}
        measure_names = {measure["name"] for measure in table.get("measures", [])}
        clash = column_names & measure_names
        assert not clash, f"{table['name']}: measure/column clash on {sorted(clash)}"


def test_reports_are_present_and_non_trivial():
    for path, minimum in [
        (config.REPORTS_DIR / "executive_summary.md", 1_500),
        (config.REPORTS_DIR / "findings.md", 3_000),
        (config.REPORTS_DIR / "business_decision_report.md", 1_500),
        (config.REPORTS_DIR / "sql_results.md", 10_000),
        (config.REPORTS_DIR / "data_quality.md", 1_000),
        (config.PROJECT_ROOT / "README.md", 3_000),
    ]:
        if not path.exists():
            pytest.skip(f"{path.name} not built")
        assert path.stat().st_size > minimum, f"{path.name} looks truncated"


def test_reports_never_claim_an_unmeasured_impact():
    """Guard against the classic failure mode: claiming a saving that was not measured.

    A phrase only counts as a CLAIM when it is not negated - "no saving was
    measured" is the opposite of a claim, and the reports are allowed to say
    that out loud.
    """
    forbidden = [
        "reduced costs by",
        "saved r$",
        "prevented fraud",
        "increased profit by",
        "eliminated the loss",
        "delivered a saving",
        "reduced refunds by",
    ]
    negations = ("no ", "not ", "never", "cannot", "can't", "without", "nor ",
                 "nothing", "any saving", "no saving", "claims no")
    for path in [
        config.REPORTS_DIR / "findings.md",
        config.REPORTS_DIR / "business_decision_report.md",
        config.REPORTS_DIR / "executive_summary.md",
        config.PROJECT_ROOT / "README.md",
    ]:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for phrase in forbidden:
            start = 0
            while True:
                index = text.find(phrase, start)
                if index == -1:
                    break
                context = text[max(0, index - 90):index]
                if not any(negation in context for negation in negations):
                    raise AssertionError(
                        f"{path.name} contains an unmeasured impact claim: '{phrase}' "
                        f"(context: ...{context[-70:]!r})"
                    )
                start = index + len(phrase)
