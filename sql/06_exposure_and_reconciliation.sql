-- =====================================================================
-- 06_exposure_and_reconciliation.sql
-- The control file: cash that has been collected but is owed back,
-- cash that cannot be reconciled to any merchandise record, and the
-- transaction-level exception list a finance team would work through.
-- =====================================================================


-- name: x01_refund_exposure_summary
-- description: Cash collected on orders that will never be fulfilled. The source has no refund table, so this is the exposure proxy.
SELECT order_status,
       COUNT(*)                     AS orders,
       ROUND(SUM(cash_collected),2) AS cash_collected,
       ROUND(100.0*SUM(cash_collected)/(SELECT SUM(cash_collected) FROM fact_order_financials),3) AS pct_of_cash_collected,
       SUM(line_item_count = 0)     AS orders_with_no_line_items,
       ROUND(100.0*SUM(line_item_count = 0)/COUNT(*),2) AS pct_without_line_items,
       ROUND(100.0*SUM(refund_exposure_value)/NULLIF(SUM(cash_collected),0),3) AS refund_exposure_pct
FROM fact_order_financials
WHERE status_class IN ('cancelled','unavailable')
GROUP BY order_status
UNION ALL
SELECT 'TOTAL', COUNT(*), ROUND(SUM(cash_collected),2),
       ROUND(100.0*SUM(cash_collected)/(SELECT SUM(cash_collected) FROM fact_order_financials),3),
       SUM(line_item_count = 0),
       ROUND(100.0*SUM(line_item_count = 0)/COUNT(*),2),
       ROUND(100.0*SUM(refund_exposure_value)/NULLIF(SUM(cash_collected),0),3)
FROM fact_order_financials
WHERE status_class IN ('cancelled','unavailable');


-- name: x02_refund_exposure_by_month
-- description: Monthly refund exposure and its rate against cash collected - the volatility a reserve policy has to absorb.
SELECT purchase_month,
       COUNT(*)                     AS orders,
       ROUND(SUM(cash_collected),2) AS cash_collected,
       ROUND(SUM(refund_exposure_value),2) AS refund_exposure,
       ROUND(100.0*SUM(refund_exposure_value)/NULLIF(SUM(cash_collected),0),3) AS refund_exposure_pct
FROM fact_order_financials
WHERE CAST(strftime('%m', purchase_month) AS INTEGER) BETWEEN 1 AND 8
      AND CAST(purchase_year AS INTEGER) IN (2017, 2018)
GROUP BY purchase_month
ORDER BY purchase_month;


-- name: x03_reconciliation_summary
-- description: The cash-to-revenue reconciliation: expected charge, cash collected, and the size of the break.
SELECT COUNT(*)                       AS orders,
       ROUND(SUM(expected_charge),2)  AS expected_charge,
       ROUND(SUM(cash_collected),2)   AS cash_collected,
       ROUND(SUM(cash_collected)-SUM(expected_charge),2) AS net_break,
       ROUND(SUM(ABS(recon_delta)),2) AS gross_break_value,
       SUM(recon_break_flag)          AS orders_in_break,
       ROUND(100.0*SUM(recon_break_flag)/COUNT(*),3) AS break_rate_pct,
       ROUND(100.0*SUM(ABS(recon_delta))/SUM(cash_collected),3) AS gross_break_pct_of_cash
FROM fact_order_financials;


-- name: x04_break_structure
-- description: Why the break happens - missing merchandise versus a price/charge mismatch - split by size band.
SELECT CASE WHEN line_item_count = 0 THEN 'no line items at all' ELSE 'line items present' END AS break_reason,
       CASE WHEN ABS(recon_delta) < 1     THEN 'a. rounding (< R$1)'
            WHEN ABS(recon_delta) < 100   THEN 'b. R$1 - R$100'
            WHEN ABS(recon_delta) < 1000  THEN 'c. R$100 - R$1,000'
            ELSE 'd. R$1,000+' END AS size_band,
       COUNT(*)                       AS orders,
       ROUND(SUM(cash_collected),2)   AS cash_collected,
       ROUND(SUM(ABS(recon_delta)),2) AS absolute_break,
       ROUND(SUM(recon_delta),2)      AS net_break
