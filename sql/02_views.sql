-- ===========================================================================
--  02_views.sql  |  Analytic layer
-- ---------------------------------------------------------------------------
--  Views are the contract between the SQL layer, the Python analysis, the
--  Excel workbook and the Power BI model. Every financial number in the
--  project is produced by one of these views, so the definitions cannot
--  drift between tools.
--
--  v_order_financials  : the order-level fact. One row per order with
--                         revenue, cash collected, reconciliation delta,
--                         status class, payment mix and risk flags.
--  v_payment_detail    : payment-level fact with method and risk attributes.
--  v_item_financials   : line-item fact joined to product and seller.
--  v_seller_performance: seller-level financial summary.
--  v_category_financials: product-category-level financial summary.
--  dim_date            : continuous date spine for the reporting window.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- dim_date : one row per calendar day across the observation window.
-- ---------------------------------------------------------------------------
CREATE VIEW dim_date AS
WITH RECURSIVE
bounds AS (
    SELECT MIN(date(order_purchase_timestamp)) AS start_date,
           MAX(date(order_purchase_timestamp)) AS end_date
    FROM orders
),
calendar(date) AS (
    SELECT start_date FROM bounds
    UNION ALL
    SELECT date(date, '+1 day') FROM calendar, bounds
    WHERE date < (SELECT end_date FROM bounds)
)
SELECT
    c.date                                   AS full_date,
    strftime('%Y-%m-01', c.date)             AS month_start,
    strftime('%Y', c.date)                   AS year,
    strftime('%m', c.date)                   AS month_num,
    strftime('%Y-%m', c.date)                AS month_key,
    CASE
        WHEN CAST(strftime('%m', c.date) AS INTEGER) BETWEEN 1 AND 3  THEN strftime('%Y', c.date) || '-Q1'
        WHEN CAST(strftime('%m', c.date) AS INTEGER) BETWEEN 4 AND 6  THEN strftime('%Y', c.date) || '-Q2'
        WHEN CAST(strftime('%m', c.date) AS INTEGER) BETWEEN 7 AND 9  THEN strftime('%Y', c.date) || '-Q3'
        ELSE strftime('%Y', c.date) || '-Q4'
    END                                      AS quarter_key,
    CAST(strftime('%w', c.date) AS INTEGER)  AS day_of_week,
    CASE WHEN CAST(strftime('%w', c.date) AS INTEGER) IN (0, 6)
         THEN 1 ELSE 0 END                    AS is_weekend
FROM calendar c;

-- ---------------------------------------------------------------------------
-- v_payment_detail : payment-level fact.
-- ---------------------------------------------------------------------------
CREATE VIEW v_payment_detail AS
SELECT
    p.order_id,
    p.payment_sequential,
    p.payment_type,
    p.payment_installments,
    p.payment_value,
    o.order_status,
    CASE o.order_status
        WHEN 'delivered'   THEN 'fulfilled'
        WHEN 'shipped'     THEN 'in_flight'
        WHEN 'invoiced'    THEN 'in_flight'
        WHEN 'processing'  THEN 'in_flight'
        WHEN 'created'     THEN 'in_flight'
        WHEN 'approved'    THEN 'in_flight'
        WHEN 'canceled'    THEN 'cancelled'
        WHEN 'unavailable' THEN 'unavailable'
        ELSE 'other'
    END                                   AS status_class,
    o.order_purchase_timestamp,
    strftime('%Y-%m-01', o.order_purchase_timestamp) AS purchase_month,
    strftime('%Y', o.order_purchase_timestamp)       AS purchase_year,
    c.customer_state,
    c.customer_unique_id,
    -- Cash that was collected but against an order that will never be
    -- fulfilled: refund exposure (proxy - refunds are not recorded).
    CASE WHEN o.order_status IN ('canceled', 'unavailable') THEN p.payment_value ELSE 0 END AS refund_exposure_value,
    -- A marketplace-funded promotional credit: revenue forgone, not collected.
    CASE WHEN p.payment_type = 'voucher' THEN p.payment_value ELSE 0 END AS voucher_value,
    -- Consumer credit extension: value that will be settled in instalments.
    CASE WHEN p.payment_type = 'credit_card' AND p.payment_installments > 1
         THEN p.payment_value ELSE 0 END AS installment_credit_value
