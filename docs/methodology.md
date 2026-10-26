# Methodology

How the analysis is defined, cleaned, computed and bounded. Read this before
quoting a number from the project.

---

## 1. The business process the data represents

Olist is a **marketplace**, not a retailer. A customer buys from an independent
third-party seller through the marketplace's storefront and checkout:

1. The customer places an order. The order is priced as *merchandise value*
   (`order_items.price`) plus *freight* (`order_items.freight_value`).
2. The customer pays through one of four instruments — card (optionally in
   instalments), boleto (bank slip), debit card, or a marketplace-funded
   voucher. Each payment is one row in `payments`.
3. The marketplace holds the cash while the order moves through
   `approved → processing → invoiced → shipped → delivered`.
4. The seller is paid once the order is fulfilled. Until then the cash is a
   **settlement float** on the marketplace's balance sheet.
5. Orders can be `canceled` or become `unavailable`. The money collected on
   those orders has to go back.

For a finance team this is simultaneously a revenue-recognition problem, a
receivables problem, a working-capital problem and a payment-cost problem. That
is the frame the analysis uses.

---

## 2. Source data

| | |
|---|---|
| Dataset | Brazilian E-Commerce Public Dataset by Olist |
| Publisher | Olist (olistbr) / André Sionek, 2018 |
| Nature | **Real commercial data**, anonymised by Olist |
| Licence | CC BY-NC-SA 4.0 |
| Retrieved by | `src/fetch_data.py`, with SHA-256 verification |
| Raw files | `data/raw/` — untouched |

| Table | Rows | Grain |
|---|---:|---|
| `customers` | 99,441 | one customer profile |
| `orders` | 99,441 | one order |
| `order_items` | 112,650 | one line item |
| `payments` | 103,886 | one payment transaction |
| `reviews` | 99,224 | one review row |
| `products` | 32,951 | one product |
| `sellers` | 3,095 | one seller |
| `product_category_translation` | 71 | one category |

---

## 3. Data model

### Physical layer (`sql/01_schema.sql`)

Eight tables, declared with types, primary keys, foreign keys and ten
secondary indexes. Two design decisions matter:

- **Timestamps are stored as TEXT** in ISO-8601 `YYYY-MM-DD HH:MM:SS` form.
  SQLite's `date()` and `strftime()` parse that natively, and it keeps the
  layer portable to Power BI's connector and to Excel.
- **Money is REAL.** The source carries two decimal places, so nothing is
  lost. Comparisons apply a **R$ 0.01 tolerance** to absorb binary floating
  point noise.

`reviews` has a **composite** primary key `(review_id, order_id)` rather than
`review_id`. 789 review ids in the source are each recorded against two
different orders belonging to the same customer, with identical score, text and
timestamps — one review submission duplicated across two orders. `review_id`
alone is therefore not unique. All rows are retained: both order-level links
are real, because the customer did review both orders. Review-*level* counts
use `COUNT(DISTINCT review_id)`.

### Analytic layer (`sql/02_views.sql`)

| View | Grain | Purpose |
|---|---|---|
| `v_order_financials` | one row per order | The order-level fact. Every financial measure is defined here. |
| `v_payment_detail` | one row per payment | Payment mix, instalment depth, refund exposure by payment |
| `v_item_financials` | one row per line item | Logistics cost-to-serve by product, seller and category |
| `v_seller_performance` | one row per seller | Counterparty concentration |
| `v_category_financials` | one row per category | Freight burden by merchandise category |
| `dim_date` | one row per calendar day | Continuous date spine with a year / quarter / month / weekend hierarchy |

`fact_order_financials` is the **materialised snapshot** of
`v_order_financials`, rebuilt from it on every run and indexed for
aggregation. Re-aggregating payments, items and reviews on every read is
correct for a view but slow across 55 analysis queries; the fact table is the
performance answer, and `dq13_fact_table_reconciliation` proves the two agree
row for row.

---

