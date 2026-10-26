# Business decision report

**Target stakeholder.** Head of Finance / Financial Operations Manager at a Brazilian marketplace operating an Olist-style model: third-party sellers, multiple payment methods, customer funds collected before seller settlement.

## The decision

The finance team currently reports GMV. This analysis shows that GMV and cash are not the same population and that neither is net revenue. The decision is which of the three the business should manage on, and what has to be fixed in the data pipeline before it can.

| Option | What it fixes | Evidence | Cost to implement | Verdict |
|---|---|---|---|---|
| A. Keep reporting GMV | Nothing | R$ 13,591,643.70 of merchandise value | None | **Rejected** - GMV ignores freight, refunds and the R$ 162,591.95 of cash with no merchandise record |
| B. Manage on net revenue | Revenue recognition | R$ 15,739,137.01 net of R$ 269,735.11 exposure | Low - a status rule on the fact table | **Recommended as the reporting spine** |
| C. Fix the reconciliation break | Control | 1,220 orders, R$ 170,716.88 gross break | Medium - upstream order-detail extract | **Recommended, in parallel** |
| D. Shift payment mix away from long instalments | Modelled cost | R$ 990,121.38 of modelled instalment funding | Medium - pricing and checkout incentive changes | **Test, do not assume** |
| E. Tighten logistics on heavy categories | Freight ratio | 16.6% of GMV, +1.08 pts YoY | Medium - carrier pricing and seller terms | **Recommended as a pilot** |

## Why B and C first

Options B and C are the only two that change what the business *knows*. They cost no discount and no subsidy, they require no customer behaviour change, and they make every other option measurable afterwards. D and E are real levers but their impact cannot be observed until the reporting spine is correct - which is exactly why they come later.

## B: Manage on net revenue

**Recommendation.** Adopt net revenue (R$ 15,739,137.01) as the headline financial measure, with cash collected and GMV as supporting lines.

**Why.** Net revenue is the only one of the three measures that is both measured from the data and comparable across periods. It answers the question a finance team is actually asked - what did the business keep - and it explicitly carries the refund exposure that GMV hides.

**Measured baseline.** Net revenue is 98.315% of cash collected; refund exposure runs at 1.685% of cash collected and peaked at 5.381% in a single month of the clean window.

**Limitations.** The refund figure is an exposure proxy, not a refunds ledger - the source has no refund table. Before the measure is used for external reporting it needs the actual refund transactions, and the exposure policy (reserve basis, cut-off) has to be set by the finance team.

## C: Fix the reconciliation break

**Recommendation.** Raise a control ticket for the 1,220 orders that fail the reconciliation, prioritising the 772 orders with cash and no line items (R$ 162,591.95).

**Why.** This is the one finding in the analysis that is unambiguously a data defect rather than a business outcome. Cash has been collected; the order content that would justify it is missing from the extract. Until it is recovered, no revenue number in this dataset can be independently verified.

**Measured baseline.** 1,220 orders in break (1.227%), R$ 170,716.88 of gross break value, of which R$ 162,591.95 is cash with no merchandise record. The break has been reported, not corrected, so this baseline will not move on its own.

**Limitations.** The analysis cannot tell whether the missing content was never captured, was deleted when the order was cancelled, or was lost in the extract. That distinction determines whether this is a pipeline fix or a historical backfill, and it has to be answered upstream.

## D: Payment mix (test, do not assume)

**Recommendation.** Model the cost of the payment mix before changing it. The modelled instalment-funding cost is R$ 990,121.38 at the 1.99% base rate, but the published band runs from R$ 497,548.43 to R$ 1,487,669.81 - so the *size* of the lever is assumption-dependent even though its *direction* is not. At the low end the instalment-funding cost would still be 116% of the modelled acquiring cost.

**Limitations.** No contractual rate for this marketplace is in the data, no checkout experiment has been run, and the direction of customer behaviour response to a payment-method incentive is unknown. No saving is claimed here, because none has been measured.

## E: Logistics (pilot on the heavy categories)


## Measurement plan

| Metric | Baseline (measured) | Target | Source |
|---|---:|---|---|
| Reconciliation break rate | 1.227% of orders | < 0.25% | fact_order_financials |
| Cash with no merchandise record | R$ 162,591.95 | R$ 0.00 | fact_order_financials |
| Refund exposure rate | 1.685% of cash | within policy | fact_order_financials |
| Freight ratio (Jan-Aug YoY) | 17.06% | <= 15.98% | v_item_financials |
| Dispute rate, 7+ instalments | 17.351% | monitor | fact_order_financials |

Every baseline in this table is produced by `src/analyze.py` and reproducible from `sql/04_revenue_and_cash.sql` and `sql/06_exposure_and_reconciliation.sql`.