FROM payments p
JOIN orders    o ON o.order_id = p.order_id
JOIN customers c ON c.customer_id = o.customer_id;

-- ---------------------------------------------------------------------------
-- v_order_financials : the order-level fact used by every KPI.
--
--  Definitions locked here:
--    gmv             = SUM(order_items.price)
--    freight_total   = SUM(order_items.freight_value)
--    expected_charge = gmv + freight_total      (what the order should cost)
--    cash_collected  = SUM(payments.payment_value)
--    recon_delta     = cash_collected - expected_charge
--    net_revenue     = cash_collected - refund_exposure_value
-- ---------------------------------------------------------------------------
CREATE VIEW v_order_financials AS
WITH item_agg AS (
    SELECT
        order_id,
        COUNT(*)                     AS line_item_count,
        COUNT(DISTINCT seller_id)    AS seller_count,
        COUNT(DISTINCT product_id)   AS product_count,
        SUM(price)                   AS gmv,
        SUM(freight_value)           AS freight_total
    FROM order_items
    GROUP BY order_id
),
pay_agg AS (
    SELECT
        order_id,
        COUNT(*)                      AS payment_count,
        SUM(payment_value)            AS cash_collected,
        MAX(payment_installments)     AS max_installments,
        SUM(payment_installments)     AS installment_months,
        SUM(CASE WHEN payment_type = 'credit_card' THEN payment_value ELSE 0 END) AS card_value,
        SUM(CASE WHEN payment_type = 'boleto'       THEN payment_value ELSE 0 END) AS boleto_value,
        SUM(CASE WHEN payment_type = 'debit_card'   THEN payment_value ELSE 0 END) AS debit_card_value,
        SUM(CASE WHEN payment_type = 'voucher'      THEN payment_value ELSE 0 END) AS voucher_value,
        SUM(CASE WHEN payment_type = 'not_defined'  THEN payment_value ELSE 0 END) AS undefined_value
    FROM payments
    GROUP BY order_id
),
dominant AS (
    SELECT order_id, payment_type AS primary_payment_type
    FROM (
        SELECT order_id, payment_type,
               ROW_NUMBER() OVER (PARTITION BY order_id
                                  ORDER BY payment_value DESC, payment_sequential ASC) AS rn
        FROM payments
    )
    WHERE rn = 1
),
review_agg AS (
    SELECT
        r.order_id,
        COUNT(*)          AS review_count,
        MIN(r.review_score) AS worst_review_score,
        AVG(r.review_score) AS avg_review_score,
        COUNT(DISTINCT r.review_id) AS distinct_review_ids,
        -- A review_id that also appears against another order of the same
        -- customer: one submission duplicated across two orders.
        MAX(CASE WHEN dup.n_orders > 1 THEN 1 ELSE 0 END) AS duplicate_review_flag
    FROM reviews r
    LEFT JOIN (
        SELECT review_id, COUNT(DISTINCT order_id) AS n_orders
        FROM reviews GROUP BY review_id
    ) dup ON dup.review_id = r.review_id
    GROUP BY r.order_id
)
SELECT
    o.order_id,
    o.customer_id,
    c.customer_unique_id,
    c.customer_state,
    c.customer_zip_code_prefix,
    o.order_status,
    CASE o.order_status
        WHEN 'delivered'   THEN 'fulfilled'
        WHEN 'shipped'     THEN 'in_flight'
        WHEN 'invoiced'    THEN 'in_flight'
        WHEN 'processing'  THEN 'in_flight'
        WHEN 'created'     THEN 'in_flight'
        WHEN 'approved'    THEN 'in_flight'
        WHEN 'canceled'    THEN 'cancelled'
        WHEN 'unavailable' THEN 'unavailable'
        ELSE 'other'
    END                                                     AS status_class,
    o.order_purchase_timestamp,
    date(o.order_purchase_timestamp)                       AS purchase_date,
    strftime('%Y-%m-01', o.order_purchase_timestamp)       AS purchase_month,
    strftime('%Y', o.order_purchase_timestamp)             AS purchase_year,
    CASE
        WHEN CAST(strftime('%m', o.order_purchase_timestamp) AS INTEGER) BETWEEN 1 AND 3 THEN strftime('%Y', o.order_purchase_timestamp) || '-Q1'
        WHEN CAST(strftime('%m', o.order_purchase_timestamp) AS INTEGER) BETWEEN 4 AND 6 THEN strftime('%Y', o.order_purchase_timestamp) || '-Q2'
        WHEN CAST(strftime('%m', o.order_purchase_timestamp) AS INTEGER) BETWEEN 7 AND 9 THEN strftime('%Y', o.order_purchase_timestamp) || '-Q3'
        ELSE strftime('%Y', o.order_purchase_timestamp) || '-Q4'
    END                                                     AS purchase_quarter,
    o.order_approved_at,
    o.order_delivered_carrier_date,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date,
    -- Cycle time from purchase to customer delivery, in days.
    CASE WHEN o.order_delivered_customer_date IS NOT NULL
         THEN ROUND(julianday(o.order_delivered_customer_date)
                  - julianday(o.order_purchase_timestamp), 2)
    END                                                     AS delivery_days,
    -- Days late against the promised delivery date.
    CASE WHEN o.order_delivered_customer_date IS NOT NULL
          AND o.order_estimated_delivery_date IS NOT NULL
         THEN ROUND(julianday(o.order_delivered_customer_date)
                  - julianday(o.order_estimated_delivery_date), 2)
    END                                                     AS days_late_vs_promise,
    COALESCE(ia.line_item_count, 0)                        AS line_item_count,
    COALESCE(ia.seller_count, 0)                           AS seller_count,
    COALESCE(ia.product_count, 0)                          AS product_count,
    COALESCE(ia.gmv, 0)                                    AS gmv,
    COALESCE(ia.freight_total, 0)                          AS freight_total,
    COALESCE(ia.gmv, 0) + COALESCE(ia.freight_total, 0)    AS expected_charge,
    COALESCE(pa.cash_collected, 0)                         AS cash_collected,
    COALESCE(pa.cash_collected, 0)
      - (COALESCE(ia.gmv, 0) + COALESCE(ia.freight_total, 0)) AS recon_delta,
    CASE WHEN COALESCE(pa.cash_collected, 0)
              - (COALESCE(ia.gmv, 0) + COALESCE(ia.freight_total, 0)) >= 0.01
          OR COALESCE(pa.cash_collected, 0)
              - (COALESCE(ia.gmv, 0) + COALESCE(ia.freight_total, 0)) <= -0.01
         THEN 1 ELSE 0 END                                 AS recon_break_flag,
    COALESCE(pa.payment_count, 0)                          AS payment_count,
    COALESCE(pa.max_installments, 0)                       AS max_installments,
    COALESCE(pa.installment_months, 0)                     AS installment_months,
    d.primary_payment_type,
    COALESCE(pa.card_value, 0)                            AS card_value,
    COALESCE(pa.boleto_value, 0)                          AS boleto_value,
    COALESCE(pa.debit_card_value, 0)                       AS debit_card_value,
    COALESCE(pa.voucher_value, 0)                         AS voucher_value,
    COALESCE(pa.undefined_value, 0)                       AS undefined_value,
    -- Refund exposure: cash collected on orders that will never be fulfilled.
    CASE WHEN o.order_status IN ('canceled', 'unavailable')
         THEN COALESCE(pa.cash_collected, 0) ELSE 0 END    AS refund_exposure_value,
    -- Net revenue = what the business actually keeps after the refund exposure.
    CASE WHEN o.order_status IN ('canceled', 'unavailable')
         THEN 0 ELSE COALESCE(pa.cash_collected, 0) END    AS net_revenue,
    -- Settlement float: collected but not yet released to the seller.
    CASE WHEN o.order_status IN ('shipped', 'invoiced', 'processing', 'created', 'approved')
         THEN COALESCE(pa.cash_collected, 0) ELSE 0 END    AS settlement_float_value,
    COALESCE(rv.review_count, 0)                          AS review_count,
    rv.worst_review_score,
    ROUND(rv.avg_review_score, 3)                         AS avg_review_score,
    COALESCE(rv.duplicate_review_flag, 0)                 AS duplicate_review_flag,
    CASE WHEN rv.worst_review_score IS NOT NULL AND rv.worst_review_score <= 2
         THEN 1 ELSE 0 END                                 AS disputed_flag
