-- =====================================================================
-- 03_data_quality.sql
-- Data-quality and control checks executed against the loaded warehouse.
-- Every check returns a row even when it finds nothing, so a clean check
-- is still visible in the audit trail.
--
-- src/run_queries.py parses the `-- name:` / `-- description:` headers
-- and renders reports/data_quality.md from the output.
-- =====================================================================


-- name: dq01_record_counts
-- description: Row counts per source table - the first reconciliation against the published dataset shape.
SELECT 'customers' AS table_name, COUNT(*) AS row_count FROM customers
UNION ALL SELECT 'orders',                    COUNT(*) FROM orders
UNION ALL SELECT 'order_items',               COUNT(*) FROM order_items
UNION ALL SELECT 'payments',                  COUNT(*) FROM payments
UNION ALL SELECT 'reviews',                   COUNT(*) FROM reviews
UNION ALL SELECT 'products',                  COUNT(*) FROM products
UNION ALL SELECT 'sellers',                   COUNT(*) FROM sellers
UNION ALL SELECT 'product_category_translation', COUNT(*) FROM product_category_translation;


-- name: dq02_key_uniqueness
-- description: Duplicate primary keys on every source table. All must be zero.
SELECT 'orders.order_id' AS key_name, COUNT(*) - COUNT(DISTINCT order_id) AS duplicates FROM orders
UNION ALL SELECT 'customers.customer_id', COUNT(*) - COUNT(DISTINCT customer_id) FROM customers
UNION ALL SELECT 'order_items(order_id,order_item_id)', COUNT(*) - COUNT(DISTINCT order_id || '|' || order_item_id) FROM order_items
UNION ALL SELECT 'payments(order_id,payment_sequential)', COUNT(*) - COUNT(DISTINCT order_id || '|' || payment_sequential) FROM payments
UNION ALL SELECT 'reviews.review_id', COUNT(*) - COUNT(DISTINCT review_id) FROM reviews
UNION ALL SELECT 'products.product_id', COUNT(*) - COUNT(DISTINCT product_id) FROM products
UNION ALL SELECT 'sellers.seller_id', COUNT(*) - COUNT(DISTINCT seller_id) FROM sellers;


-- name: dq03_referential_integrity
-- description: Orphan rows on every declared foreign key. All must be zero.
SELECT 'order_items -> orders' AS relationship, COUNT(*) AS orphan_rows
  FROM order_items i LEFT JOIN orders o ON o.order_id = i.order_id WHERE o.order_id IS NULL
UNION ALL SELECT 'order_items -> products', COUNT(*)
  FROM order_items i LEFT JOIN products p ON p.product_id = i.product_id WHERE p.product_id IS NULL
UNION ALL SELECT 'order_items -> sellers', COUNT(*)
  FROM order_items i LEFT JOIN sellers s ON s.seller_id = i.seller_id WHERE s.seller_id IS NULL
UNION ALL SELECT 'payments -> orders', COUNT(*)
  FROM payments p LEFT JOIN orders o ON o.order_id = p.order_id WHERE o.order_id IS NULL
UNION ALL SELECT 'reviews -> orders', COUNT(*)
  FROM reviews r LEFT JOIN orders o ON o.order_id = r.order_id WHERE o.order_id IS NULL
UNION ALL SELECT 'orders -> customers', COUNT(*)
  FROM orders o LEFT JOIN customers c ON c.customer_id = o.customer_id WHERE c.customer_id IS NULL;


-- name: dq04_null_profile
-- description: Null counts and null rates for every column used in a financial calculation.
SELECT 'orders.order_purchase_timestamp' AS column_name, COUNT(*) AS rows, SUM(order_purchase_timestamp IS NULL) AS nulls,
       ROUND(100.0*SUM(order_purchase_timestamp IS NULL)/COUNT(*),3) AS null_pct FROM orders
