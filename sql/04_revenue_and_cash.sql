-- =====================================================================
-- 04_revenue_and_cash.sql
-- The revenue-vs-cash reconciliation: what the marketplace sold, what
-- customers paid, what it kept, and how the trend behaves once the
-- partial boundary months are removed.
--
-- Every figure here is MEASURED from the source data. No assumption is
-- applied in this file.
-- =====================================================================


-- name: r01_headline_financials
-- description: Headline scoreboard - merchandise value, cash collected, refund exposure, net revenue and the reconciliation gap for the whole window.
SELECT
    COUNT(*)                                                            AS orders,
    COUNT(DISTINCT customer_unique_id)                                  AS unique_customers,
    ROUND(SUM(gmv),2)                                                   AS gmv_merchandise,
    ROUND(SUM(freight_total),2)                                         AS freight_collected,
    ROUND(SUM(expected_charge),2)                                       AS expected_charge,
    ROUND(SUM(cash_collected),2)                                        AS cash_collected,
    ROUND(SUM(refund_exposure_value),2)                                 AS refund_exposure,
    ROUND(SUM(net_revenue),2)                                           AS net_revenue,
    ROUND(SUM(cash_collected) - SUM(net_revenue),2)                     AS reconciliation_gap,
    ROUND(100.0 * SUM(net_revenue) / SUM(cash_collected), 3)            AS net_revenue_pct_of_cash,
    ROUND(SUM(cash_collected) / COUNT(*), 2)                            AS average_order_value,
    ROUND(100.0 * SUM(freight_total) / SUM(gmv), 2)                     AS freight_ratio_pct,
    ROUND(SUM(settlement_float_value),2)                                AS settlement_float,
    SUM(recon_break_flag)                                               AS reconciliation_breaks
FROM fact_order_financials;


-- name: r02_cash_versus_revenue_by_status
-- description: Where cash and merchandise diverge by order status. Cancelled and unavailable orders carry 100% refund exposure.
SELECT order_status,
       status_class,
       COUNT(*)                        AS orders,
       ROUND(SUM(cash_collected),2)    AS cash_collected,
       ROUND(SUM(gmv),2)               AS gmv,
       ROUND(SUM(refund_exposure_value),2) AS refund_exposure,
       ROUND(100.0*SUM(refund_exposure_value)/NULLIF(SUM(cash_collected),0),3) AS refund_exposure_pct,
       SUM(line_item_count = 0)        AS orders_with_no_line_items,
       ROUND(SUM(cash_collected)*100.0/(SELECT SUM(cash_collected) FROM fact_order_financials),3) AS pct_of_cash
FROM fact_order_financials
GROUP BY order_status, status_class
ORDER BY cash_collected DESC;


-- name: r03_monthly_financials
-- description: Monthly cash, merchandise, AOV, refund exposure and freight ratio across the whole window.
SELECT purchase_month,
       COUNT(*)                        AS orders,
       ROUND(SUM(cash_collected),2)    AS cash_collected,
       ROUND(SUM(gmv),2)               AS gmv,
       ROUND(SUM(freight_total),2)     AS freight,
       ROUND(SUM(refund_exposure_value),2) AS refund_exposure,
       ROUND(100.0*SUM(refund_exposure_value)/NULLIF(SUM(cash_collected),0),3) AS refund_exposure_pct,
       ROUND(SUM(cash_collected)/COUNT(*),2) AS average_order_value,
       ROUND(100.0*SUM(freight_total)/NULLIF(SUM(gmv),0),2) AS freight_ratio_pct,
       COUNT(DISTINCT customer_unique_id) AS active_customers
FROM fact_order_financials
GROUP BY purchase_month
ORDER BY purchase_month;