FROM orders o
JOIN customers c      ON c.customer_id = o.customer_id
LEFT JOIN item_agg ia ON ia.order_id = o.order_id
LEFT JOIN pay_agg  pa ON pa.order_id = o.order_id
LEFT JOIN dominant d  ON d.order_id  = o.order_id
LEFT JOIN review_agg rv ON rv.order_id = o.order_id;

-- ---------------------------------------------------------------------------
-- v_item_financials : line-item fact joined to product, seller and category.
-- ---------------------------------------------------------------------------
CREATE VIEW v_item_financials AS
SELECT
    it.order_id,
    it.order_item_id,
    it.product_id,
    it.seller_id,
    it.price,
    it.freight_value,
    it.price + it.freight_value                          AS line_charge,
    p.product_category_name,
    COALESCE(t.product_category_name_english, p.product_category_name) AS category_english,
    p.product_weight_g,
    s.seller_state,
    s.seller_city,
    o.order_status,
    o.order_purchase_timestamp,
    strftime('%Y-%m-01', o.order_purchase_timestamp)     AS purchase_month,
    strftime('%Y', o.order_purchase_timestamp)           AS purchase_year,
    CASE WHEN it.freight_value > it.price AND it.price > 0 THEN 1 ELSE 0 END AS freight_over_price_flag,
    CASE WHEN it.price + it.freight_value > 3000 THEN 1 ELSE 0 END        AS large_line_flag