UNION ALL SELECT 'orders.order_approved_at', COUNT(*), SUM(order_approved_at IS NULL), ROUND(100.0*SUM(order_approved_at IS NULL)/COUNT(*),3) FROM orders
UNION ALL SELECT 'orders.order_delivered_customer_date', COUNT(*), SUM(order_delivered_customer_date IS NULL), ROUND(100.0*SUM(order_delivered_customer_date IS NULL)/COUNT(*),3) FROM orders
UNION ALL SELECT 'orders.order_estimated_delivery_date', COUNT(*), SUM(order_estimated_delivery_date IS NULL), ROUND(100.0*SUM(order_estimated_delivery_date IS NULL)/COUNT(*),3) FROM orders
UNION ALL SELECT 'payments.payment_installments', COUNT(*), SUM(payment_installments IS NULL), ROUND(100.0*SUM(payment_installments IS NULL)/COUNT(*),3) FROM payments
UNION ALL SELECT 'payments.payment_type', COUNT(*), SUM(payment_type IS NULL), ROUND(100.0*SUM(payment_type IS NULL)/COUNT(*),3) FROM payments
UNION ALL SELECT 'payments.payment_value', COUNT(*), SUM(payment_value IS NULL), ROUND(100.0*SUM(payment_value IS NULL)/COUNT(*),3) FROM payments
UNION ALL SELECT 'order_items.price', COUNT(*), SUM(price IS NULL), ROUND(100.0*SUM(price IS NULL)/COUNT(*),3) FROM order_items
UNION ALL SELECT 'order_items.freight_value', COUNT(*), SUM(freight_value IS NULL), ROUND(100.0*SUM(freight_value IS NULL)/COUNT(*),3) FROM order_items
UNION ALL SELECT 'order_items.seller_id', COUNT(*), SUM(seller_id IS NULL), ROUND(100.0*SUM(seller_id IS NULL)/COUNT(*),3) FROM order_items
UNION ALL SELECT 'products.product_category_name', COUNT(*), SUM(product_category_name IS NULL), ROUND(100.0*SUM(product_category_name IS NULL)/COUNT(*),3) FROM products
UNION ALL SELECT 'reviews.review_score', COUNT(*), SUM(review_score IS NULL), ROUND(100.0*SUM(review_score IS NULL)/COUNT(*),3) FROM reviews;


-- name: dq05_missing_order_content
-- description: Orders that carry no line items - the structural break behind the cash-to-revenue reconciliation failure.
SELECT o.order_status,
       COUNT(*)                        AS orders,
       ROUND(SUM(p.payment_value),2)   AS cash_collected,
       ROUND(SUM(p.payment_value)*100.0/(SELECT SUM(payment_value) FROM payments),3) AS pct_of_cash_collected
FROM orders o
JOIN payments p ON p.order_id = o.order_id
WHERE NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id = o.order_id)
GROUP BY o.order_status
ORDER BY cash_collected DESC;


-- name: dq06_amount_validity
-- description: Zero, negative and extreme monetary values across payments and line items.
SELECT 'payments with zero value' AS check_name, COUNT(*) AS rows,
       ROUND(SUM(payment_value),2) AS value_at_stake FROM payments WHERE payment_value = 0
UNION ALL SELECT 'payments with negative value', COUNT(*), ROUND(SUM(payment_value),2) FROM payments WHERE payment_value < 0
UNION ALL SELECT 'payments above R$ 3,000 (99.8th pct)', COUNT(*), ROUND(SUM(payment_value),2) FROM payments WHERE payment_value > 3000
UNION ALL SELECT 'line items priced at zero', COUNT(*), ROUND(SUM(price),2) FROM order_items WHERE price = 0
UNION ALL SELECT 'line items with freight above merchandise value', COUNT(*), ROUND(SUM(freight_value),2) FROM order_items WHERE freight_value > price
UNION ALL SELECT 'line items above R$ 3,000', COUNT(*), ROUND(SUM(price),2) FROM order_items WHERE price > 3000;


-- name: dq07_temporal_integrity
-- description: Orders whose event dates are internally inconsistent, plus coverage of each timestamp.
SELECT 'delivered before purchase' AS check_name, COUNT(*) AS rows FROM orders
  WHERE order_delivered_customer_date IS NOT NULL
    AND julianday(order_delivered_customer_date) < julianday(order_purchase_timestamp)
UNION ALL SELECT 'approved before purchase', COUNT(*) FROM orders
  WHERE order_approved_at IS NOT NULL
    AND julianday(order_approved_at) < julianday(order_purchase_timestamp)