-- name: r04_month_on_month_change
-- description: Period-on-period movement in cash, orders and AOV inside the clean window (2017-01 to 2018-08).
WITH monthly AS (
    SELECT purchase_month,
           COUNT(*)                     AS orders,
           SUM(cash_collected)          AS cash,
           SUM(gmv)                     AS gmv,
           SUM(refund_exposure_value)   AS refund_exposure,
           SUM(freight_total)           AS freight,
           COUNT(DISTINCT customer_unique_id) AS customers
    FROM fact_order_financials
    WHERE CAST(strftime('%m', purchase_month) AS INTEGER) BETWEEN 1 AND 8
      AND CAST(purchase_year AS INTEGER) IN (2017, 2018)
    GROUP BY purchase_month
)
SELECT purchase_month,
       orders,
       ROUND(cash,2)      AS cash_collected,
       ROUND(100.0*(cash - LAG(cash) OVER (ORDER BY purchase_month))
                 / NULLIF(LAG(cash) OVER (ORDER BY purchase_month),0),2) AS mom_cash_growth_pct,
       ROUND(100.0*(orders - LAG(orders) OVER (ORDER BY purchase_month))
                 / NULLIF(LAG(orders) OVER (ORDER BY purchase_month),0),2) AS mom_order_growth_pct,
       ROUND(cash/orders,2) AS average_order_value,
       ROUND(100.0*(cash/orders - LAG(cash/orders) OVER (ORDER BY purchase_month))
                 / NULLIF(LAG(cash/orders) OVER (ORDER BY purchase_month),0),2) AS mom_aov_growth_pct,
       ROUND(100.0*refund_exposure/NULLIF(cash,0),3) AS refund_exposure_pct,
       ROUND(100.0*freight/NULLIF(gmv,0),2)         AS freight_ratio_pct
FROM monthly
ORDER BY purchase_month;


-- name: r05_like_for_like_yoy
-- description: Year-on-year comparison on a like-for-like calendar basis (Jan-Aug 2017 vs Jan-Aug 2018). Partial months are excluded.
WITH period AS (
    SELECT purchase_year,
           COUNT(*)                     AS orders,
           SUM(cash_collected)          AS cash,
           SUM(gmv)                     AS gmv,
           SUM(freight_total)           AS freight,
           SUM(refund_exposure_value)   AS refund_exposure,
           COUNT(DISTINCT customer_unique_id) AS customers
    FROM fact_order_financials
    WHERE CAST(strftime('%m', purchase_month) AS INTEGER) BETWEEN 1 AND 8
      AND CAST(purchase_year AS INTEGER) IN (2017, 2018)
    GROUP BY purchase_year
)
SELECT '2017-01..2017-08' AS period, orders, ROUND(cash,2) AS cash_collected, ROUND(gmv,2) AS gmv,
       ROUND(freight,2) AS freight, ROUND(refund_exposure,2) AS refund_exposure,
       ROUND(cash/orders,2) AS average_order_value, ROUND(100.0*freight/gmv,2) AS freight_ratio_pct,
       ROUND(100.0*refund_exposure/cash,3) AS refund_exposure_pct, customers
FROM period WHERE purchase_year = '2017'
UNION ALL
SELECT '2018-01..2018-08', orders, ROUND(cash,2), ROUND(gmv,2), ROUND(freight,2), ROUND(refund_exposure,2),
       ROUND(cash/orders,2), ROUND(100.0*freight/gmv,2), ROUND(100.0*refund_exposure/cash,3), customers
FROM period WHERE purchase_year = '2018';


-- name: r06_growth_decomposition
-- description: Decomposing year-on-year cash growth into order volume, average order value and customer acquisition.
WITH period AS (
    SELECT purchase_year,
           COUNT(*)                     AS orders,
           SUM(cash_collected)          AS cash,
           COUNT(DISTINCT customer_unique_id) AS customers
    FROM fact_order_financials
    WHERE CAST(strftime('%m', purchase_month) AS INTEGER) BETWEEN 1 AND 8
      AND CAST(purchase_year AS INTEGER) IN (2017, 2018)
    GROUP BY purchase_year
),
p AS (SELECT '2017-01..2017-08' AS label, * FROM period WHERE purchase_year='2017'
      UNION ALL SELECT '2018-01..2018-08', * FROM period WHERE purchase_year='2018')
