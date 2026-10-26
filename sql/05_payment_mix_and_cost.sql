-- =====================================================================
-- 05_payment_mix_and_cost.sql
-- Payment behaviour, consumer-credit exposure and a MODELLLED
-- cost-to-serve.
--
-- !! MODELLED OUTPUT - READ THE ASSUMPTIONS !!
-- The market rates below are published Brazilian acquiring benchmarks, not
-- facts about this marketplace. They are held in src/config.py
-- (PAYMENT_COST_MODEL and INSTALLMENT_FUNDING_RATE) and a unit test
-- asserts that this file and config.py agree, so the assumption can never
-- drift silently. Every figure produced from them is labelled "modelled"
-- in the reports and carries a sensitivity band.
-- =====================================================================


-- name: p01_payment_method_mix
-- description: Cash, order count, share of collection and instalment depth by payment method.
SELECT payment_type,
       COUNT(*)                     AS payment_rows,
       COUNT(DISTINCT order_id)     AS orders,
       ROUND(SUM(payment_value),2)  AS gross_value,
       ROUND(100.0*SUM(payment_value)/(SELECT SUM(payment_value) FROM payments),3) AS pct_of_value,
       ROUND(AVG(payment_value),2)  AS average_payment_value,
       ROUND(AVG(payment_installments),3) AS average_installments,
       MAX(payment_installments)    AS max_installments,
       SUM(payment_installments)     AS installment_months,
       SUM(payment_value = 0)        AS zero_value_rows
FROM payments
GROUP BY payment_type
ORDER BY gross_value DESC;


-- name: p02_payment_mix_at_order_level
-- description: Dominant payment method per order, with value share and average order value.
SELECT primary_payment_type,
       COUNT(*)                     AS orders,
       ROUND(SUM(cash_collected),2) AS cash_collected,
       ROUND(100.0*SUM(cash_collected)/(SELECT SUM(cash_collected) FROM fact_order_financials),3) AS pct_of_cash,
       ROUND(AVG(cash_collected),2) AS average_order_value,
       ROUND(AVG(max_installments),3) AS average_installments,
       ROUND(100.0*SUM(max_installments),0) AS installment_months
FROM fact_order_financials
GROUP BY primary_payment_type
ORDER BY cash_collected DESC;


-- name: p03_installment_profile
-- description: Card payments by instalment count - the shape of the consumer-credit book.
SELECT payment_installments,
       COUNT(*)                    AS payment_rows,
       ROUND(SUM(payment_value),2) AS value,
       ROUND(100.0*SUM(payment_value)/(SELECT SUM(payment_value) FROM payments WHERE payment_type='credit_card'),3) AS pct_of_card_value,
       ROUND(AVG(payment_value),2) AS average_payment_value
FROM payments
WHERE payment_type = 'credit_card'
GROUP BY payment_installments
ORDER BY payment_installments;


-- name: p04_installment_exposure
-- description: How much card value is settled on an instalment plan and the weighted average depth.
SELECT
    ROUND(SUM(payment_value),2) AS card_value,
    ROUND(SUM(CASE WHEN COALESCE(payment_installments,1) > 1 THEN payment_value ELSE 0 END),2) AS value_on_installment_plans,
    ROUND(100.0*SUM(CASE WHEN COALESCE(payment_installments,1) > 1 THEN payment_value ELSE 0 END)/SUM(payment_value),3) AS pct_of_card_value_on_installments,
    COUNT(DISTINCT CASE WHEN COALESCE(payment_installments,1) > 1 THEN order_id END) AS orders_with_installments,
    ROUND(SUM(payment_installments*payment_value)/SUM(payment_value),3) AS value_weighted_average_installments,
    ROUND(AVG(payment_installments),3) AS simple_average_installments
FROM payments
WHERE payment_type = 'credit_card';


-- name: p05_modelled_cost_to_serve
-- description: MODELLED payment cost-to-serve by method - acquiring fee, per-transaction fee and instalment funding premium.
WITH params(payment_type, pct_rate, fixed_fee) AS (
    VALUES ('credit_card', 0.029, 0.00),
           ('debit_card', 0.015, 1.50),
           ('boleto',       0.000, 3.00),
           ('voucher',      0.000, 0.00),
           ('not_defined',  0.000, 0.00)
),
funding(rate) AS (VALUES (0.0199)),
pay AS (
    SELECT p.payment_type,
           p.payment_value,
           COALESCE(p.payment_installments, 1) AS installments,
           pa.pct_rate,
           pa.fixed_fee,
           f.rate AS funding_rate
    FROM payments p
    JOIN params pa ON pa.payment_type = p.payment_type
    CROSS JOIN funding f
)
SELECT payment_type,
       COUNT(*)                    AS payment_rows,
       ROUND(SUM(payment_value),2) AS gross_value,
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
ORDER BY gross_value DESC;


-- name: p06_cost_to_serve_sensitivity
-- description: MODELLED - how the instalment funding cost changes across the published market rate band (1.00% / 1.99% / 2.99% per instalment).
WITH rates(rate) AS (VALUES (0.0100), (0.0199), (0.0299)),
card AS (SELECT payment_value, COALESCE(payment_installments,1) AS inst FROM payments WHERE payment_type='credit_card')
SELECT r.rate AS funding_rate_per_installment,
       ROUND(SUM(c.payment_value * r.rate * (c.inst - 1)),2) AS modelled_installment_funding_cost,
       ROUND(100.0*SUM(c.payment_value * r.rate * (c.inst - 1))
             /(SELECT SUM(payment_value) FROM payments WHERE payment_type='credit_card'),3) AS pct_of_card_value,
       ROUND(SUM(c.payment_value * r.rate * (c.inst - 1))
             - SUM(c.payment_value * 0.0199 * (c.inst - 1)),2) AS delta_vs_base_case
