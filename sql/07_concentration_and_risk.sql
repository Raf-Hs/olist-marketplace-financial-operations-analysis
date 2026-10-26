-- =====================================================================
-- 07_concentration_and_risk.sql
-- Counterparty concentration, logistics cost-to-serve, and the
-- dispute-risk relationship between payment behaviour and review score.
-- =====================================================================


-- name: c01_seller_concentration
-- description: Seller concentration - HHI and the top-N GMV shares, which together describe counterparty dependency.
WITH s AS (SELECT seller_id, SUM(price) AS gmv FROM order_items GROUP BY seller_id),
     ranked AS (SELECT seller_id, gmv, RANK() OVER (ORDER BY gmv DESC) AS rnk FROM s),
     t AS (SELECT SUM(gmv) AS total FROM s)
SELECT COUNT(*) AS sellers,
       ROUND(SUM(r.gmv),2) AS total_gmv,
       ROUND(100.0*SUM(CASE WHEN r.rnk=1 THEN r.gmv ELSE 0 END)/t.total,3) AS top1_seller_pct,
       ROUND(100.0*SUM(CASE WHEN r.rnk<=10 THEN r.gmv ELSE 0 END)/t.total,3) AS top10_sellers_pct,
       ROUND(100.0*SUM(CASE WHEN r.rnk<=100 THEN r.gmv ELSE 0 END)/t.total,3) AS top100_sellers_pct,
       ROUND(100.0*SUM(CASE WHEN r.rnk<=1000 THEN r.gmv ELSE 0 END)/t.total,3) AS top1000_sellers_pct,
       ROUND(SUM(r.gmv*r.gmv)/(t.total*t.total),5) AS hhi_index,
       (SELECT COUNT(*) FROM s, t WHERE s.gmv > 0.01*t.total) AS sellers_above_1pct,
       (SELECT COUNT(*) FROM s, t WHERE s.gmv > 0.005*t.total) AS sellers_above_half_1pct
FROM ranked r, t;


-- name: c02_top_sellers
-- description: The largest sellers by GMV, with their freight burden.
SELECT seller_id, seller_state, order_count, line_item_count,
       ROUND(seller_gmv,2) AS seller_gmv,
       ROUND(seller_freight,2) AS seller_freight,
       freight_ratio_pct, avg_order_value, product_count,
       ROUND(100.0*seller_gmv/(SELECT SUM(seller_gmv) FROM v_seller_performance),3) AS pct_of_total_gmv
FROM v_seller_performance
ORDER BY seller_gmv DESC
LIMIT 20;


-- name: c03_seller_geography
-- description: Where the supply sits and what it costs to ship it - a regional rather than a counterparty concentration.
SELECT seller_state,
       COUNT(*) AS sellers,
       ROUND(SUM(seller_gmv),2) AS gmv,
       ROUND(100.0*SUM(seller_gmv)/(SELECT SUM(seller_gmv) FROM v_seller_performance),3) AS pct_of_gmv,
       ROUND(SUM(seller_freight),2) AS freight,
       ROUND(100.0*SUM(seller_freight)/SUM(seller_gmv),2) AS freight_ratio_pct
FROM v_seller_performance
GROUP BY seller_state
ORDER BY gmv DESC;


-- name: c04_category_logistics
-- description: Freight burden by product category - where logistics eats the most of the merchandise value.
SELECT category_english, order_count, line_item_count,
       ROUND(category_gmv,2) AS gmv,
       ROUND(category_freight,2) AS freight,
       freight_ratio_pct, avg_item_price,
       ROUND(100.0*category_gmv/(SELECT SUM(category_gmv) FROM v_category_financials),3) AS pct_of_gmv
FROM v_category_financials
ORDER BY gmv DESC;


-- name: c05_freight_extremes
-- description: The categories with the heaviest freight burden, and how much value is exposed at each extreme.
SELECT 'worst freight burden' AS side, category_english,
       ROUND(category_gmv,2) AS gmv, freight_ratio_pct, line_item_count
FROM (SELECT * FROM v_category_financials WHERE category_gmv > 0 ORDER BY freight_ratio_pct DESC LIMIT 10)
UNION ALL
SELECT 'best freight burden', category_english,
       ROUND(category_gmv,2), freight_ratio_pct, line_item_count
FROM (SELECT * FROM v_category_financials WHERE category_gmv > 0 ORDER BY freight_ratio_pct ASC LIMIT 10);


-- name: c06_freight_intensity_vs_value
-- description: Does shipping cost more than the goods on a material share of the catalogue, and what is it worth.
SELECT
    COUNT(*) AS line_items,
    SUM(CASE WHEN freight_value > price THEN 1 ELSE 0 END) AS items_freight_exceeds_price,
    ROUND(100.0*SUM(CASE WHEN freight_value > price THEN 1 ELSE 0 END)/COUNT(*),2) AS pct_items_freight_exceeds_price,
    ROUND(SUM(CASE WHEN freight_value > price THEN price ELSE 0 END),2) AS merchandise_value_on_those_items,
    ROUND(SUM(CASE WHEN freight_value > price THEN freight_value ELSE 0 END),2) AS freight_collected_on_those_items,
    ROUND(SUM(CASE WHEN freight_value > price THEN freight_value - price ELSE 0 END),2) AS freight_over_merchandise_value,
    ROUND(SUM(freight_value),2) AS total_freight,
    ROUND(100.0*SUM(freight_value)/SUM(price),2) AS portfolio_freight_ratio_pct
FROM order_items;