FROM fact_order_financials
WHERE recon_break_flag = 1
GROUP BY 1, 2
ORDER BY 1, 2;


-- name: x05_material_breaks
-- description: The individual orders behind a break of R$100 or more - the exception list for a finance team.
SELECT order_id,
       order_status,
       ROUND(gmv,2)             AS gmv,
       ROUND(freight_total,2)  AS freight,
       ROUND(expected_charge,2) AS expected_charge,
       ROUND(cash_collected,2)  AS cash_collected,
       ROUND(recon_delta,2)     AS break_amount,
       line_item_count,
       primary_payment_type
FROM fact_order_financials
WHERE ABS(recon_delta) >= 100
ORDER BY ABS(recon_delta) DESC
LIMIT 25;


-- name: x06_break_by_payment_type
-- description: Which payment method is associated with reconciliation breaks.
SELECT COALESCE(primary_payment_type, 'no payment row') AS payment_type,
       COUNT(*)                     AS orders,
       SUM(recon_break_flag)        AS orders_in_break,
       ROUND(100.0*SUM(recon_break_flag)/COUNT(*),3) AS break_rate_pct,
       ROUND(SUM(ABS(recon_delta)),2) AS gross_break_value,
       ROUND(SUM(cash_collected),2)   AS cash_collected
FROM fact_order_financials
GROUP BY COALESCE(primary_payment_type, 'no payment row')
ORDER BY orders_in_break DESC;


-- name: x07_break_by_status
-- description: Whether reconciliation breaks concentrate in the non-fulfilled order states.
SELECT order_status,
       COUNT(*)                     AS orders,
       SUM(recon_break_flag)        AS orders_in_break,
       ROUND(100.0*SUM(recon_break_flag)/COUNT(*),3) AS break_rate_pct,
       ROUND(SUM(ABS(recon_delta)),2) AS gross_break_value,
       ROUND(SUM(cash_collected),2)   AS cash_collected
FROM fact_order_financials
GROUP BY order_status
ORDER BY gross_break_value DESC;


-- name: x08_cash_without_merchandise
-- description: Cash collected on orders for which the dataset holds no line items at all - the control gap behind the reconciliation failure.
SELECT order_status,
       COUNT(*)                     AS orders,
       ROUND(SUM(cash_collected),2) AS cash_collected,
       ROUND(SUM(cash_collected)/(SELECT SUM(cash_collected) FROM fact_order_financials)*100,3) AS pct_of_cash_collected,
       ROUND(AVG(cash_collected),2) AS average_cash_per_order,
       MAX(cash_collected)          AS largest_single_order
FROM fact_order_financials
WHERE line_item_count = 0 AND cash_collected > 0
GROUP BY order_status
UNION ALL
SELECT 'TOTAL', COUNT(*), ROUND(SUM(cash_collected),2),
       ROUND(SUM(cash_collected)/(SELECT SUM(cash_collected) FROM fact_order_financials)*100,3),
       ROUND(AVG(cash_collected),2), MAX(cash_collected)
FROM fact_order_financials
WHERE line_item_count = 0 AND cash_collected > 0;


-- name: x09_anomaly_screen
-- description: Transaction-level anomaly screen - concentration, outliers and structural exceptions, with the value attached to each.
SELECT 'payments above the 99th percentile' AS anomaly, COUNT(*) AS records,
       ROUND(SUM(payment_value),2) AS value_at_stake, ROUND(MAX(payment_value),2) AS worst_case
FROM payments
WHERE payment_value > (SELECT payment_value FROM payments ORDER BY payment_value
                        LIMIT 1 OFFSET (SELECT CAST(COUNT(*)*0.99 AS INTEGER)-1 FROM payments))
