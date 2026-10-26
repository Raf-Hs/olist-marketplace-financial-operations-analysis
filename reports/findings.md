# Findings

Every figure below is computed by `src/analyze.py` from the warehouse and reproduced in `reports/sql_results.md`. Figures marked **modelelled** depend on the published market-rate assumptions in `src/config.py`; all others are measured from the source data.

## 1. The cash-to-revenue reconciliation does not close

**What the data shows.** Customers paid R$ 16,008,872.12 against an expected charge of R$ 15,848,243.14 (merchandise R$ 13,591,643.70 plus freight R$ 2,256,599.44). The gap is R$ 160,628.98. 1,220 orders (1.227%) fail the reconciliation outright, carrying R$ 170,716.88 of gross break value.

**Why it happens.** The break has two distinct causes. 772 orders have cash collected but no line items at all - R$ 162,591.95 of cash with nothing in the dataset to deliver against it. The remaining 448 orders do have line items but the amount paid does not equal price plus freight.

| Break reason | Size band | Orders | Absolute break |
|---|---|---:|---:|
| line items present | a. rounding (< R$1) | 134 | R$ 6.70 |
| line items present | b. R$1 - R$100 | 292 | R$ 4,282.99 |
| line items present | c. R$100 - R$1,000 | 22 | R$ 3,833.32 |
| no line items at all | b. R$1 - R$100 | 358 | R$ 22,310.79 |
| no line items at all | c. R$100 - R$1,000 | 388 | R$ 92,522.03 |
| no line items at all | d. R$1,000+ | 26 | R$ 47,759.13 |

**Why it matters.** A revenue report built on line items alone silently drops R$ 162,591.95 of collected cash. A report built on cash alone overstates revenue by the reconciliation gap. The finance team cannot close its own books from this extract without the missing order content.

**What would be needed to act.** The order-detail extract for the affected 1,220 orders from the order-management system. The break is reported, not corrected: no amount in this analysis has been adjusted to make it close.

## 2. Refund exposure is real, measurable and volatile

**What the data shows.** 1,234 orders (R$ 269,735.11 of cash collected) were cancelled or became unavailable. The cash collected against them - R$ 269,735.11, or 1.685% of all cash collected - is owed back. Net revenue after that exposure is R$ 15,739,137.01, 98.315% of cash collected.

| Order status | Orders | Cash collected | Refund exposure | Orders with no line items |
|---|---:|---:|---:|---:|
| canceled | 625 | R$ 143,255.60 | R$ 143,255.60 | 164 |
| unavailable | 609 | R$ 126,479.51 | R$ 126,479.51 | 603 |

**Limitation.** The source data contains no refund table. This is the cash collected on orders that will never be fulfilled - an exposure proxy, not a record of refunds actually paid. It is the most the data can support.

**Volatility.** The monthly rate moves from 0.331% to 5.381% of cash collected across the clean window (16x), so a reserve set on the lifetime average would be under-provided in the bad months.

## 3. Instalment-heavy card volume is the largest single cost lever

**What the data shows.** Card payments are 78.345% of all collected value. R$ 10,101,491.12 of that - 80.541% of card value - is settled on an instalment plan, at a value-weighted average depth of 4.967 instalments (maximum 24).

**Modelled cost.** Applying published Brazilian acquiring rates (card 2.9%, debit 1.5% + R$1.50, boleto R$3.00) and an instalment-funding rate of 1.99% per instalment gives a total modelled payment cost of R$ 1,418,757.17, of which R$ 990,121.38 is instalment funding - 6.291% of net revenue.

| Funding rate per instalment | Modelled instalment funding | % of card value |
|---:|---:|---:|
| 1.00% | R$ 497,548.43 | 3.967% |
| 1.99% | R$ 990,121.38 | 7.894% |
| 2.99% | R$ 1,487,669.81 | 11.861% |

**Interpretation.** The instalment-funding component is the largest single item in the modelled cost base - larger than the R$ 428,635.79 acquiring cost and the R$ 379,436.87 of promotional voucher credit combined. At the low end of the published rate band it is still the dominant term.

**Limitation.** These are market benchmarks, not this marketplace's contract. The sensitivity band above is the honest statement of how much the conclusion depends on the assumption.

## 4. Dispute risk rises with instalment depth, and promotional credit carries the highest rate