-- name: c07_dispute_rate_by_instalments
-- description: Dispute rate by instalment depth - the credit-risk signal in the payment mix.
SELECT CASE WHEN max_installments <= 1 THEN '1 (paid in full)'
            WHEN max_installments <= 3 THEN '2 - 3'
            WHEN max_installments <= 6 THEN '4 - 6'
            WHEN max_installments <= 12 THEN '7 - 12'
            ELSE '13 +' END AS instalment_bucket,
       COUNT(*)                        AS orders,
       ROUND(SUM(cash_collected),2)    AS cash_collected,
       ROUND(AVG(cash_collected),2)    AS average_order_value,
       SUM(disputed_flag)              AS disputed_orders,
       ROUND(100.0*SUM(disputed_flag)/COUNT(*),3) AS dispute_rate_pct,
       ROUND(SUM(CASE WHEN disputed_flag=1 THEN cash_collected ELSE 0 END),2) AS disputed_value,
       ROUND(100.0*SUM(CASE WHEN disputed_flag=1 THEN cash_collected ELSE 0 END)/SUM(cash_collected),3) AS pct_of_value_disputed
FROM fact_order_financials
WHERE primary_payment_type = 'credit_card'
GROUP BY CASE WHEN max_installments <= 1 THEN '1 (paid in full)'
              WHEN max_installments <= 3 THEN '2 - 3'
              WHEN max_installments <= 6 THEN '4 - 6'
              WHEN max_installments <= 12 THEN '7 - 12'
              ELSE '13 +' END
ORDER BY CASE WHEN max_installments <= 1 THEN 1 WHEN max_installments <= 3 THEN 2
              WHEN max_installments <= 6 THEN 3 WHEN max_installments <= 12 THEN 4 ELSE 5 END;


-- name: c08_dispute_value_at_risk
-- description: The cash sitting behind orders that were rated 1 or 2 out of 5 - the disputed value at risk.
SELECT worst_review_score,
       COUNT(*)                     AS orders,
       ROUND(SUM(cash_collected),2) AS cash_collected,
       ROUND(100.0*SUM(cash_collected)/(SELECT SUM(cash_collected) FROM fact_order_financials WHERE worst_review_score IS NOT NULL),3) AS pct_of_reviewed_value
FROM fact_order_financials
WHERE worst_review_score IS NOT NULL
GROUP BY worst_review_score
ORDER BY worst_review_score;


-- name: c09_dispute_rate_by_method
-- description: Dispute rate by payment method - comparing the promotional and credit channels with the others.
SELECT COALESCE(primary_payment_type,'no payment row') AS payment_type,
       COUNT(*)                        AS orders,
       ROUND(SUM(cash_collected),2)    AS cash_collected,
       SUM(disputed_flag)              AS disputed_orders,
       ROUND(100.0*SUM(disputed_flag)/COUNT(*),3) AS dispute_rate_pct,
       ROUND(SUM(CASE WHEN disputed_flag=1 THEN cash_collected ELSE 0 END),2) AS disputed_value,
       ROUND(100.0*SUM(CASE WHEN disputed_flag=1 THEN cash_collected ELSE 0 END)
             /SUM(cash_collected),3) AS pct_of_value_disputed
FROM fact_order_financials
GROUP BY COALESCE(primary_payment_type,'no payment row')
ORDER BY disputed_value DESC;


-- name: c10_fulfilment_performance
-- description: Cycle time and promise-keeping - the service level the refunds are attached to.
SELECT order_status,
       COUNT(*)                              AS orders,
       ROUND(AVG(delivery_days),2)           AS avg_delivery_days,
       ROUND(AVG(days_late_vs_promise),2)    AS avg_days_vs_promise,
       SUM(days_late_vs_promise > 0)         AS delivered_late,
       ROUND(100.0*SUM(days_late_vs_promise > 0)/COUNT(*),3) AS pct_delivered_late,
       ROUND(AVG(line_item_count),3)         AS avg_line_items,
       ROUND(AVG(cash_collected),2)          AS average_order_value
FROM fact_order_financials
WHERE status_class = 'fulfilled'
GROUP BY order_status;


-- name: c11_sla_vs_dispute
-- description: Whether late delivery is associated with a higher dispute rate.
SELECT CASE WHEN days_late_vs_promise IS NULL THEN 'not delivered'
            WHEN days_late_vs_promise <= 0    THEN 'on time or early'
            WHEN days_late_vs_promise <= 5   THEN '1 - 5 days late'
            WHEN days_late_vs_promise <= 15  THEN '6 - 15 days late'
            ELSE 'more than 15 days late' END AS delivery_band,
       COUNT(*)                     AS orders,
       ROUND(SUM(cash_collected),2) AS cash_collected,
       SUM(disputed_flag)           AS disputed_orders,
       ROUND(100.0*SUM(disputed_flag)/COUNT(*),3) AS dispute_rate_pct,
       ROUND(SUM(CASE WHEN disputed_flag=1 THEN cash_collected ELSE 0 END),2) AS disputed_value
FROM fact_order_financials
WHERE status_class = 'fulfilled'
GROUP BY CASE WHEN days_late_vs_promise IS NULL THEN 'not delivered'
              WHEN days_late_vs_promise <= 0    THEN 'on time or early'
              WHEN days_late_vs_promise <= 5   THEN '1 - 5 days late'
              WHEN days_late_vs_promise <= 15  THEN '6 - 15 days late'
              ELSE 'more than 15 days late' END
ORDER BY MIN(days_late_vs_promise);
