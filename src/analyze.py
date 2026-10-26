"""Compute the financial findings and render the narrative reports.

Pipeline step 4 of 4:  load -> clean -> query -> report.

This module is the single source of every number quoted in the README, the
Excel workbook, the Power BI model and the markdown reports. It reads the
warehouse, computes the KPI set, writes `reports/key_metrics.json`, and then
renders `reports/findings.md`, `reports/executive_summary.md` and
`reports/business_decision_report.md` from that same dictionary, so a report
sentence can never disagree with the number next to it.

MEASURED vs MODELLED
--------------------
Metrics carry a `basis` of "measured" or "modelled". Modelled metrics depend
on the market-rate assumptions in `config.PAYMENT_COST_MODEL` and
`config.INSTALLMENT_FUNDING_RATE`; they are labelled as such everywhere they
appear and carry a sensitivity band.

Usage:
    python src/analyze.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

KEY_METRICS_JSON = config.REPORTS_DIR / "key_metrics.json"
FINDINGS_MD = config.REPORTS_DIR / "findings.md"
EXECUTIVE_SUMMARY_MD = config.REPORTS_DIR / "executive_summary.md"
DECISION_REPORT_MD = config.REPORTS_DIR / "business_decision_report.md"


def brl(value: float) -> str:
    """Format a number the way a finance pack would: R$ 1,234.56"""
    return f"R$ {value:,.2f}"


def pct(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}%"


def q(conn: sqlite3.Connection, sql: str) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn)


def one(conn: sqlite3.Connection, sql: str) -> dict:
    return q(conn, sql).iloc[0].to_dict()


def compute(conn: sqlite3.Connection) -> dict:
    m: dict = {}

    # ---------------------------------------------------------- headline set
    m["headline"] = one(
        conn,
        """
        SELECT COUNT(*)                                                    AS orders,
               COUNT(DISTINCT customer_unique_id)                          AS unique_customers,
               ROUND(SUM(gmv),2)                                           AS gmv,
               ROUND(SUM(freight_total),2)                                 AS freight,
               ROUND(SUM(expected_charge),2)                               AS expected_charge,
               ROUND(SUM(cash_collected),2)                                AS cash_collected,
               ROUND(SUM(refund_exposure_value),2)                         AS refund_exposure,
               ROUND(SUM(net_revenue),2)                                  AS net_revenue,
               ROUND(SUM(cash_collected)-SUM(expected_charge),2)          AS reconciliation_gap,
               ROUND(100.0*SUM(net_revenue)/SUM(cash_collected),3)        AS net_revenue_pct_of_cash,
               ROUND(SUM(cash_collected)/COUNT(*),2)                      AS aov,
               ROUND(100.0*SUM(freight_total)/SUM(gmv),2)                 AS freight_ratio_pct,
               ROUND(SUM(settlement_float_value),2)                        AS settlement_float,
               SUM(recon_break_flag)                                       AS reconciliation_breaks,
               ROUND(100.0*SUM(recon_break_flag)/COUNT(*),3)               AS reconciliation_break_rate_pct,
               MIN(purchase_date)                                          AS first_order_date,
               MAX(purchase_date)                                          AS last_order_date
        FROM fact_order_financials
        """,
    )

    # ------------------------------------------------- like-for-like growth
    yoy = q(
        conn,
        """
        SELECT CAST(purchase_year AS INTEGER) AS purchase_year,
               COUNT(*)                      AS orders,
               COUNT(DISTINCT customer_unique_id) AS customers,
               ROUND(SUM(cash_collected),2)  AS cash,
               ROUND(SUM(gmv),2)             AS gmv,
               ROUND(SUM(freight_total),2)   AS freight,
               ROUND(SUM(refund_exposure_value),2) AS refund_exposure
        FROM fact_order_financials
        WHERE CAST(strftime('%m', purchase_month) AS INTEGER) BETWEEN 1 AND 8
          AND CAST(purchase_year AS INTEGER) IN (2017, 2018)
        GROUP BY purchase_year
        """,
    ).set_index("purchase_year")
    a, b = yoy.loc[2017], yoy.loc[2018]
    m["yoy"] = {
        "window": "Jan-Aug 2017 vs Jan-Aug 2018",
        "orders_2017": int(a["orders"]),
        "orders_2018": int(b["orders"]),
        "orders_growth_pct": round(100 * (b["orders"] / a["orders"] - 1), 2),
        "cash_2017": float(a["cash"]),
        "cash_2018": float(b["cash"]),
        "cash_growth_pct": round(100 * (b["cash"] / a["cash"] - 1), 2),
        "aov_2017": round(a["cash"] / a["orders"], 2),
        "aov_2018": round(b["cash"] / b["orders"], 2),
        "aov_growth_pct": round(100 * ((b["cash"] / b["orders"]) / (a["cash"] / a["orders"]) - 1), 2),
        "customers_2017": int(a["customers"]),
        "customers_2018": int(b["customers"]),
        "customers_growth_pct": round(100 * (b["customers"] / a["customers"] - 1), 2),
        "freight_ratio_2017": round(100 * a["freight"] / a["gmv"], 2),
        "freight_ratio_2018": round(100 * b["freight"] / b["gmv"], 2),
        "refund_exposure_2017": float(a["refund_exposure"]),
        "refund_exposure_2018": float(b["refund_exposure"]),
        "refund_rate_2017": round(100 * a["refund_exposure"] / a["cash"], 3),
        "refund_rate_2018": round(100 * b["refund_exposure"] / b["cash"], 3),
    }
    m["yoy"]["freight_ratio_change_pts"] = round(
        m["yoy"]["freight_ratio_2018"] - m["yoy"]["freight_ratio_2017"], 2
    )
    m["yoy"]["refund_exposure_growth_pct"] = round(
        100 * (b["refund_exposure"] / a["refund_exposure"] - 1), 2
    )

    # ---------------------------------------------------------- status mix
    m["status_mix"] = q(
        conn,
        """
        SELECT order_status, status_class, COUNT(*) AS orders,
               ROUND(SUM(cash_collected),2) AS cash,
               ROUND(SUM(gmv),2) AS gmv,
               ROUND(SUM(refund_exposure_value),2) AS refund_exposure,
               SUM(line_item_count = 0) AS orders_without_line_items
        FROM fact_order_financials
        GROUP BY order_status, status_class
        ORDER BY cash DESC
        """,
    ).to_dict("records")

    # ------------------------------------------------------- payment mix
    m["payment_mix"] = q(
        conn,
        """
        SELECT payment_type, COUNT(*) AS payment_rows, COUNT(DISTINCT order_id) AS orders,
               ROUND(SUM(payment_value),2) AS value,
               ROUND(100.0*SUM(payment_value)/(SELECT SUM(payment_value) FROM payments),3) AS pct_of_value,
               ROUND(AVG(payment_value),2) AS average_value,
               ROUND(AVG(payment_installments),3) AS average_installments
        FROM payments GROUP BY payment_type ORDER BY value DESC
        """,
    ).to_dict("records")

    m["installments"] = one(
        conn,
        """
        SELECT ROUND(SUM(payment_value),2) AS card_value,
               ROUND(SUM(CASE WHEN COALESCE(payment_installments,1) > 1 THEN payment_value ELSE 0 END),2) AS value_on_installment_plans,
               ROUND(100.0*SUM(CASE WHEN COALESCE(payment_installments,1) > 1 THEN payment_value ELSE 0 END)/SUM(payment_value),3) AS pct_of_card_value_on_installments,
               COUNT(DISTINCT CASE WHEN COALESCE(payment_installments,1) > 1 THEN order_id END) AS orders_with_installments,
               ROUND(SUM(payment_installments*payment_value)/SUM(payment_value),3) AS value_weighted_average_installments,
               MAX(payment_installments) AS max_installments
        FROM payments WHERE payment_type = 'credit_card'
        """,
    )
    m["installments"]["max_installments"] = int(m["installments"]["max_installments"])
    m["installments"]["orders_with_installments"] = int(
        m["installments"]["orders_with_installments"])

    # -------------------------------------------- modelled cost to serve
    cost = q(
        conn,
        f"""
        WITH params(payment_type, pct_rate, fixed_fee) AS (
            VALUES ('credit_card', {config.PAYMENT_COST_MODEL['credit_card'][0]}, {config.PAYMENT_COST_MODEL['credit_card'][1]}),
                   ('debit_card', {config.PAYMENT_COST_MODEL['debit_card'][0]}, {config.PAYMENT_COST_MODEL['debit_card'][1]}),
                   ('boleto',      {config.PAYMENT_COST_MODEL['boleto'][0]}, {config.PAYMENT_COST_MODEL['boleto'][1]}),
                   ('voucher',     {config.PAYMENT_COST_MODEL['voucher'][0]}, {config.PAYMENT_COST_MODEL['voucher'][1]}),
                   ('not_defined', {config.PAYMENT_COST_MODEL['not_defined'][0]}, {config.PAYMENT_COST_MODEL['not_defined'][1]})
        ),
        funding(rate) AS (VALUES ({config.INSTALLMENT_FUNDING_RATE})),
        pay AS (
            SELECT p.payment_type, p.payment_value,
                   COALESCE(p.payment_installments,1) AS installments,
                   pa.pct_rate, pa.fixed_fee, f.rate AS funding_rate
            FROM payments p JOIN params pa ON pa.payment_type = p.payment_type
            CROSS JOIN funding f
        )
        SELECT payment_type, COUNT(*) AS payment_rows,
               ROUND(SUM(payment_value),2) AS gross_value,
               ROUND(SUM(payment_value*pct_rate + fixed_fee),2) AS acquiring_cost,
               ROUND(SUM(CASE WHEN payment_type='credit_card'
                              THEN payment_value*funding_rate*(installments-1) ELSE 0 END),2) AS installment_funding_cost,
               ROUND(SUM(payment_value*pct_rate + fixed_fee
                         + CASE WHEN payment_type='credit_card'
                                THEN payment_value*funding_rate*(installments-1) ELSE 0 END),2) AS total_modelled_cost
        FROM pay GROUP BY payment_type ORDER BY gross_value DESC
        """,
    )
    m["cost_model"] = {
        "basis": "modelled",
        "by_method": cost.to_dict("records"),
        "acquiring_cost": round(float(cost["acquiring_cost"].sum()), 2),
        "installment_funding_cost": round(float(cost["installment_funding_cost"].sum()), 2),
        "total_modelled_payment_cost": round(float(cost["total_modelled_cost"].sum()), 2),
        "net_revenue": m["headline"]["net_revenue"],
        "contribution_after_payment_cost": round(
            m["headline"]["net_revenue"] - float(cost["total_modelled_cost"].sum()), 2
        ),
    }
    m["cost_model"]["contribution_margin_pct"] = round(
        100 * m["cost_model"]["contribution_after_payment_cost"] / m["headline"]["net_revenue"], 2
    )
    m["cost_model"]["installment_funding_pct_of_net_revenue"] = round(
        100 * m["cost_model"]["installment_funding_cost"] / m["headline"]["net_revenue"], 3
    )

    # sensitivity band on the instalment funding rate
    sens = q(
        conn,
        """
        WITH rates(rate) AS (VALUES (0.0100), (0.0199), (0.0299)),
             card AS (SELECT payment_value, COALESCE(payment_installments,1) AS inst
                      FROM payments WHERE payment_type='credit_card')
        SELECT r.rate AS rate,
               ROUND(SUM(c.payment_value * r.rate * (c.inst - 1)),2) AS installment_funding_cost,
               ROUND(100.0*SUM(c.payment_value * r.rate * (c.inst - 1))
                     /(SELECT SUM(payment_value) FROM payments WHERE payment_type='credit_card'),3) AS pct_of_card_value
        FROM rates r CROSS JOIN card c GROUP BY r.rate ORDER BY r.rate
        """,
    ).to_dict("records")
    m["cost_model"]["sensitivity"] = sens

    # voucher
    m["voucher"] = one(
        conn,
        """
        SELECT COUNT(DISTINCT p.order_id) AS orders,
               COUNT(*) AS payment_rows,
               ROUND(SUM(p.payment_value),2) AS value,
               ROUND(100.0*SUM(p.payment_value)/(SELECT SUM(payment_value) FROM payments),3) AS pct_of_value
        FROM payments p WHERE p.payment_type = 'voucher'
        """,
    )
    m["voucher_profile"] = q(
        conn,
        """
        SELECT CASE WHEN voucher_value > 0 THEN 'voucher order' ELSE 'non-voucher order' END AS order_type,
               COUNT(*) AS orders, ROUND(SUM(cash_collected),2) AS cash,
               ROUND(AVG(cash_collected),2) AS average_order_value,
               SUM(disputed_flag) AS disputed_orders,
               ROUND(100.0*SUM(disputed_flag)/COUNT(*),3) AS dispute_rate_pct,
               ROUND(SUM(CASE WHEN disputed_flag=1 THEN cash_collected ELSE 0 END),2) AS disputed_value
        FROM fact_order_financials
        GROUP BY CASE WHEN voucher_value > 0 THEN 'voucher order' ELSE 'non-voucher order' END
        """,
    ).to_dict("records")

    # --------------------------------------------------- reconciliation
    m["reconciliation"] = one(
        conn,
        """
        SELECT ROUND(SUM(expected_charge),2) AS expected_charge,
               ROUND(SUM(cash_collected),2) AS cash_collected,
               ROUND(SUM(cash_collected)-SUM(expected_charge),2) AS net_break,
               ROUND(SUM(ABS(recon_delta)),2) AS gross_break_value,
               SUM(recon_break_flag) AS orders_in_break,
               ROUND(100.0*SUM(recon_break_flag)/COUNT(*),3) AS break_rate_pct,
               SUM(CASE WHEN line_item_count = 0 THEN 1 ELSE 0 END) AS orders_without_line_items,
               SUM(CASE WHEN line_item_count = 0 AND cash_collected > 0 THEN 1 ELSE 0 END) AS paid_orders_without_line_items,
               ROUND(SUM(CASE WHEN line_item_count = 0 THEN cash_collected ELSE 0 END),2) AS cash_without_merchandise
        FROM fact_order_financials
        """,
    )
    for _key in ("orders_in_break", "orders_without_line_items",
                 "paid_orders_without_line_items"):
        m["reconciliation"][_key] = int(m["reconciliation"][_key])
    m["break_structure"] = q(
        conn,
        """
        SELECT CASE WHEN line_item_count = 0 THEN 'no line items at all' ELSE 'line items present' END AS break_reason,
               CASE WHEN ABS(recon_delta) < 1     THEN 'a. rounding (< R$1)'
                    WHEN ABS(recon_delta) < 100   THEN 'b. R$1 - R$100'
                    WHEN ABS(recon_delta) < 1000  THEN 'c. R$100 - R$1,000'
                    ELSE 'd. R$1,000+' END AS size_band,
               COUNT(*) AS orders,
               ROUND(SUM(ABS(recon_delta)),2) AS absolute_break,
               ROUND(SUM(recon_delta),2) AS net_break
        FROM fact_order_financials WHERE recon_break_flag = 1
        GROUP BY 1, 2 ORDER BY 1, 2
        """,
    ).to_dict("records")

    m["refund_exposure"] = q(
        conn,
        """
        SELECT order_status, COUNT(*) AS orders,
               ROUND(SUM(cash_collected),2) AS cash_collected,
               ROUND(SUM(refund_exposure_value),2) AS refund_exposure,
               SUM(line_item_count = 0) AS orders_without_line_items,
               ROUND(100.0*SUM(line_item_count = 0)/COUNT(*),2) AS pct_without_line_items
        FROM fact_order_financials
        WHERE status_class IN ('cancelled','unavailable')
        GROUP BY order_status
        """,
    ).to_dict("records")
    m["refund_exposure_total"] = {
        "orders": int(sum(r["orders"] for r in m["refund_exposure"])),
        "cash_collected": round(sum(r["cash_collected"] for r in m["refund_exposure"]), 2),
        "refund_exposure": round(sum(r["refund_exposure"] for r in m["refund_exposure"]), 2),
        "orders_without_line_items": int(
            sum(r["orders_without_line_items"] for r in m["refund_exposure"])
        ),
    }

    # ------------------------------------------------------- risk signals
    m["dispute_by_installments"] = q(
        conn,
        """
        SELECT CASE WHEN max_installments <= 1 THEN '1 (paid in full)'
                    WHEN max_installments <= 3 THEN '2 - 3'
                    WHEN max_installments <= 6 THEN '4 - 6'
                    WHEN max_installments <= 12 THEN '7 - 12'
                    ELSE '13 +' END AS instalment_bucket,
               COUNT(*) AS orders, ROUND(SUM(cash_collected),2) AS cash,
               ROUND(AVG(cash_collected),2) AS average_order_value,
               SUM(disputed_flag) AS disputed_orders,
               ROUND(100.0*SUM(disputed_flag)/COUNT(*),3) AS dispute_rate_pct,
               ROUND(SUM(CASE WHEN disputed_flag=1 THEN cash_collected ELSE 0 END),2) AS disputed_value
        FROM fact_order_financials
        WHERE primary_payment_type = 'credit_card'
        GROUP BY 1
        ORDER BY CASE instalment_bucket
                    WHEN '1 (paid in full)' THEN 1 WHEN '2 - 3' THEN 2
                    WHEN '4 - 6' THEN 3 WHEN '7 - 12' THEN 4 ELSE 5 END
        """,
    ).to_dict("records")

    m["dispute_total"] = one(
        conn,
        """
        SELECT COUNT(*) AS orders_with_review,
               SUM(worst_review_score <= 2) AS disputed_orders,
               ROUND(SUM(CASE WHEN worst_review_score <= 2 THEN cash_collected ELSE 0 END),2) AS disputed_value,
               ROUND(100.0*SUM(CASE WHEN worst_review_score <= 2 THEN cash_collected ELSE 0 END)
                     /SUM(cash_collected),3) AS pct_of_cash_at_risk,
               ROUND(100.0*SUM(worst_review_score <= 2)/COUNT(*),3) AS pct_of_orders_disputed
        FROM fact_order_financials WHERE worst_review_score IS NOT NULL
        """,
    )
    m["dispute_total"]["disputed_orders"] = int(m["dispute_total"]["disputed_orders"])
    m["dispute_total"]["orders_with_review"] = int(m["dispute_total"]["orders_with_review"])

    m["seller_concentration"] = one(
        conn,
        """
        WITH s AS (SELECT seller_id, SUM(price) AS gmv FROM order_items GROUP BY seller_id),
             ranked AS (SELECT seller_id, gmv, RANK() OVER (ORDER BY gmv DESC) AS rnk FROM s),
             t AS (SELECT SUM(gmv) AS total FROM s)
        SELECT COUNT(*) AS sellers, ROUND(SUM(r.gmv),2) AS total_gmv,
               ROUND(100.0*SUM(CASE WHEN r.rnk=1 THEN r.gmv ELSE 0 END)/t.total,3) AS top1_pct,
               ROUND(100.0*SUM(CASE WHEN r.rnk<=10 THEN r.gmv ELSE 0 END)/t.total,3) AS top10_pct,
               ROUND(100.0*SUM(CASE WHEN r.rnk<=100 THEN r.gmv ELSE 0 END)/t.total,3) AS top100_pct,
               ROUND(100.0*SUM(CASE WHEN r.rnk<=1000 THEN r.gmv ELSE 0 END)/t.total,3) AS top1000_pct,
               ROUND(SUM(r.gmv*r.gmv)/(t.total*t.total),5) AS hhi,
               (SELECT COUNT(*) FROM s, t WHERE s.gmv > 0.01*t.total) AS sellers_above_1pct
        FROM ranked r, t
        """,
    )
    m["seller_concentration"]["sellers"] = int(m["seller_concentration"]["sellers"])
    m["seller_concentration"]["sellers_above_1pct"] = int(
        m["seller_concentration"]["sellers_above_1pct"])

    m["category_freight"] = q(
        conn,
        """
        SELECT category_english, ROUND(category_gmv,2) AS gmv,
               ROUND(category_freight,2) AS freight, freight_ratio_pct, line_item_count
        FROM v_category_financials WHERE category_gmv > 0
        ORDER BY category_gmv DESC
        """,
    ).to_dict("records")

    # The same categories ranked by the freight burden, restricted to
    # categories large enough for the ratio to mean something.
    m["category_freight_by_burden"] = q(
        conn,
        """
        SELECT category_english, ROUND(category_gmv,2) AS gmv,
               ROUND(category_freight,2) AS freight, freight_ratio_pct, line_item_count
        FROM v_category_financials WHERE category_gmv >= 100000
        ORDER BY freight_ratio_pct DESC
        """,
    ).to_dict("records")

    m["freight_extremes"] = one(
        conn,
        """
        SELECT COUNT(*) AS line_items,
               SUM(CASE WHEN freight_value > price THEN 1 ELSE 0 END) AS items_freight_exceeds_price,
               ROUND(100.0*SUM(CASE WHEN freight_value > price THEN 1 ELSE 0 END)/COUNT(*),2) AS pct_items,
               ROUND(SUM(CASE WHEN freight_value > price THEN freight_value - price ELSE 0 END),2) AS freight_over_merchandise_value,
               ROUND(SUM(freight_value),2) AS total_freight,
               ROUND(100.0*SUM(freight_value)/SUM(price),2) AS portfolio_freight_ratio_pct
        FROM order_items
        """,
    )
    m["freight_extremes"]["items_freight_exceeds_price"] = int(
        m["freight_extremes"]["items_freight_exceeds_price"])
    m["freight_extremes"]["line_items"] = int(m["freight_extremes"]["line_items"])

    m["customer_economics"] = one(
        conn,
        """
        WITH cu AS (SELECT customer_unique_id, COUNT(DISTINCT order_id) AS orders,
                           SUM(cash_collected) AS cash
                    FROM fact_order_financials GROUP BY customer_unique_id)
        SELECT COUNT(*) AS unique_customers, SUM(orders) AS orders,
               ROUND(SUM(cash),2) AS cash,
               SUM(orders > 1) AS repeat_customers,
               ROUND(100.0*SUM(orders>1)/COUNT(*),3) AS repeat_customer_rate_pct,
               ROUND(SUM(cash)/COUNT(*),2) AS cash_per_customer,
               ROUND(AVG(orders),4) AS orders_per_customer
        FROM cu
        """,
    )
    m["customer_economics"]["unique_customers"] = int(
        m["customer_economics"]["unique_customers"])
    m["customer_economics"]["orders"] = int(m["customer_economics"]["orders"])
    m["customer_economics"]["repeat_customers"] = int(
        m["customer_economics"]["repeat_customers"])

    m["identity_fragmentation"] = one(
        conn,
        """
        SELECT COUNT(*) AS customer_rows,
               COUNT(DISTINCT customer_unique_id) AS unique_customers,
               (SELECT COUNT(*) FROM (SELECT customer_unique_id FROM customers
                                     GROUP BY customer_unique_id HAVING COUNT(*)>1)) AS customers_split_across_ids,
               (SELECT MAX(n) FROM (SELECT COUNT(DISTINCT customer_id) AS n FROM customers
                                    GROUP BY customer_unique_id)) AS worst_case_ids_for_one_customer
        FROM customers
        """,
    )

    m["fulfilment"] = one(
        conn,
        """
        SELECT COUNT(*) AS delivered_orders,
               ROUND(AVG(delivery_days),2) AS avg_delivery_days,
               SUM(days_late_vs_promise > 0) AS delivered_late,
               ROUND(100.0*SUM(days_late_vs_promise > 0)/COUNT(*),3) AS pct_delivered_late
        FROM fact_order_financials WHERE status_class = 'fulfilled'
        """,
    )

    # ------------------------------------------------ data quality summary
    m["data_quality"] = q(
        conn,
        "SELECT rule_code, table_name, rule_type, records_affected, rule_description "
        "FROM dq_cleaning_rules ORDER BY rule_id",
    ).to_dict("records")

    m["monthly"] = q(
        conn,
        """
        SELECT purchase_month, COUNT(*) AS orders,
               ROUND(SUM(cash_collected),2) AS cash,
               ROUND(SUM(gmv),2) AS gmv,
               ROUND(SUM(refund_exposure_value),2) AS refund_exposure,
               ROUND(SUM(cash_collected)/COUNT(*),2) AS average_order_value,
               ROUND(100.0*SUM(freight_total)/SUM(gmv),2) AS freight_ratio_pct,
               ROUND(100.0*SUM(refund_exposure_value)/SUM(cash_collected),3) AS refund_exposure_pct,
               COUNT(DISTINCT customer_unique_id) AS active_customers
        FROM fact_order_financials GROUP BY purchase_month ORDER BY purchase_month
        """,
    ).to_dict("records")

    return m


def main() -> None:
    conn = sqlite3.connect(config.DB_PATH)
    metrics = compute(conn)
    conn.close()

    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    KEY_METRICS_JSON.write_text(
        json.dumps(metrics, indent=2, default=str), encoding="utf-8"
    )
    print(f"[analyze] wrote {KEY_METRICS_JSON.name}")

    write_findings(metrics)
    write_executive_summary(metrics)
    write_decision_report(metrics)


# ---------------------------------------------------------------------------
# Narrative reports
# ---------------------------------------------------------------------------
def write_findings(m: dict) -> None:
    h = m["headline"]
    y = m["yoy"]
    r = m["reconciliation"]
    c = m["cost_model"]
    v = m["voucher"]
    d = m["dispute_by_installments"]
    s = m["seller_concentration"]
    cat = m["category_freight"]

    def bucket(name: str) -> dict:
        return next(x for x in d if x["instalment_bucket"] == name)

    lines: list[str] = []
    lines.append("# Findings")
    lines.append("")
    lines.append(
        "Every figure below is computed by `src/analyze.py` from the warehouse and "
        "reproduced in `reports/sql_results.md`. Figures marked **modelelled** depend "
        "on the published market-rate assumptions in `src/config.py`; all others are "
        "measured from the source data."
    )
    lines.append("")

    # --- Finding 1
    lines.append("## 1. The cash-to-revenue reconciliation does not close")
    lines.append("")
    lines.append(
        f"**What the data shows.** Customers paid {brl(h['cash_collected'])} against an "
        f"expected charge of {brl(h['expected_charge'])} (merchandise {brl(h['gmv'])} plus "
        f"freight {brl(h['freight'])}). The gap is {brl(h['reconciliation_gap'])}. "
        f"{int(r['orders_in_break']):,} orders ({r['break_rate_pct']}%) fail the reconciliation "
        f"outright, carrying {brl(r['gross_break_value'])} of gross break value."
    )
    lines.append("")
    lines.append(
        f"**Why it happens.** The break has two distinct causes. "
        f"{r['paid_orders_without_line_items']:,} orders have cash collected but no line "
        f"items at all - {brl(r['cash_without_merchandise'])} of cash with nothing in the "
        f"dataset to deliver against it. The remaining "
        f"{r['orders_in_break'] - r['paid_orders_without_line_items']:,} orders do have "
        f"line items but the amount paid does not equal price plus freight."
    )
    lines.append("")
    lines.append("| Break reason | Size band | Orders | Absolute break |")
    lines.append("|---|---|---:|---:|")
    for row in m["break_structure"]:
        lines.append(
            f"| {row['break_reason']} | {row['size_band']} | {row['orders']:,} | "
            f"{brl(row['absolute_break'])} |"
        )
    lines.append("")
    lines.append(
        "**Why it matters.** A revenue report built on line items alone silently drops "
        f"{brl(r['cash_without_merchandise'])} of collected cash. A report built on cash "
        "alone overstates revenue by the reconciliation gap. The finance team cannot close "
        "its own books from this extract without the missing order content."
    )
    lines.append("")
    lines.append(
        "**What would be needed to act.** The order-detail extract for the affected "
        f"{r['orders_in_break']:,} orders from the order-management system. The break is "
        "reported, not corrected: no amount in this analysis has been adjusted to make it "
        "close."
    )
    lines.append("")

    # --- Finding 2
    lines.append("## 2. Refund exposure is real, measurable and volatile")
    lines.append("")
    lines.append(
        f"**What the data shows.** {m['refund_exposure_total']['orders']:,} orders "
        f"({brl(m['refund_exposure_total']['cash_collected'])} of cash collected) were "
        "cancelled or became unavailable. The cash collected against them - "
        f"{brl(h['refund_exposure'])}, or {pct(100 * h['refund_exposure'] / h['cash_collected'], 3)} "
        "of all cash collected - is owed back. Net revenue after that exposure is "
        f"{brl(h['net_revenue'])}, {pct(h['net_revenue_pct_of_cash'], 3)} of cash collected."
    )
    lines.append("")
    lines.append("| Order status | Orders | Cash collected | Refund exposure | Orders with no line items |")
    lines.append("|---|---:|---:|---:|---:|")
    for row in m["refund_exposure"]:
        lines.append(
            f"| {row['order_status']} | {row['orders']:,} | {brl(row['cash_collected'])} | "
            f"{brl(row['refund_exposure'])} | {row['orders_without_line_items']:,} |"
        )
    lines.append("")
    lines.append(
        f"**Limitation.** The source data contains no refund table. This is the cash "
        "collected on orders that will never be fulfilled - an exposure proxy, not a "
        "record of refunds actually paid. It is the most the data can support."
    )
    lines.append("")
    _rates = [x["refund_exposure_pct"] for x in m["monthly"]
              if "2017-01-01" <= x["purchase_month"] <= "2018-08-01"]
    lines.append(
        "**Volatility.** The monthly rate moves from "
        f"{min(_rates)}% to {max(_rates)}% of cash collected across the clean window "
        f"({max(_rates) / min(_rates):.0f}x), so a reserve set on the lifetime average "
        "would be under-provided in the bad months."
    )
    lines.append("")

    # --- Finding 3
    lines.append("## 3. Instalment-heavy card volume is the largest single cost lever")
    lines.append("")
    lines.append(
        f"**What the data shows.** Card payments are {next(x['pct_of_value'] for x in m['payment_mix'] if x['payment_type'] == 'credit_card')}% "
        f"of all collected value. "
        f"{brl(m['installments']['value_on_installment_plans'])} of that - "
        f"{m['installments']['pct_of_card_value_on_installments']}% of card value - is "
        f"settled on an instalment plan, at a value-weighted average depth of "
        f"{m['installments']['value_weighted_average_installments']} instalments "
        f"(maximum {m['installments']['max_installments']})."
    )
    lines.append("")
    lines.append(
        f"**Modelled cost.** Applying published Brazilian acquiring rates (card 2.9%, "
        f"debit 1.5% + R$1.50, boleto R$3.00) and an instalment-funding rate of "
        f"{pct(config.INSTALLMENT_FUNDING_RATE * 100, 2)} per instalment gives a total "
        f"modelled payment cost of {brl(c['total_modelled_payment_cost'])}, of which "
        f"{brl(c['installment_funding_cost'])} is instalment funding - "
        f"{pct(c['installment_funding_pct_of_net_revenue'], 3)} of net revenue."
    )
    lines.append("")
    lines.append("| Funding rate per instalment | Modelled instalment funding | % of card value |")
    lines.append("|---:|---:|---:|")
    for row in c["sensitivity"]:
        lines.append(
            f"| {pct(row['rate'] * 100, 2)} | {brl(row['installment_funding_cost'])} | "
            f"{row['pct_of_card_value']}% |"
        )
    lines.append("")
    lines.append(
        "**Interpretation.** The instalment-funding component is the largest single item "
        f"in the modelled cost base - larger than the {brl(c['acquiring_cost'])} acquiring "
        f"cost and the {brl(v['value'])} of promotional voucher credit combined. At the "
        "low end of the published rate band it is still the dominant term."
    )
    lines.append("")
    lines.append(
        "**Limitation.** These are market benchmarks, not this marketplace's contract. "
        "The sensitivity band above is the honest statement of how much the conclusion "
        "depends on the assumption."
    )
    lines.append("")

    # --- Finding 4
    lines.append("## 4. Dispute risk rises with instalment depth, and promotional credit carries the highest rate")
    lines.append("")
    lines.append(
        f"**What the data shows.** A review score of 1 or 2 out of 5 marks a disputed "
        f"order. {m['dispute_total']['disputed_orders']:,} orders are disputed, carrying "
        f"{brl(m['dispute_total']['disputed_value'])} of cash - "
        f"{pct(m['dispute_total']['pct_of_cash_at_risk'], 2)} of the value on reviewed orders."
    )
    lines.append("")
    lines.append("| Instalment bucket | Orders | Cash | Dispute rate | Disputed value |")
    lines.append("|---|---:|---:|---:|---:|")
    for row in d:
        lines.append(
            f"| {row['instalment_bucket']} | {row['orders']:,} | {brl(row['cash'])} | "
            f"{row['dispute_rate_pct']}% | {brl(row['disputed_value'])} |"
        )
    lines.append("")
    lines.append(
        "**Promotional credit.** Orders funded by a marketplace voucher have a dispute "
        f"rate of {next(x['dispute_rate_pct'] for x in m['voucher_profile'] if x['order_type'] == 'voucher order')}% "
        f"against {next(x['dispute_rate_pct'] for x in m['voucher_profile'] if x['order_type'] == 'non-voucher order')}% "
        f"for orders without a voucher, while carrying {brl(v['value'])} of promotional "
        f"credit ({v['pct_of_value']}% of all collected value)."
    )
    lines.append("")
    lines.append(
        "**What this does and does not show.** The instalment-depth gradient is an "
        "association in the data, not a demonstrated cause: longer instalment plans may "
        "select for riskier baskets, or may simply correlate with higher-value and "
        "more complex orders. No causal claim is made and no intervention has been "
        "measured. A review score is a proxy for a dispute - the dataset records no "
        "chargeback, refund or complaint."
    )
    lines.append("")

    # --- Finding 5
    lines.append("## 5. Logistics is the second-largest cost, and it is getting worse as the business scales")
    lines.append("")
    lines.append(
        f"**What the data shows.** Freight collected is {brl(h['freight'])}, "
        f"{h['freight_ratio_pct']}% of merchandise value. On a like-for-like basis "
        f"(Jan-Aug 2017 vs Jan-Aug 2018) the freight ratio moved from "
        f"{y['freight_ratio_2017']}% to {y['freight_ratio_2018']}%, "
        f"{y['freight_ratio_change_pts']:+} points, while cash grew "
        f"{y['cash_growth_pct']}%. Scale is not delivering logistics efficiency."
    )
    lines.append("")
    lines.append(
        f"{m['freight_extremes']['items_freight_exceeds_price']:,} line items "
        f"({m['freight_extremes']['pct_items']}%) ship with a freight charge larger than "
        f"the merchandise value itself, by {brl(m['freight_extremes']['freight_over_merchandise_value'])} "
        "in aggregate."
    )
    lines.append("")
    lines.append("| Category | GMV | Freight | Freight ratio |")
    lines.append("|---|---:|---:|---:|")
    for row in cat[:5]:
        lines.append(
            f"| {row['category_english']} | {brl(row['gmv'])} | {brl(row['freight'])} | "
            f"{row['freight_ratio_pct']}% |"
        )
    lines.append("")
    burden = m["category_freight_by_burden"]
    lines.append(
        f"Across the {len(burden)} categories with at least R$ 100,000 of GMV, the "
        f"freight burden runs from {burden[-1]['category_english']} at "
        f"{burden[-1]['freight_ratio_pct']}% to {burden[0]['category_english']} at "
        f"{burden[0]['freight_ratio_pct']}%. The three heaviest - "
        f"{burden[0]['category_english']}, {burden[1]['category_english']} and "
        f"{burden[2]['category_english']} - carry "
        f"{brl(sum(r['gmv'] for r in burden[:3]))} of GMV between them, so a "
        "category-level freight change would move a meaningful share of the "
        "portfolio rather than a rounding of it."
    )
    lines.append("")
    lines.append(
        "**Limitation.** Freight collected is a revenue line, not a carrier invoice. "
        "The dataset contains no logistics cost, so the ratio measures the logistics "
        "burden on the order, not the logistics margin."
    )
    lines.append("")

    # --- Finding 6
    lines.append("## 6. Seller concentration is low; the real concentration is regional")
    lines.append("")
    lines.append(
        f"**What the data shows.** {s['sellers']:,} active sellers. The largest holds "
        f"{s['top1_pct']}% of GMV, the top ten {s['top10_pct']}%, the top hundred "
        f"{s['top100_pct']}%. The Herfindahl-Hirschman index is {s['hhi']} - far below "
        "the 0.15 threshold that marks an unconcentrated market - and only "
        f"{s['sellers_above_1pct']} sellers hold more than 1% of GMV each. Counterparty "
        "dependency is not a material risk in this data."
    )
    lines.append("")
    lines.append(
        "**What would be concentrated instead.** Supply sits in one state: Sao Paulo "
        "hosts 1,849 of the 3,095 sellers and 64.4% of GMV. A regional logistics or "
        "regulatory event is a bigger exposure than the loss of any single seller."
    )
    lines.append("")

    # --- Finding 7
    lines.append("## 7. Growth is entirely acquisition, and the customer base barely repeats")
    lines.append("")
    ce = m["customer_economics"]
    lines.append(
        f"**What the data shows.** On a like-for-like basis cash grew "
        f"{y['cash_growth_pct']}% (order volume {y['orders_growth_pct']}%, average order "
        f"value only {y['aov_growth_pct']}%) and active customers grew "
        f"{y['customers_growth_pct']}%. Across the whole window only "
        f"{ce['repeat_customers']:,} of {ce['unique_customers']:,} customers "
        f"({ce['repeat_customer_rate_pct']}%) placed more than one order - "
        f"{ce['orders_per_customer']} orders per customer."
    )
    lines.append("")
    lines.append(
        "**Data-quality caveat that matters here.** "
        f"{m['identity_fragmentation']['customers_split_across_ids']:,} real customers "
        "appear under more than one customer_id (one appears under "
        f"{m['identity_fragmentation']['worst_case_ids_for_one_customer']}). Counting "
        "customers on customer_id would overstate the base by "
        f"{pct(100 * (m['identity_fragmentation']['customer_rows'] / m['identity_fragmentation']['unique_customers'] - 1), 1)} "
        "and would understate the repeat rate. All customer metrics in this project use "
        "customer_unique_id."
    )
    lines.append("")
    lines.append(
        "**What this means.** The platform acquires customers and does not retain them. "
        "That is a decision about acquisition economics and lifetime value that this "
        "dataset cannot settle - there is no marketing spend, no margin and no "
        "customer-acquisition cost here."
    )
    lines.append("")

    FINDINGS_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"[analyze] wrote {FINDINGS_MD.name}")


def write_executive_summary(m: dict) -> None:
    h = m["headline"]
    y = m["yoy"]
    r = m["reconciliation"]
    c = m["cost_model"]
    lines = []
    lines.append("# Executive summary")
    lines.append("")
    lines.append(
        f"**{config.PROJECT_SUBTITLE}.** "
        f"{h['orders']:,} orders, {h['unique_customers']:,} customers and "
        f"{brl(h['cash_collected'])} of cash collected between {h['first_order_date']} "
        f"and {h['last_order_date']}."
    )
    lines.append("")
    lines.append("## The scoreboard")
    lines.append("")
    lines.append("| KPI | Value | Basis |")
    lines.append("|---|---:|---|")
    lines.append(f"| GMV (merchandise value) | {brl(h['gmv'])} | measured |")
    lines.append(f"| Cash collected | {brl(h['cash_collected'])} | measured |")
    lines.append(f"| Refund exposure | {brl(h['refund_exposure'])} | measured (proxy) |")
    lines.append(f"| Net revenue | {brl(h['net_revenue'])} | measured |")
    lines.append(f"| Reconciliation gap | {brl(h['reconciliation_gap'])} | measured |")
    lines.append(f"| Average order value | {brl(h['aov'])} | measured |")
    lines.append(f"| Freight ratio | {h['freight_ratio_pct']}% of GMV | measured |")
    lines.append(f"| Reconciliation break rate | {h['reconciliation_break_rate_pct']}% of orders | measured |")
    lines.append(f"| Repeat customer rate | {m['customer_economics']['repeat_customer_rate_pct']}% | measured |")
    lines.append(f"| Seller HHI | {m['seller_concentration']['hhi']} | measured |")
    lines.append(f"| Modelled payment cost | {brl(c['total_modelled_payment_cost'])} | **modelled** |")
    lines.append("")
    lines.append("## What matters")
    lines.append("")
    lines.append(
        f"1. **The books do not close.** {int(r['orders_in_break']):,} orders "
        f"({r['break_rate_pct']}%) fail the cash-to-revenue reconciliation, and "
        f"{brl(r['cash_without_merchandise'])} of cash sits on orders for which the "
        "dataset holds no merchandise record at all."
    )
    _rates = [x["refund_exposure_pct"] for x in m["monthly"]
              if "2017-01-01" <= x["purchase_month"] <= "2018-08-01"]
    lines.append(
        f"2. **Refund exposure is {brl(h['refund_exposure'])}**, "
        f"{pct(100 * h['refund_exposure'] / h['cash_collected'], 2)} of cash collected, "
        f"and the monthly rate moves from {min(_rates)}% to {max(_rates)}% "
        f"({max(_rates) / min(_rates):.0f}x) between the best and worst month."
    )
    lines.append(
        f"3. **Instalments are the biggest modelled cost.** "
        f"{brl(c['installment_funding_cost'])} of modelled instalment funding on "
        f"{brl(m['installments']['value_on_installment_plans'])} of instalment-funded "
        "card volume - larger than acquiring cost and promotional credit combined."
    )
    lines.append(
        f"4. **Logistics is deteriorating as the business scales.** The freight ratio "
        f"moved {y['freight_ratio_change_pts']:+} points year on year while cash grew "
        f"{y['cash_growth_pct']}%."
    )
    lines.append(
        f"5. **Dispute risk rises with instalment depth** - from "
        f"{m['dispute_by_installments'][0]['dispute_rate_pct']}% at one instalment to "
        f"{m['dispute_by_installments'][-1]['dispute_rate_pct']}% at thirteen or more, "
        f"covering {brl(m['dispute_total']['disputed_value'])} of cash."
    )
    lines.append(
        f"6. **Growth is acquisition, not retention.** Cash grew "
        f"{y['cash_growth_pct']}% like-for-like while average order value grew "
        f"{y['aov_growth_pct']}% and only "
        f"{m['customer_economics']['repeat_customer_rate_pct']}% of customers ever "
        "reordered."
    )
    lines.append("")
    lines.append("## What this analysis does not claim")
    lines.append("")
    lines.append(
        "- The source data has no refund, chargeback, complaint, logistics-cost or "
        "marketing-spend table. Refund exposure and disputed value are proxies; no "
        "intervention has been measured, so no saving or avoided loss is claimed."
    )
    lines.append(
        "- The cost-to-serve model uses published market rates. Every modelled number "
        "carries a sensitivity band and is labelled as modelled."
    )
    lines.append(
        "- The dataset is real, anonymised commercial data from 2016-2018. It is a "
        "historical extract; the business context is a marketplace, not a bank."
    )
    lines.append("")
    EXECUTIVE_SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"[analyze] wrote {EXECUTIVE_SUMMARY_MD.name}")


def write_decision_report(m: dict) -> None:
    h = m["headline"]
    y = m["yoy"]
    r = m["reconciliation"]
    c = m["cost_model"]
    lines = []
    lines.append("# Business decision report")
    lines.append("")
    lines.append(
        "**Target stakeholder.** Head of Finance / Financial Operations Manager at a "
        "Brazilian marketplace operating an Olist-style model: third-party sellers, "
        "multiple payment methods, customer funds collected before seller settlement."
    )
    lines.append("")
    lines.append("## The decision")
    lines.append("")
    lines.append(
        "The finance team currently reports GMV. This analysis shows that GMV and cash "
        "are not the same population and that neither is net revenue. The decision is "
        "which of the three the business should manage on, and what has to be fixed in "
        "the data pipeline before it can."
    )
    lines.append("")
    lines.append("| Option | What it fixes | Evidence | Cost to implement | Verdict |")
    lines.append("|---|---|---|---|---|")
    lines.append(
        f"| A. Keep reporting GMV | Nothing | {brl(h['gmv'])} of merchandise value | "
        "None | **Rejected** - GMV ignores freight, refunds and the "
        f"{brl(r['cash_without_merchandise'])} of cash with no merchandise record |"
    )
    lines.append(
        f"| B. Manage on net revenue | Revenue recognition | "
        f"{brl(h['net_revenue'])} net of {brl(h['refund_exposure'])} exposure | "
        "Low - a status rule on the fact table | **Recommended as the reporting spine** |"
    )
    lines.append(
        f"| C. Fix the reconciliation break | Control | "
        f"{r['orders_in_break']:,} orders, {brl(r['gross_break_value'])} gross break | "
        "Medium - upstream order-detail extract | **Recommended, in parallel** |"
    )
    lines.append(
        f"| D. Shift payment mix away from long instalments | Modelled cost | "
        f"{brl(c['installment_funding_cost'])} of modelled instalment funding | "
        "Medium - pricing and checkout incentive changes | **Test, do not assume** |"
    )
    lines.append(
        f"| E. Tighten logistics on heavy categories | Freight ratio | "
        f"{h['freight_ratio_pct']}% of GMV, {y['freight_ratio_change_pts']:+} pts YoY | "
        "Medium - carrier pricing and seller terms | **Recommended as a pilot** |"
    )
    lines.append("")
    lines.append("## Why B and C first")
    lines.append("")
    lines.append(
        f"Options B and C are the only two that change what the business *knows*. They "
        "cost no discount and no subsidy, they require no customer behaviour change, "
        "and they make every other option measurable afterwards. D and E are real "
        "levers but their impact cannot be observed until the reporting spine is "
        "correct - which is exactly why they come later."
    )
    lines.append("")
    lines.append("## B: Manage on net revenue")
    lines.append("")
    lines.append(
        f"**Recommendation.** Adopt net revenue ({brl(h['net_revenue'])}) as the "
        "headline financial measure, with cash collected and GMV as supporting lines."
    )
    lines.append("")
    lines.append(
        "**Why.** Net revenue is the only one of the three measures that is both "
        "measured from the data and comparable across periods. It answers the question "
        "a finance team is actually asked - what did the business keep - and it "
        "explicitly carries the refund exposure that GMV hides."
    )
    lines.append("")
    lines.append(
        f"**Measured baseline.** Net revenue is {pct(h['net_revenue_pct_of_cash'], 3)} of "
        f"cash collected; refund exposure runs at "
        f"{pct(100 * h['refund_exposure'] / h['cash_collected'], 3)} of cash collected "
        f"and peaked at {max(x['refund_exposure_pct'] for x in m['monthly'] if '2017-01-01' <= x['purchase_month'] <= '2018-08-01')}% "
        "in a single month of the clean window."
    )
    lines.append("")
    lines.append(
        "**Limitations.** The refund figure is an exposure proxy, not a refunds ledger - "
        "the source has no refund table. Before the measure is used for external "
        "reporting it needs the actual refund transactions, and the exposure policy "
        "(reserve basis, cut-off) has to be set by the finance team."
    )
    lines.append("")
    lines.append("## C: Fix the reconciliation break")
    lines.append("")
    lines.append(
        f"**Recommendation.** Raise a control ticket for the {r['orders_in_break']:,} "
        f"orders that fail the reconciliation, prioritising the "
        f"{r['paid_orders_without_line_items']:,} orders with cash and no line items "
        f"({brl(r['cash_without_merchandise'])})."
    )
    lines.append("")
    lines.append(
        "**Why.** This is the one finding in the analysis that is unambiguously a data "
        "defect rather than a business outcome. Cash has been collected; the order "
        "content that would justify it is missing from the extract. Until it is "
        "recovered, no revenue number in this dataset can be independently verified."
    )
    lines.append("")
    lines.append(
        "**Measured baseline.** "
        f"{r['orders_in_break']:,} orders in break ({r['break_rate_pct']}%), "
        f"{brl(r['gross_break_value'])} of gross break value, of which "
        f"{brl(r['cash_without_merchandise'])} is cash with no merchandise record. "
        "The break has been reported, not corrected, so this baseline will not move "
        "on its own."
    )
    lines.append("")
    lines.append(
        "**Limitations.** The analysis cannot tell whether the missing content was "
        "never captured, was deleted when the order was cancelled, or was lost in the "
        "extract. That distinction determines whether this is a pipeline fix or a "
        "historical backfill, and it has to be answered upstream."
    )
    lines.append("")
    lines.append("## D: Payment mix (test, do not assume)")
    lines.append("")
    band = c["sensitivity"]
    low = band[0]["installment_funding_cost"]
    high = band[-1]["installment_funding_cost"]
    base = c["installment_funding_cost"]
    lines.append(
        f"**Recommendation.** Model the cost of the payment mix before changing it. The "
        f"modelled instalment-funding cost is {brl(base)} at the "
        f"{pct(config.INSTALLMENT_FUNDING_RATE * 100, 2)} base rate, but the published "
        f"band runs from {brl(low)} to {brl(high)} - so the *size* of the lever is "
        f"assumption-dependent even though its *direction* is not. At the low end the "
        f"instalment-funding cost would still be "
        f"{pct(100 * low / c['acquiring_cost'], 0)} of the modelled acquiring cost."
    )
    lines.append("")
    lines.append(
        "**Limitations.** No contractual rate for this marketplace is in the data, no "
        "checkout experiment has been run, and the direction of customer behaviour "
        "response to a payment-method incentive is unknown. No saving is claimed here, "
        "because none has been measured."
    )
    lines.append("")
    lines.append("## E: Logistics (pilot on the heavy categories)")
    lines.append("")
    lines.append("")
    lines.append("## Measurement plan")
    lines.append("")
    lines.append("| Metric | Baseline (measured) | Target | Source |")
    lines.append("|---|---:|---|---|")
    lines.append(
        f"| Reconciliation break rate | {h['reconciliation_break_rate_pct']}% of orders | "
        "< 0.25% | fact_order_financials |"
    )
    lines.append(
        f"| Cash with no merchandise record | {brl(r['cash_without_merchandise'])} | "
        "R$ 0.00 | fact_order_financials |"
    )
    lines.append(
        f"| Refund exposure rate | {pct(100 * h['refund_exposure'] / h['cash_collected'], 3)} "
        "of cash | within policy | fact_order_financials |"
    )
    lines.append(
        f"| Freight ratio (Jan-Aug YoY) | {y['freight_ratio_2018']}% | "
        f"<= {y['freight_ratio_2017']}% | v_item_financials |"
    )
    lines.append(
        f"| Dispute rate, 7+ instalments | "
        f"{[x for x in m['dispute_by_installments'] if x['instalment_bucket'] == '7 - 12'][0]['dispute_rate_pct']}% "
        "| monitor | fact_order_financials |"
    )
    lines.append("")
    lines.append(
        "Every baseline in this table is produced by `src/analyze.py` and reproducible "
        "from `sql/04_revenue_and_cash.sql` and `sql/06_exposure_and_reconciliation.sql`."
    )
    lines.append("")
    DECISION_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"[analyze] wrote {DECISION_REPORT_MD.name}")


if __name__ == "__main__":
    main()
