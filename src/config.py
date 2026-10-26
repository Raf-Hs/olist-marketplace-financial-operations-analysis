"""Central configuration for the Olist Marketplace Financial Operations analysis.

Every path is resolved relative to the project root so the pipeline runs from
any working directory.

This module is the *single source of truth* for the rules that the SQL layer,
the Python analysis, the Excel workbook, the Power BI model, the report and
the tests must all agree on. If a rule changes here it changes everywhere; no
magic numbers are duplicated downstream.

Metric definitions implemented here and asserted in `tests/test_analysis.py`:

    KPI 1  GMV                 SUM(order_items.price) - merchandise value ordered
    KPI 2  Cash collected      SUM(payments.payment_value) - what customers paid
    KPI 3  Refund exposure     cash collected on orders that were cancelled or
                                became unavailable (proxy; refunds are not
                                recorded in the source data)
    KPI 4  Net revenue         cash collected - refund exposure
    KPI 5  AOV                 cash collected / orders with a payment
    KPI 6  Freight ratio       freight collected / GMV (logistics cost-to-serve)
    KPI 7  Recon break rate    orders where |paid - (price + freight)| >= 0.01
    KPI 8  Installment depth   weighted average payment_installments on spend
    KPI 9  Disputed value      spend on orders reviewed 1-2 (chargeback proxy)
    KPI 10 Seller concentration HHI of seller GMV share + top-N share
    KPI 11 Settlement float    cash collected on orders not yet delivered
    KPI 12 Contribution margin cash collected - modelled cost-to-serve

IMPORTANT - ASSUMPTIONS vs FACTS
--------------------------------
KPIs 1-5 and 7-11 are *measured* from the source data. KPI 12 depends on the
market rate assumptions in `PAYMENT_COST_MODEL` and `INSTALLMENT_FUNDING_RATE`
below. Every figure derived from those assumptions is labelled as a model
output in the reports and the Excel workbook, and a sensitivity table is
published so the reader can see how much the conclusion depends on the
assumption.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
SQL_DIR = PROJECT_ROOT / "sql"
SRC_DIR = PROJECT_ROOT / "src"
REPORTS_DIR = PROJECT_ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"
EXCEL_DIR = PROJECT_ROOT / "excel"
POWERBI_DIR = PROJECT_ROOT / "powerbi"
POWERBI_DATA_DIR = POWERBI_DIR / "MarketplaceFinance" / "Data"
TESTS_DIR = PROJECT_ROOT / "tests"
DOCS_DIR = PROJECT_ROOT / "docs"

DB_PATH = PROJECT_ROOT / "marketplace_finance.db"
EXCEL_PATH = EXCEL_DIR / "Marketplace_Financial_Ops_Dashboard.xlsx"
PBIT_PATH = POWERBI_DIR / "MarketplaceFinance.pbit"

RAW_TABLES = {
    "customers": "olist_customers_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "product_category_translation": "product_category_name_translation.csv",
}

# ---------------------------------------------------------------------------
# Dataset provenance
# ---------------------------------------------------------------------------
DATASET_NAME = "Brazilian E-Commerce Public Dataset by Olist"
DATASET_PUBLISHER = "Olist (olistbr) / Andre Sionek"
DATASET_PUBLISHED = "2018"
DATASET_URL = "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce"
DATASET_MIRROR = (
    "https://github.com/olist/work-at-olist-data/tree/master/datasets"
)
DATASET_LICENSE = (
    "CC BY-NC-SA 4.0 (Olist public release; non-commercial use, attribution "
    "and share-alike required)"
)
DATASET_NATURE = "REAL commercial data, anonymised by Olist"
CURRENCY = "BRL"

# ---------------------------------------------------------------------------
# Business rules - revenue recognition policy
# ---------------------------------------------------------------------------
# Statuses that represent a *fulfilled* commercial transaction. An order in
# any of these states is treated as earned revenue.
STATUS_FULFILLED = ("delivered",)
# Order is live and expected to be fulfilled (cash collected, work in flight).
STATUS_IN_FLIGHT = ("shipped", "invoiced", "processing", "created", "approved")
# Order will never be fulfilled. Cash collected against these orders is
# classified as REFUND EXPOSURE (a proxy: the source data has no refund
# table, so this is the amount that was collected and is owed back).
STATUS_CANCELLED = ("canceled",)
STATUS_UNAVAILABLE = ("unavailable",)
STATUS_NON_EARNED = STATUS_CANCELLED + STATUS_UNAVAILABLE

STATUS_CLASS = {
    "delivered": "fulfilled",
    "shipped": "in_flight",
    "invoiced": "in_flight",
    "processing": "in_flight",
    "created": "in_flight",
    "approved": "in_flight",
    "canceled": "cancelled",
    "unavailable": "unavailable",
}

# Payment methods. `voucher` is a marketplace-funded promotional credit, so
# it is a revenue reduction rather than a customer payment.
PAYMENT_METHODS = ("credit_card", "boleto", "voucher", "debit_card", "not_defined")
PROMOTIONAL_METHODS = ("voucher",)

# ---------------------------------------------------------------------------
# ASSUMPTIONS - market cost-to-serve model (NOT measured in the data)
# ---------------------------------------------------------------------------
# Brazilian acquiring / payment market rates used to build the cost-to-serve
# model. Percentages are applied to the payment value; fixed fees are in BRL.
# These are assumptions published for sensitivity analysis, not facts about
# this marketplace.
PAYMENT_COST_MODEL = {
    # method: (percent_of_value, fixed_fee_brl, note)
    "credit_card": (0.029, 0.00, "card acquiring + MDR, typical Brazilian market rate"),
    "debit_card": (0.015, 1.50, "debit acquiring + per-transaction fee"),
    "boleto": (0.000, 3.00, "bank slip: per-instruction bank fee"),
    "voucher": (0.000, 0.00, "marketplace-funded credit: no acquiring cost, full cost is the subsidy"),
    "not_defined": (0.000, 0.00, "excluded from the model"),
}

# Cost of financing a card sale that the customer pays in N installments.
# Brazilian acquirers charge roughly 1.5%-2.5% per installment for
# anticipation. The base case uses the mid-point; the sensitivity band is
# 1.00% - 2.99% per installment.
INSTALLMENT_FUNDING_RATE = 0.0199
INSTALLMENT_FUNDING_SENSITIVITY = (0.0100, 0.0199, 0.0299)

# Discount rate used to discount the value of a 1-star or 2-star review from
# the moment of purchase to the moment the review is written (average of
# ~8 months of review lag). Used for the dispute-value-at-risk figure.
DISPUTE_DISCOUNT_RATE = 0.0100

# Reconciliation tolerance in BRL. Differences below this are treated as
# rounding noise; at or above it the order is a reconciliation break.
RECON_TOLERANCE = 0.01

# Outlier thresholds for the transaction-anomaly screen.
FREIGHT_RATIO_OUTLIER = 1.00   # freight exceeds the merchandise value of the item
AMOUNT_P99_OUTLIER = 3000.00   # BRL, flag top 1% style large transactions

# ---------------------------------------------------------------------------
# Derived layer names
# ---------------------------------------------------------------------------
ANALYTIC_VIEWS = (
    "dim_date",
    "v_order_financials",
    "v_payment_detail",
    "v_item_financials",
    "v_seller_performance",
    "v_category_financials",
)

PROCESSED_TABLES = (
    "clean_orders",
    "clean_payments",
    "clean_order_items",
    "monthly_financials",
    "payment_method_financials",
    "seller_concentration",
    "reconciliation_breaks",
    "kpi_summary",
)

# ---------------------------------------------------------------------------
# SQL query sections executed by src/run_queries.py
# ---------------------------------------------------------------------------
SQL_SECTIONS = (
    ("03_data_quality.sql", "Data quality and control checks"),
    ("04_revenue_and_cash.sql", "Revenue, cash and the reconciliation gap"),
    ("05_payment_mix_and_cost.sql", "Payment mix and modelled cost-to-serve"),
    ("06_exposure_and_reconciliation.sql", "Refund exposure and reconciliation breaks"),
    ("07_concentration_and_risk.sql", "Concentration, logistics cost and dispute risk"),
)

SQL_RESULTS_MD = REPORTS_DIR / "sql_results.md"
DATA_QUALITY_MD = REPORTS_DIR / "data_quality.md"
DATA_QUALITY_JSON = REPORTS_DIR / "data_quality.json"

PROCESSED_FILES = {
    "clean_orders": PROCESSED_DIR / "clean_orders.csv",
    "clean_payments": PROCESSED_DIR / "clean_payments.csv",
    "clean_order_items": PROCESSED_DIR / "clean_order_items.csv",
    "monthly_financials": PROCESSED_DIR / "monthly_financials.csv",
    "payment_method_financials": PROCESSED_DIR / "payment_method_financials.csv",
    "seller_concentration": PROCESSED_DIR / "seller_concentration.csv",
    "reconciliation_breaks": PROCESSED_DIR / "reconciliation_breaks.csv",
    "kpi_summary": PROCESSED_DIR / "kpi_summary.csv",
}

# ---------------------------------------------------------------------------
# Reporting window
# ---------------------------------------------------------------------------
# The dataset opens and closes with partial months (4 orders in 2016-09,
# 4 in 2018-10). Trend, growth and year-on-year analysis therefore run on a
# clean 20-month window; the full window is used for lifetime totals.
CLEAN_WINDOW_START = "2017-01-01"
CLEAN_WINDOW_END = "2018-08-01"
CLEAN_WINDOW_LABEL = "Jan 2017 - Aug 2018"

# ---------------------------------------------------------------------------
# Portfolio / presentation
# ---------------------------------------------------------------------------
ANALYST = "Rafael Silva"
PROJECT_TITLE = "Olist Marketplace - Financial Operations & Revenue Analytics"
PROJECT_SUBTITLE = (
    "Reconciling cash collected against revenue earned, and quantifying "
    "refund exposure, payment cost-to-serve and credit risk"
)