**What the data shows.** A review score of 1 or 2 out of 5 marks a disputed order. 14,533 orders are disputed, carrying R$ 2,769,252.32 of cash - 17.46% of the value on reviewed orders.

| Instalment bucket | Orders | Cash | Dispute rate | Disputed value |
|---|---:|---:|---:|---:|
| 1 (paid in full) | 24,005 | R$ 2,422,409.82 | 12.964% | R$ 364,299.46 |
| 2 - 3 | 22,649 | R$ 3,070,682.59 | 14.473% | R$ 492,308.96 |
| 4 - 6 | 16,160 | R$ 2,950,182.46 | 15.186% | R$ 508,826.51 |
| 7 - 12 | 11,976 | R$ 4,022,205.80 | 17.351% | R$ 776,882.64 |
| 13 + | 185 | R$ 77,046.48 | 21.081% | R$ 16,679.51 |

**Promotional credit.** Orders funded by a marketplace voucher have a dispute rate of 16.244% against 14.549% for orders without a voucher, while carrying R$ 379,436.87 of promotional credit (2.37% of all collected value).

**What this does and does not show.** The instalment-depth gradient is an association in the data, not a demonstrated cause: longer instalment plans may select for riskier baskets, or may simply correlate with higher-value and more complex orders. No causal claim is made and no intervention has been measured. A review score is a proxy for a dispute - the dataset records no chargeback, refund or complaint.

## 5. Logistics is the second-largest cost, and it is getting worse as the business scales

**What the data shows.** Freight collected is R$ 2,256,599.44, 16.6% of merchandise value. On a like-for-like basis (Jan-Aug 2017 vs Jan-Aug 2018) the freight ratio moved from 15.98% to 17.06%, +1.08 points, while cash grew 136.98%. Scale is not delivering logistics efficiency.

4,119 line items (3.66%) ship with a freight charge larger than the merchandise value itself, by R$ 27,659.95 in aggregate.

| Category | GMV | Freight | Freight ratio |
|---|---:|---:|---:|
| health_beauty | R$ 1,258,681.34 | R$ 182,748.35 | 14.52% |
| watches_gifts | R$ 1,205,005.68 | R$ 100,535.93 | 8.34% |
| bed_bath_table | R$ 1,036,988.68 | R$ 204,693.04 | 19.74% |
| sports_leisure | R$ 988,048.97 | R$ 170,274.23 | 17.23% |
| computers_accessories | R$ 911,954.32 | R$ 147,318.08 | 16.15% |

Across the 27 categories with at least R$ 100,000 of GMV, the freight burden runs from computers at 4.41% to electronics at 29.07%. The three heaviest - electronics, office_furniture and furniture_decor - carry R$ 1,163,969.93 of GMV between them, so a category-level freight change would move a meaningful share of the portfolio rather than a rounding of it.

**Limitation.** Freight collected is a revenue line, not a carrier invoice. The dataset contains no logistics cost, so the ratio measures the logistics burden on the order, not the logistics margin.

## 6. Seller concentration is low; the real concentration is regional

**What the data shows.** 3,095 active sellers. The largest holds 1.688% of GMV, the top ten 13.15%, the top hundred 45.061%. The Herfindahl-Hirschman index is 0.00357 - far below the 0.15 threshold that marks an unconcentrated market - and only 9 sellers hold more than 1% of GMV each. Counterparty dependency is not a material risk in this data.

**What would be concentrated instead.** Supply sits in one state: Sao Paulo hosts 1,849 of the 3,095 sellers and 64.4% of GMV. A regional logistics or regulatory event is a bigger exposure than the loss of any single seller.

## 7. Growth is entirely acquisition, and the customer base barely repeats

**What the data shows.** On a like-for-like basis cash grew 136.98% (order volume 135.07%, average order value only 0.81%) and active customers grew 136.3%. Across the whole window only 2,997 of 96,096 customers (3.119%) placed more than one order - 1.0348 orders per customer.

**Data-quality caveat that matters here.** 2,997 real customers appear under more than one customer_id (one appears under 17). Counting customers on customer_id would overstate the base by 3.5% and would understate the repeat rate. All customer metrics in this project use customer_unique_id.

**What this means.** The platform acquires customers and does not retain them. That is a decision about acquisition economics and lifetime value that this dataset cannot settle - there is no marketing spend, no margin and no customer-acquisition cost here.
