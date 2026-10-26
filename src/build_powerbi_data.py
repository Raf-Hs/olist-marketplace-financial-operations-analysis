"""Publish the Power BI star schema as CSV.

Pipeline step 3a:  load -> clean -> query -> report.

The `.pbit` template built by `powerbi/build_pbit.py` consumes these files
through Power Query. They are deliberately flat and pre-aggregated where the
grain demands it, so that opening the template in Power BI Desktop never
requires a live connection.

Star schema
-----------
    FactOrder      one row per order          (the financial fact)
    FactPayment    one row per payment        (payment mix and cost-to-serve)
    FactOrderItem  one row per order line     (logistics cost-to-serve)
    DimDate        one row per calendar day
    DimCustomer    one row per real customer  (keyed on customer_unique_id)
    DimSeller      one row per seller
    DimProduct     one row per product
    DimPaymentMethod one row per payment method, carrying the modelled rates

Usage:
    python src/build_powerbi_data.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402


def _write(df: pd.DataFrame, name: str) -> None:
    path = config.POWERBI_DATA_DIR / f"{name}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    print(f"[build_powerbi_data] wrote {name}.csv: {len(df):,} rows")


def main() -> None:
    conn = sqlite3.connect(config.DB_PATH)

    # ------------------------------------------------------------- FactOrder
    fact_order = pd.read_sql_query(
        """
        SELECT
            o.order_id                       AS OrderKey,
            CAST(REPLACE(REPLACE(o.purchase_date,'-',''),'/','') AS INTEGER) AS DateKey,
            o.customer_unique_id             AS CustomerKey,
            COALESCE(o.primary_payment_type, 'not_defined') AS PaymentMethodKey,
            o.order_status                   AS OrderStatus,
            o.status_class                   AS StatusClass,
            o.purchase_month                 AS PurchaseMonth,
            o.purchase_year                  AS PurchaseYear,
            o.purchase_quarter               AS PurchaseQuarter,
            o.customer_state                 AS CustomerState,
            o.line_item_count                AS LineItemCount,
            o.seller_count                   AS SellerCount,
            o.product_count                  AS ProductCount,
            o.gmv                            AS MerchandiseValue,
            o.freight_total                  AS FreightCollected,
            o.expected_charge                AS ExpectedCharge,
            o.cash_collected                 AS CashCollected,
            o.recon_delta                    AS ReconDelta,
            o.recon_break_flag               AS ReconBreak,
            o.payment_count                  AS PaymentCount,
            o.max_installments               AS MaxInstallments,
            o.installment_months             AS InstallmentMonths,
            o.refund_exposure_value          AS RefundExposure,
            o.net_revenue                    AS NetRevenue,
            o.settlement_float_value         AS SettlementFloat,
            o.voucher_value                  AS VoucherValue,
            o.card_value                     AS CardValue,
            o.boleto_value                   AS BoletoValue,
            o.debit_card_value               AS DebitCardValue,
            o.review_count                   AS ReviewCount,
            o.worst_review_score             AS WorstReviewScore,
            o.disputed_flag                  AS DisputedFlag,
            o.delivery_days                  AS DeliveryDays,
            o.days_late_vs_promise           AS DaysLateVsPromise
        FROM fact_order_financials o
        ORDER BY o.order_id
        """,
        conn,
    )
    _write(fact_order, "FactOrder")

    # ----------------------------------------------------------- FactPayment
    fact_payment = pd.read_sql_query(
        """
        SELECT
            p.order_id                                   AS OrderKey,
            p.payment_sequential                          AS PaymentSequence,
            p.payment_type                               AS PaymentMethodKey,
            CAST(REPLACE(REPLACE(date(p.order_purchase_timestamp),'-',''),'/','') AS INTEGER) AS DateKey,
            p.payment_installments                       AS Installments,
            p.payment_value                              AS PaymentValue,
            p.refund_exposure_value                      AS RefundExposure,
            p.voucher_value                              AS VoucherValue,
            p.installment_credit_value                   AS InstallmentCreditValue,
            p.status_class                               AS StatusClass,
            p.customer_state                             AS CustomerState
        FROM v_payment_detail p
        ORDER BY p.order_id, p.payment_sequential
        """,
        conn,
    )
    _write(fact_payment, "FactPayment")

    # --------------------------------------------------------- FactOrderItem
    fact_item = pd.read_sql_query(
        """
        SELECT
            i.order_id                       AS OrderKey,
            i.order_item_id                  AS OrderItemKey,
            i.product_id                     AS ProductKey,
            i.seller_id                      AS SellerKey,
            CAST(REPLACE(REPLACE(date(i.order_purchase_timestamp),'-',''),'/','') AS INTEGER) AS DateKey,
            i.price                          AS Price,
            i.freight_value                  AS FreightValue,
            i.line_charge                    AS LineCharge,
            i.freight_over_price_flag        AS FreightOverPrice,
            i.large_line_flag                AS LargeLine,
            i.product_weight_g               AS ProductWeightG,
            i.seller_state                   AS SellerState
        FROM v_item_financials i
        ORDER BY i.order_id, i.order_item_id
        """,
        conn,
    )
    _write(fact_item, "FactOrderItem")

    # --------------------------------------------------------------- DimDate
    dim_date = pd.read_sql_query(
        """
        SELECT
            CAST(REPLACE(REPLACE(full_date,'-',''),'/','') AS INTEGER) AS DateKey,
            full_date,
            year,
            CAST(month_num AS INTEGER)       AS MonthNumber,
            quarter_key,
            month_start,
            day_of_week,
            is_weekend
        FROM dim_date
        ORDER BY full_date
        """,
        conn,
    )
    dim_date["full_date"] = pd.to_datetime(dim_date["full_date"]).dt.strftime("%Y-%m-%d")
    dim_date["month_start"] = pd.to_datetime(dim_date["month_start"]).dt.strftime("%Y-%m-%d")
    _write(dim_date, "DimDate")

    # ----------------------------------------------------------- DimCustomer
    dim_customer = pd.read_sql_query(
        """
        WITH cu AS (
            SELECT customer_unique_id,
                   MIN(customer_state)              AS customer_state,
                   MIN(customer_zip_code_prefix)    AS zip_code_prefix,
                   COUNT(DISTINCT order_id)         AS order_count,
                   SUM(cash_collected)              AS cash_collected,
                   SUM(gmv)                         AS gmv,
                   SUM(refund_exposure_value)       AS refund_exposure,
                   SUM(disputed_flag)               AS disputed_orders,
                   MIN(purchase_date)               AS first_purchase_date,
                   MAX(purchase_date)               AS last_purchase_date,
                   SUM(settlement_float_value)      AS settlement_float,
                   SUM(max_installments)            AS installment_months
            FROM fact_order_financials
            GROUP BY customer_unique_id
        )
        SELECT
            c.customer_unique_id                       AS CustomerKey,
            c.customer_state                           AS CustomerState,
            c.zip_code_prefix                          AS ZipCodePrefix,
            c.order_count                              AS OrderCount,
            ROUND(c.cash_collected,2)                  AS CashCollected,
            ROUND(c.gmv,2)                             AS CustomerGMV,
            ROUND(c.refund_exposure,2)                 AS RefundExposure,
            c.disputed_orders                          AS DisputedOrders,
            c.first_purchase_date                      AS FirstPurchaseDate,
            c.last_purchase_date                       AS LastPurchaseDate,
            ROUND(c.cash_collected/c.order_count,2)     AS AverageOrderValue,
            CASE WHEN c.order_count > 1 THEN 1 ELSE 0 END AS IsRepeat,
            c.settlement_float                         AS SettlementFloat,
            c.installment_months                       AS InstallmentMonths
        FROM cu c
        ORDER BY c.cash_collected DESC
        """,
        conn,
    )
    _write(dim_customer, "DimCustomer")

    # ------------------------------------------------------------- DimSeller
    dim_seller = pd.read_sql_query(
        """
        WITH s AS (SELECT seller_id, SUM(price) AS gmv FROM order_items GROUP BY seller_id),
             ranked AS (SELECT seller_id, gmv, RANK() OVER (ORDER BY gmv DESC) AS gmv_rank FROM s)
        SELECT
            r.seller_id                     AS SellerKey,
            COALESCE(p.seller_state, s.seller_state) AS SellerState,
            s.seller_city                   AS SellerCity,
            r.gmv_rank                      AS GMVRank,
            ROUND(r.gmv,2)                  AS SellerGMV,
            p.order_count                   AS OrderCount,
            p.product_count                 AS ProductCount,
            ROUND(p.seller_freight,2)       AS SellerFreight,
            p.freight_ratio_pct             AS FreightRatioPct,
            ROUND(p.avg_order_value,2)      AS AverageOrderValue
        FROM ranked r
        LEFT JOIN v_seller_performance p ON p.seller_id = r.seller_id
        LEFT JOIN sellers s ON s.seller_id = r.seller_id
        ORDER BY r.gmv_rank
        """,
        conn,
    )
    _write(dim_seller, "DimSeller")

    # ------------------------------------------------------------ DimProduct
    dim_product = pd.read_sql_query(
        """
        SELECT
            p.product_id                        AS ProductKey,
            p.product_category_name             AS ProductCategory,
            COALESCE(t.product_category_name_english, p.product_category_name) AS CategoryEnglish,
            p.product_weight_g                  AS ProductWeightG,
            p.product_length_cm                 AS ProductLengthCm,
            p.product_height_cm                 AS ProductHeightCm,
            p.product_width_cm                  AS ProductWidthCm,
            p.product_photos_qty                AS ProductPhotosQty,
            COUNT(i.order_item_id)               AS LineItemCount,
            ROUND(SUM(i.price),2)                AS ProductGMV
        FROM products p
        LEFT JOIN product_category_translation t
               ON t.product_category_name = p.product_category_name
        LEFT JOIN order_items i ON i.product_id = p.product_id
        GROUP BY p.product_id, p.product_category_name,
                 COALESCE(t.product_category_name_english, p.product_category_name),
                 p.product_weight_g, p.product_length_cm, p.product_height_cm,
                 p.product_width_cm, p.product_photos_qty
        """,
        conn,
    )
    _write(dim_product, "DimProduct")

    # ----------------------------------------------------- DimPaymentMethod
    descriptions = {
        "credit_card": "Card payment - may be settled in instalments",
        "boleto": "Bank slip - paid in cash-equivalent at the branch or online",
        "voucher": "Marketplace-funded promotional credit (revenue forgone)",
        "debit_card": "Debit card - settled from a bank account",
        "not_defined": "Payment with no type recorded (zero value)",
    }
    rows = []
    for method, (pct, fee, note) in config.PAYMENT_COST_MODEL.items():
        rows.append(
            {
                "PaymentMethodKey": method,
                "PaymentType": method,
                "Description": descriptions.get(method, ""),
                "RatePct": pct,
                "FixedFee": fee,
                "FundingRatePerInstallment": config.INSTALLMENT_FUNDING_RATE
                if method == "credit_card"
                else 0.0,
                "IsPromotional": method in config.PROMOTIONAL_METHODS,
                "AssumptionNote": note,
            }
        )
    dim_method = pd.DataFrame(rows).sort_values("PaymentMethodKey")
    _write(dim_method, "DimPaymentMethod")

    conn.close()


if __name__ == "__main__":
    main()