## 4. Metric definitions

Locked in `src/config.py`, implemented in `sql/02_views.sql`, and asserted in
`tests/test_analysis.py`.

| Metric | Formula | Basis |
|---|---|---|
| **GMV** | `SUM(order_items.price)` | measured |
| **Freight collected** | `SUM(order_items.freight_value)` | measured |
| **Expected charge** | `GMV + freight` per order | measured |
| **Cash collected** | `SUM(payments.payment_value)` | measured |
| **Reconciliation break** | order where `ABS(cash − expected) ≥ 0.01` | measured |
| **Refund exposure** | cash collected where status ∈ {`canceled`, `unavailable`} | measured **proxy** |
| **Net revenue** | cash collected − refund exposure | measured |
| **Settlement float** | cash collected where status ∈ {`shipped`, `invoiced`, `processing`, `created`, `approved`} | measured |
| **Average order value** | cash collected ÷ orders | measured |
| **Freight ratio** | freight collected ÷ GMV | measured |
| **Disputed order** | worst review score ≤ 2 of 5 | measured **proxy** |
| **Seller HHI** | Σ (seller GMV share)² | measured |
| **Modelled payment cost** | acquiring + instalment funding from market rates | **modelled** |

### Status classification

| Status | Class | Treatment |
|---|---|---|
| `delivered` | fulfilled | revenue earned |
| `shipped`, `invoiced`, `processing`, `created`, `approved` | in flight | revenue earned; cash is a settlement float |
| `canceled` | cancelled | refund exposure |
| `unavailable` | unavailable | refund exposure |

---

## 5. Cleaning rules

Seven rules. Every one is recorded in the `dq_cleaning_rules` table inside the
warehouse and in `data/processed/cleaning_log.csv`.

| # | Rule | Scope | Rationale | Action |
|---|---|---|---|---|
| R1 | `payment_installments = 0` → NULL | payments (2 rows) | Zero is not an instalment count; it occurs only on untyped payments | Value nulled, row retained |
| R2 | Timestamps parsed to ISO-8601 | orders, order_items, reviews | The source mixes formats | Value rewritten |
| R3 | Categorical text trimmed and lower-cased | orders, payments, customers, sellers, products | Stray whitespace and case variants split categories | Value rewritten |
| R4 | **No row deleted** | orders (775 kept) | Deleting the 775 orders with cash and no line items would hide R$ 162,591.95 from every total | Rows retained, flagged via `line_item_count = 0` |
| R5 | **No amount edited** | payments, order_items | An unexplained difference is a finding to escalate, not a rounding error to hide | Flagged via `recon_break_flag` |
| R6 | Customers keyed on `customer_unique_id` | all customer aggregations | 2,997 real customers are split across several `customer_id` values; one spans 17 | Aggregation key changed, both keys published |
| R7 | Partial boundary months excluded from trend and YoY | monthly and YoY extracts | The dataset opens with 4 orders (Sep 2016) and closes with 4 (Oct 2018); comparing them with full months manufactures growth | Window restricted to Jan 2017 – Aug 2018 |

### Why R4 and R5 are the important ones

Most portfolios delete the awkward rows and move on. Here, the awkward rows
*are* the analysis:

- 775 orders carry cash but no line items. Removing them would produce a clean
  revenue report that silently omits R$ 162,591.95 of customer money.
- 448 further orders have line items but a collected amount that does not equal
  price plus freight. Adjusting those amounts to make the books close would
  destroy the control finding. They are reported instead.

---

## 6. Data-quality controls

20 checks, recorded with the number of records each touched, in
`dq_cleaning_rules` and reproduced in `reports/data_quality.md`.

| Result | Checks |
|---|---|
| Clean (zero) | primary-key uniqueness on all 8 tables · referential integrity on all 6 foreign keys · negative amounts · temporal ordering (delivered-before-purchased, approved-before-purchased) · orders without payments (1) |
| Findings | 775 orders with no line items · 1,220 reconciliation breaks · 789 duplicated review ids · 2,997 customers split across ids · 4,119 items where freight exceeds price · 547 orders with multiple reviews · 9 zero-value payments · 2 zero-instalment payments · 13 unmapped product categories |