FROM rates r CROSS JOIN card c
GROUP BY r.rate
ORDER BY r.rate;


-- name: p07_cost_to_serve_total
-- description: MODELLED - total cost-to-serve and the resulting contribution, with the promotional credit shown separately.
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
    FROM payments p JOIN params pa ON pa.payment_type = p.payment_type CROSS JOIN funding f
),
costs AS (
    SELECT
        ROUND(SUM(payment_value),2) AS gross_value,
        ROUND(SUM(payment_value*pct_rate + fixed_fee),2) AS acquiring_cost,
        ROUND(SUM(CASE WHEN payment_type='credit_card'
                       THEN payment_value*funding_rate*(installments-1) ELSE 0 END),2) AS installment_funding_cost,
        ROUND(SUM(CASE WHEN payment_type='voucher' THEN payment_value ELSE 0 END),2) AS voucher_promo_credit,
        ROUND(SUM(payment_value*pct_rate + fixed_fee
                  + CASE WHEN payment_type='credit_card'
                         THEN payment_value*funding_rate*(installments-1) ELSE 0 END),2) AS total_modelled_payment_cost
    FROM pay
),
net AS (SELECT SUM(net_revenue) AS net_revenue FROM fact_order_financials)
SELECT c.gross_value,
       (SELECT net_revenue FROM net) AS net_revenue,
       c.acquiring_cost,
       c.installment_funding_cost,
       c.total_modelled_payment_cost,
       c.voucher_promo_credit,
       ROUND((SELECT net_revenue FROM net) - c.total_modelled_payment_cost,2) AS contribution_after_payment_cost,
       ROUND(100.0*((SELECT net_revenue FROM net) - c.total_modelled_payment_cost)
             /(SELECT net_revenue FROM net),2) AS contribution_margin_pct,
       ROUND(100.0*c.installment_funding_cost/((SELECT net_revenue FROM net)),3) AS installment_funding_pct_of_net_revenue,
       ROUND(100.0*c.voucher_promo_credit/((SELECT net_revenue FROM net)),3) AS voucher_promo_pct_of_net_revenue
FROM costs c;


-- name: p08_method_shift_scenario
-- description: MODELLED - what a shift of card volume to boleto would save, at the modelled per-order costs. Not a measured saving.
WITH card AS (
    SELECT COUNT(*) AS orders, SUM(cash_collected) AS value
    FROM fact_order_financials WHERE primary_payment_type='credit_card'
),
avg_card_cost AS (
    SELECT AVG(payment_value*0.029 + payment_value*0.0199*(COALESCE(payment_installments,1)-1)) AS per_order_cost
    FROM payments WHERE payment_type='credit_card'
),
shift(shift_pct) AS (VALUES (0.05), (0.10), (0.20))
SELECT s.shift_pct AS card_volume_shifted_to_boleto,
       c.orders     AS card_orders,
       ROUND(c.orders * s.shift_pct,0) AS orders_moved,
       ROUND(a.per_order_cost,2) AS modelled_cost_per_card_order,
       ROUND(3.00,2) AS modelled_cost_per_boleto_order,
       ROUND(a.per_order_cost - 3.00,2) AS saving_per_order,
       ROUND(c.orders * s.shift_pct * (a.per_order_cost - 3.00),2) AS modelled_annual_saving,
       ROUND(100.0*c.orders * s.shift_pct * (a.per_order_cost - 3.00)
             /(SELECT SUM(net_revenue) FROM fact_order_financials),3) AS pct_of_net_revenue
FROM shift s CROSS JOIN card c CROSS JOIN avg_card_cost a
ORDER BY s.shift_pct;


-- name: p09_voucher_promotional_credit
-- description: Marketplace-funded voucher credit - revenue that is never collected, and the profile of the orders it lands on.
SELECT COUNT(DISTINCT p.order_id)  AS orders_receiving_voucher,
       COUNT(*)                     AS voucher_payment_rows,
       ROUND(SUM(p.payment_value),2)  AS voucher_value,
       ROUND(100.0*SUM(p.payment_value)/(SELECT SUM(payment_value) FROM payments),3) AS pct_of_total_value,
       ROUND(AVG(p.payment_value),2)  AS average_voucher_payment,
       ROUND(100.0*SUM(CASE WHEN f.cash_collected > 0 THEN 1 ELSE 0 END)/COUNT(*),2) AS pct_orders_also_paying_by_card
FROM payments p
JOIN fact_order_financials f ON f.order_id = p.order_id
WHERE p.payment_type = 'voucher';


-- name: p10_voucher_order_profile
-- description: Voucher orders versus non-voucher orders - value, instalment depth and dispute rate side by side.
SELECT CASE WHEN f.voucher_value > 0 THEN 'voucher order' ELSE 'non-voucher order' END AS order_type,
       COUNT(*)                     AS orders,
       ROUND(SUM(f.cash_collected),2) AS cash_collected,
       ROUND(AVG(f.cash_collected),2) AS average_order_value,
       ROUND(AVG(f.max_installments),3) AS average_installments,
       SUM(f.disputed_flag)         AS disputed_orders,
       ROUND(100.0*SUM(f.disputed_flag)/COUNT(*),3) AS dispute_rate_pct,
       ROUND(SUM(CASE WHEN f.disputed_flag=1 THEN f.cash_collected ELSE 0 END),2) AS disputed_value,
       ROUND(100.0*SUM(CASE WHEN f.disputed_flag=1 THEN f.cash_collected ELSE 0 END)
             /SUM(f.cash_collected),3) AS pct_of_value_disputed
FROM fact_order_financials f
GROUP BY CASE WHEN f.voucher_value > 0 THEN 'voucher order' ELSE 'non-voucher order' END;