UNION ALL
SELECT 'payments in the top 0.1% by value', COUNT(*), ROUND(SUM(payment_value),2), ROUND(MAX(payment_value),2)
FROM payments WHERE payment_value > 3000
UNION ALL
SELECT 'line items where freight exceeds merchandise value', COUNT(*), ROUND(SUM(freight_value),2), ROUND(MAX(freight_value),2)
FROM order_items WHERE freight_value > price
UNION ALL
SELECT 'orders with no line items but cash collected', COUNT(*), ROUND(SUM(cash_collected),2), ROUND(MAX(cash_collected),2)
FROM fact_order_financials WHERE line_item_count = 0 AND cash_collected > 0
UNION ALL
SELECT 'orders in flight holding cash (settlement float)', COUNT(*), ROUND(SUM(cash_collected),2), ROUND(MAX(cash_collected),2)
FROM fact_order_financials WHERE status_class = 'in_flight'
UNION ALL
SELECT 'orders with more than one payment row (split payment)', COUNT(*), ROUND(SUM(cash_collected),2), ROUND(MAX(cash_collected),2)
FROM fact_order_financials WHERE payment_count > 1;


-- name: x10_split_payment_orders
-- description: Orders settled in more than one payment - where a partial capture or a second method was used.
SELECT payment_count AS payments_on_the_order,
       COUNT(*)                     AS orders,
       ROUND(SUM(cash_collected),2) AS cash_collected,
       ROUND(AVG(cash_collected),2) AS average_order_value
FROM fact_order_financials
WHERE payment_count > 1
GROUP BY payment_count
ORDER BY payment_count;


-- name: x11_kpi_scorecard
-- description: The twelve headline KPIs computed independently in SQL, for reconciliation against the Python implementation and the Power BI model.
SELECT 'KPI 01 GMV (merchandise value)' AS kpi,
       ROUND((SELECT SUM(gmv) FROM fact_order_financials),2) AS value, 'BRL' AS unit
UNION ALL SELECT 'KPI 02 Cash collected',
       ROUND((SELECT SUM(cash_collected) FROM fact_order_financials),2), 'BRL'
UNION ALL SELECT 'KPI 03 Refund exposure',
       ROUND((SELECT SUM(refund_exposure_value) FROM fact_order_financials),2), 'BRL'
UNION ALL SELECT 'KPI 04 Net revenue',
       ROUND((SELECT SUM(net_revenue) FROM fact_order_financials),2), 'BRL'
UNION ALL SELECT 'KPI 05 Average order value',
       ROUND((SELECT SUM(cash_collected)/COUNT(*) FROM fact_order_financials),2), 'BRL'
UNION ALL SELECT 'KPI 06 Freight ratio',
       ROUND((SELECT 100.0*SUM(freight_total)/SUM(gmv) FROM fact_order_financials),2), 'pct of GMV'
UNION ALL SELECT 'KPI 07 Reconciliation break rate',
       ROUND((SELECT 100.0*SUM(recon_break_flag)/COUNT(*) FROM fact_order_financials),3), 'pct of orders'
UNION ALL SELECT 'KPI 08 Value-weighted instalment depth',
       ROUND((SELECT SUM(payment_installments*payment_value)/SUM(payment_value) FROM payments WHERE payment_type='credit_card'),3), 'instalments'
UNION ALL SELECT 'KPI 09 Disputed value at risk',
       ROUND((SELECT SUM(CASE WHEN disputed_flag=1 THEN cash_collected ELSE 0 END) FROM fact_order_financials),2), 'BRL'
UNION ALL SELECT 'KPI 10 Seller HHI',
       ROUND((SELECT SUM(g*g)/((SELECT SUM(seller_gmv) FROM v_seller_performance)*(SELECT SUM(seller_gmv) FROM v_seller_performance)) FROM (SELECT seller_gmv AS g FROM v_seller_performance)),5), 'index'
UNION ALL SELECT 'KPI 11 Settlement float',
       ROUND((SELECT SUM(settlement_float_value) FROM fact_order_financials),2), 'BRL'
UNION ALL SELECT 'KPI 12 Repeat customer rate',
       ROUND((SELECT 100.0*COUNT(*)/(SELECT COUNT(DISTINCT customer_unique_id) FROM fact_order_financials)
              FROM (SELECT customer_unique_id FROM fact_order_financials GROUP BY customer_unique_id HAVING COUNT(*)>1)),3), 'pct of customers';