FROM order_items it
JOIN orders   o ON o.order_id    = it.order_id
LEFT JOIN products p ON p.product_id = it.product_id
LEFT JOIN product_category_translation t
       ON t.product_category_name = p.product_category_name
LEFT JOIN sellers s ON s.seller_id = it.seller_id;

-- ---------------------------------------------------------------------------
-- v_seller_performance : seller-level financial summary.
-- ---------------------------------------------------------------------------
CREATE VIEW v_seller_performance AS
SELECT
    it.seller_id,
    s.seller_state,
    COUNT(DISTINCT it.order_id)   AS order_count,
    COUNT(*)                      AS line_item_count,
    SUM(it.price)                 AS seller_gmv,
    SUM(it.freight_value)         AS seller_freight,
    SUM(it.price) + SUM(it.freight_value) AS seller_charge,
    ROUND(100.0 * SUM(it.freight_value) / NULLIF(SUM(it.price), 0), 2) AS freight_ratio_pct,
    ROUND(SUM(it.price) / NULLIF(COUNT(DISTINCT it.order_id), 0), 2)  AS avg_order_value,
    COUNT(DISTINCT it.product_id) AS product_count
FROM order_items it
LEFT JOIN sellers s ON s.seller_id = it.seller_id
GROUP BY it.seller_id, s.seller_state;

-- ---------------------------------------------------------------------------
-- v_category_financials : product-category-level financial summary.
-- ---------------------------------------------------------------------------
CREATE VIEW v_category_financials AS
SELECT
    COALESCE(t.product_category_name_english, p.product_category_name) AS category_english,
    p.product_category_name,
    COUNT(DISTINCT it.order_id) AS order_count,
    COUNT(*)                    AS line_item_count,
    SUM(it.price)               AS category_gmv,
    SUM(it.freight_value)       AS category_freight,
    ROUND(100.0 * SUM(it.freight_value) / NULLIF(SUM(it.price), 0), 2) AS freight_ratio_pct,
    ROUND(SUM(it.price) / NULLIF(COUNT(*), 0), 2) AS avg_item_price
FROM order_items it
LEFT JOIN products p ON p.product_id = it.product_id
LEFT JOIN product_category_translation t
       ON t.product_category_name = p.product_category_name
GROUP BY COALESCE(t.product_category_name_english, p.product_category_name),
         p.product_category_name;