---

## 7. The modelled layer

Only one part of the analysis is modelled: the **payment cost-to-serve**.

| Method | Rate | Fixed fee | Note |
|---|---:|---:|---|
| `credit_card` | 2.90% | — | card acquiring + MDR, typical Brazilian market rate |
| `debit_card` | 1.50% | R$ 1.50 | debit acquiring + per-transaction fee |
| `boleto` | — | R$ 3.00 | per-instruction bank fee |
| `voucher` | — | — | marketplace-funded credit: the full cost is the subsidy |
| Instalment funding | **1.99% per instalment** beyond the first | — | acquirer anticipation premium, base case |

Sensitivity band on the funding rate: **1.00% / 1.99% / 2.99%**.

**These are published market benchmarks, not this marketplace's contract.**
Two consequences are handled explicitly:

1. Every modelled figure is labelled `modelled` in the reports, the KPI
   scoreboard and the Excel workbook.
2. `tests/test_analysis.py::test_sql_cost_model_matches_the_python_cost_model`
   asserts that the rates held in `config.py` are the rates used in the SQL, so
   the assumption cannot drift silently between the two implementations.

The instalment-funding rate is a **modelling convention** as much as an
assumption: Brazilian acquirers commonly quote a single MDR that already
embeds the anticipation cost. Modelling the two components separately
therefore presents the card cost as an **upper bound**, which is why the
sensitivity band is published rather than a single number.

---

## 8. Limitations

**Hard limits of the source data**

1. **No refund table.** Refund exposure is cash collected on orders that will
   never be fulfilled. It is an exposure proxy, not a record of refunds paid.
2. **No chargeback, complaint or dispute table.** A 1–2 star review is a
   proxy for a dispute.
3. **No payment or settlement date.** Cash-timing and DSO analysis is
   impossible; only order lifecycle dates exist.
4. **No logistics cost.** Freight is a revenue line. The freight ratio measures
   the logistics *burden* on the order, not the logistics margin.
5. **No marketing spend, gross margin or commission.** The marketplace's own
   take rate cannot be derived, and no acquisition or retention investment can
   be appraised.
6. **No commission or settlement records.** Seller payout cannot be modelled.
7. **Two tables lack line-item detail** for cancelled and unavailable orders,
   so the offsetting merchandise value of those orders is not recoverable.

**Limits of the analysis**

8. The instalment-depth / dispute-rate relationship is an **association**.
   Longer instalment plans may select for riskier baskets, or may simply
   correlate with higher-value, more complex orders.
9. No intervention was run. **No saving, avoided loss or prevented fraud is
   claimed anywhere in this project.** The method-shift scenario in
   `p08_method_shift_scenario` is a model.
10. The data is a 2016–2018 historical extract of one marketplace in one
    country. Nothing here is a forecast.
11. Customer identity is anonymised and partly fragmented; a customer may not
    be perfectly identified even on `customer_unique_id`.

---

## 9. Reproducibility

- Every source file's SHA-256 digest is recorded in `src/fetch_data.py` and
  verified on download.
- The pipeline is deterministic: `python src/run_all.py` reproduces every
  output byte for byte from the same inputs.
- Every number in the reports is produced by `src/analyze.py` from the
  warehouse, and independently reproduced by the SQL in `sql/04`–`sql/07`.
  `reports/sql_results.md` is the audit trail.
- `tests/test_analysis.py` asserts the headline figures, the financial
  identities (cash = Σ payments; expected charge = GMV + freight; net revenue
  = cash − exposure), the break tolerance, the monotonicity of the dispute
  gradient, the fact-vs-view reconciliation, and that no report contains an
  unmeasured impact claim.