SELECT label, orders, customers, ROUND(cash,2) AS cash_collected,
       ROUND(cash/orders,2) AS average_order_value,
       ROUND(cash/customers,2) AS cash_per_customer,
       ROUND(100.0*orders/customers,3) AS orders_per_customer
FROM p;


-- name: r07_quarterly_financials
-- description: Quarterly cash, AOV and refund exposure - the grain a finance team reviews in the monthly pack.
SELECT purchase_quarter,
       COUNT(*)                     AS orders,
       ROUND(SUM(cash_collected),2) AS cash_collected,
       ROUND(SUM(gmv),2)            AS gmv,
       ROUND(SUM(freight_total),2)  AS freight,
       ROUND(SUM(refund_exposure_value),2) AS refund_exposure,
       ROUND(SUM(cash_collected)/COUNT(*),2) AS average_order_value,
       ROUND(100.0*SUM(refund_exposure_value)/SUM(cash_collected),3) AS refund_exposure_pct,
       ROUND(100.0*SUM(freight_total)/SUM(gmv),2) AS freight_ratio_pct
FROM fact_order_financials
WHERE CAST(strftime('%m', purchase_month) AS INTEGER) BETWEEN 1 AND 8
      AND CAST(purchase_year AS INTEGER) IN (2017, 2018)
GROUP BY purchase_quarter
ORDER BY purchase_quarter;


-- name: r08_settlement_float
-- description: Cash collected but not yet released to the seller - the marketplace working-capital position by status.
SELECT order_status,
       COUNT(*)                     AS orders,
       ROUND(SUM(cash_collected),2) AS cash_held,
       ROUND(100.0*SUM(cash_collected)/(SELECT SUM(cash_collected) FROM fact_order_financials),3) AS pct_of_cash_collected
FROM fact_order_financials
WHERE status_class = 'in_flight'
GROUP BY order_status
ORDER BY cash_held DESC;


-- name: r09_customer_economics
-- description: Repeat behaviour and revenue per customer, counted on customer_unique_id to avoid identity fragmentation.
WITH cu AS (
    SELECT customer_unique_id,
           COUNT(DISTINCT order_id) AS orders,
           SUM(cash_collected)       AS cash
    FROM fact_order_financials
    GROUP BY customer_unique_id
)
SELECT COUNT(*)                          AS unique_customers,
       SUM(orders)                       AS orders,
       ROUND(SUM(cash),2)                AS cash_collected,
       SUM(orders > 1)                   AS repeat_customers,
       ROUND(100.0*SUM(orders>1)/COUNT(*),3) AS repeat_customer_rate_pct,
       ROUND(SUM(cash)/COUNT(*),2)       AS cash_per_customer,
       ROUND(SUM(cash)/SUM(orders),2)    AS average_order_value,
       ROUND(AVG(orders),4)              AS orders_per_customer
FROM cu;


-- name: r10_revenue_by_geography
-- description: Cash and customers by customer state - where the revenue base actually sits.
SELECT customer_state,
       COUNT(DISTINCT customer_unique_id) AS unique_customers,
       COUNT(*)                     AS orders,
       ROUND(SUM(cash_collected),2) AS cash_collected,
       ROUND(100.0*SUM(cash_collected)/(SELECT SUM(cash_collected) FROM fact_order_financials),3) AS pct_of_cash,
       ROUND(SUM(cash_collected)/COUNT(DISTINCT customer_unique_id),2) AS cash_per_customer,
       ROUND(SUM(cash_collected)/COUNT(*),2) AS average_order_value,
       ROUND(100.0*SUM(refund_exposure_value)/NULLIF(SUM(cash_collected),0),3) AS refund_exposure_pct
FROM fact_order_financials
GROUP BY customer_state
ORDER BY cash_collected DESC;