UNION ALL SELECT 'delivered to customer before handed to carrier', COUNT(*) FROM orders
  WHERE order_delivered_customer_date IS NOT NULL AND order_delivered_carrier_date IS NOT NULL
    AND julianday(order_delivered_customer_date) < julianday(order_delivered_carrier_date)
UNION ALL SELECT 'orders missing purchase timestamp', COUNT(*) FROM orders WHERE order_purchase_timestamp IS NULL
UNION ALL SELECT 'orders missing approval timestamp', COUNT(*) FROM orders WHERE order_approved_at IS NULL
UNION ALL SELECT 'orders missing estimated delivery date', COUNT(*) FROM orders WHERE order_estimated_delivery_date IS NULL;


-- name: dq08_customer_identity_fragmentation
-- description: Repeat buyers split across several customer_id values. Counting customers on customer_id overstates the base.
SELECT n_ids AS customer_ids_for_one_person, COUNT(*) AS real_customers
FROM (SELECT customer_unique_id, COUNT(DISTINCT customer_id) AS n_ids FROM customers GROUP BY customer_unique_id)
GROUP BY n_ids ORDER BY n_ids;


-- name: dq09_unmapped_categories
-- description: Products whose category has no English translation - the only English label source.
SELECT p.product_category_name,
       COUNT(DISTINCT p.product_id) AS products,
       COUNT(i.order_item_id)        AS line_items,
       ROUND(SUM(i.price),2)          AS gmv
FROM products p
LEFT JOIN product_category_translation t ON t.product_category_name = p.product_category_name
LEFT JOIN order_items i ON i.product_id = p.product_id
WHERE p.product_category_name IS NOT NULL AND t.product_category_name IS NULL
GROUP BY p.product_category_name
ORDER BY gmv DESC;


-- name: dq10_duplicate_reviews
-- description: Orders with more than one review row - the review table is not one-per-order and must be aggregated.
SELECT review_count, COUNT(*) AS orders, ROUND(SUM(cash),2) AS cash_collected
FROM (
  SELECT r.order_id, COUNT(*) AS review_count, SUM(f.cash_collected) AS cash
  FROM reviews r JOIN fact_order_financials f ON f.order_id = r.order_id
  GROUP BY r.order_id
)
GROUP BY review_count ORDER BY review_count;


-- name: dq11_partial_month_coverage
-- description: Order volume by calendar month. The first and last months are partial and must not be used for period-on-period comparison.
SELECT purchase_month,
       COUNT(*)                     AS orders,
       ROUND(SUM(cash_collected),2) AS cash_collected,
       CASE WHEN COUNT(*) < 100 THEN 'PARTIAL - exclude from trend analysis' ELSE 'full month' END AS coverage_flag
FROM fact_order_financials
GROUP BY purchase_month
ORDER BY purchase_month;


-- name: dq12_cleaning_rule_audit
-- description: Every cleaning and validation rule applied during the load, with the number of records it touched.
SELECT rule_id, rule_code, table_name, rule_type, records_affected, rule_description, action_taken
FROM dq_cleaning_rules
ORDER BY rule_id;


-- name: dq13_fact_table_reconciliation
-- description: The materialised order-level fact must agree row-for-row with its defining view. Any non-zero value is a build defect.
SELECT
    (SELECT COUNT(*) FROM fact_order_financials) - (SELECT COUNT(*) FROM v_order_financials) AS row_count_difference,
    (SELECT COUNT(*) FROM fact_order_financials f JOIN v_order_financials v USING (order_id)
      WHERE ABS(f.cash_collected - v.cash_collected) > 0.005
         OR ABS(f.gmv - v.gmv) > 0.005
         OR f.status_class <> v.status_class
         OR f.recon_break_flag <> v.recon_break_flag) AS rows_with_a_measure_mismatch,
    ROUND((SELECT SUM(cash_collected) FROM fact_order_financials) - (SELECT SUM(cash_collected) FROM v_order_financials), 2) AS cash_total_difference,
    ROUND((SELECT SUM(gmv) FROM fact_order_financials) - (SELECT SUM(gmv) FROM v_order_financials), 2) AS gmv_total_difference;
