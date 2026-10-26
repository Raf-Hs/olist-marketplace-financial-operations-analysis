# Data model

The star schema behind `powerbi/MarketplaceFinance.pbit`, explained for a
reviewer who wants to know what each table holds and why the relationships are
shaped the way they are.

---

## 1. The grain

| Table | Grain | Primary key | Rows |
|---|---|---|---:|
| `FactOrder` | one order | `OrderKey` | 99,441 |
| `FactPayment` | one payment on one order | `OrderKey` + `PaymentSequence` | 103,886 |
| `FactOrderItem` | one line on one order | `OrderKey` + `OrderItemKey` | 112,650 |
| `DimDate` | one calendar day | `DateKey` | 774 |
| `DimCustomer` | one real customer | `CustomerKey` (`customer_unique_id`) | 96,096 |
| `DimSeller` | one seller | `SellerKey` | 3,095 |
| `DimProduct` | one product | `ProductKey` | 32,951 |
| `DimPaymentMethod` | one payment method | `PaymentMethodKey` | 5 |

Every fact is at the same grain as the source table it comes from, so no
aggregation is hidden inside a fact and every measure is a straightforward
`SUM` or `COUNTROWS`.

---

## 2. `FactOrder` — the financial fact

One row per order, carrying every measure the finance team works with.

| Column | Type | Source | Purpose |
|---|---|---|---|
| `OrderKey` | text | `orders.order_id` | The key |
| `DateKey` | int | `purchase_date` → `yyyymmdd` | Join to `DimDate` |
| `CustomerKey` | text | `customer_unique_id` | Join to `DimCustomer` |
| `PaymentMethodKey` | text | dominant method on the order | Plain text; used for order-level breakdowns |
| `OrderStatus`, `StatusClass` | text | `orders.order_status` | The fulfilment state and its financial class |
| `PurchaseMonth`, `PurchaseYear`, `PurchaseQuarter` | text / int | derived | Month and quarter grain without a date join |
| `CustomerState` | text | `customers.customer_state` | Geography |
| `LineItemCount`, `SellerCount`, `ProductCount` | int | derived | Basket shape |
| `MerchandiseValue` | double | `SUM(order_items.price)` | **GMV** |
| `FreightCollected` | double | `SUM(order_items.freight_value)` | Logistics charged |
| `ExpectedCharge` | double | GMV + freight | What the order should have cost |
| `CashCollected` | double | `SUM(payments.payment_value)` | What was actually paid |
| `ReconDelta` | double | cash − expected | The reconciliation difference |
| `ReconBreak` | int | `ABS(ReconDelta) ≥ 0.01` | The control flag |
| `PaymentCount`, `MaxInstallments`, `InstallmentMonths` | int | derived | Instalment profile of the order |
| `RefundExposure` | double | cash where status ∈ {canceled, unavailable} | **Exposure proxy** |
| `NetRevenue` | double | cash − refund exposure | The measure to manage on |
| `SettlementFloat` | double | cash where status ∈ {in flight} | Cash held before seller payout |
| `VoucherValue`, `CardValue`, `BoletoValue`, `DebitCardValue` | double | derived | Payment mix at order level |
| `ReviewCount`, `WorstReviewScore`, `DisputedFlag` | int | derived | Dispute proxy |
| `DuplicateReviewFlag` | int | derived | The order's review id is shared with another order |
| `DeliveryDays`, `DaysLateVsPromise` | double | derived | Fulfilment performance |

---

## 3. `FactPayment`

One row per payment transaction.

| Column | Purpose |
|---|---|
| `OrderKey`, `PaymentSequence` | Key to `FactOrder` |
| `PaymentMethodKey` | Join to `DimPaymentMethod` — carries the cost rates |
| `Installments` | Instalment count (0 → NULL at load) |
| `PaymentValue` | Amount collected |
| `RefundExposure` | Portion of this payment on a non-fulfilled order |
| `VoucherValue` | Marketplace-funded promotional credit |
| `InstallmentCreditValue` | Card value settled on an instalment plan |
| `StatusClass`, `CustomerState` | Cut dimensions carried for convenience |

The instalment-funding cost model needs the **payment-level** method and
instalment count, which is why `FactPayment` relates to `DimPaymentMethod`
rather than `FactOrder`.

---

## 4. `FactOrderItem`

One row per line item. Carries the logistics economics and the product and
seller keys.

| Column | Purpose |
|---|---|
| `OrderKey`, `OrderItemKey` | Key to `FactOrder` |
| `ProductKey`, `SellerKey` | Join to the dimensions |
| `Price`, `FreightValue`, `LineCharge` | The line economics |
| `FreightOverPrice` | Flag: freight exceeds the merchandise value (4,119 rows) |
| `LargeLine` | Flag: line charge above R$ 3,000 |
| `ProductWeightG`, `SellerState` | Dimensions carried for convenience |

---

## 5. The dimensions

### `DimDate` — 774 days, 2016-09-04 to 2018-10-17

A continuous spine, not a list of dates that happen to appear in the data, so
that months with no orders still exist in the model and a month-on-month series
has no gaps. Carries `year`, `MonthNumber`, `quarter_key` and `month_start`.
The table is marked as the date table, which is what makes
`SAMEPERIODLASTYEAR` and `DATEADD` work in the time-intelligence measures.

### `DimCustomer` — 96,096 rows

Keyed on `customer_unique_id`, **not** `customer_id`. This is the single most
important modelling decision in the project: 2,997 real customers are split
across several `customer_id` values in the source (one across 17), so keying
on `customer_id` would inflate the customer base by 3.5% and understate the
repeat rate.

Carries order count, cash collected, GMV, refund exposure, disputed orders,
first and last purchase date, average order value, `IsRepeat`, settlement float
and instalment months.

### `DimSeller` — 3,095 rows

Carries `GMVRank` (a rank by GMV, used by the top-N and Pareto measures) and
the freight ratio per seller.

### `DimProduct` — 32,951 rows

Product, category, English category label and physical dimensions, plus the
line-item count and GMV the product has generated.

### `DimPaymentMethod` — 5 rows

**This is where the assumptions live.**

| Column | Meaning |
|---|---|
| `PaymentMethodKey` | The key |
| `PaymentType` | Card / boleto / debit / voucher / not defined |
| `Description` | Plain-language description |
| `RatePct` | Acquiring rate as a share of the payment value |
| `FixedFee` | Per-transaction fee in BRL |
| `FundingRatePerInstallment` | Instalment-funding premium (1.99% base case) |
| `IsPromotional` | 1 for `voucher` — revenue forgone rather than collected |
| `AssumptionNote` | The published basis for the rate |

Because the rates are data, the modelled cost measures can be re-run against
different assumptions by editing this table — no DAX edit and no code change.

---

## 6. Relationships and why they are shaped this way

| From | To | On | Cardinality |
|---|---|---|---|
| `FactOrder` | `DimDate` | `DateKey` | many-to-one |
| `FactOrder` | `DimCustomer` | `CustomerKey` | many-to-one |
| `FactPayment` | `FactOrder` | `OrderKey` | many-to-one |
| `FactPayment` | `DimPaymentMethod` | `PaymentMethodKey` | many-to-one |
| `FactOrderItem` | `FactOrder` | `OrderKey` | many-to-one |
| `FactOrderItem` | `DimProduct` | `ProductKey` | many-to-one |
| `FactOrderItem` | `DimSeller` | `SellerKey` | many-to-one |

### Two decisions that the model loader will not forgive

**1. One path per fact to each dimension.** Relating `DimPaymentMethod` to
`FactOrder` as well as to `FactPayment` gives `FactPayment` two routes to the
same dimension — `FactPayment → FactOrder → DimPaymentMethod` and
`FactPayment → DimPaymentMethod` — and Power BI refuses to load the model:

> `There are ambiguous paths between 'FactPayment' and 'DimPaymentMethod'`

`DimPaymentMethod` therefore relates to `FactPayment` only. Order-level
payment-method breakdowns use the plain text column
`FactOrder[PaymentMethodKey]`, which needs no relationship.

The same principle applies to dates: `FactPayment` and `FactOrderItem` reach
`DimDate` through `FactOrder`, so there is exactly one path from each fact to
the date table and the time-intelligence measures never go ambiguous.

**2. No measure may share a name with a column in the same table.** A measure
called `GMV` next to a column called `GMV` fails the load:

> `The 'GMV' measure cannot be created because a column with the same name already exists`

The fact columns were renamed to `MerchandiseValue`, `CustomerGMV` and
`ProductGMV`, which lets the measure keep the name a finance reader expects.

---

## 7. Measure layer

59 measures across five tables. The complete catalogue with DAX and format
strings is in [`measures.dax`](measures.dax). The families:

| Family | Examples |
|---|---|
| Revenue and cash | `GMV`, `Cash Collected`, `Net Revenue`, `Expected Charge`, `Freight Collected` |
| Exposure | `Refund Exposure`, `Refund Exposure Rate`, `Settlement Float` |
| Control | `Reconciliation Break Orders`, `Reconciliation Break Rate`, `Gross Break Value`, `Net Break Amount`, `Cash Without Merchandise` |
| Unit economics | `Average Order Value`, `Freight Ratio`, `Modelled Acquiring Cost`, `Modelled Installment Funding`, `Modelled Total Payment Cost`, `Contribution After Payment Cost`, `Contribution Margin %` |
| Credit and risk | `Value Weighted Average Installments`, `Installment Funded Value`, `Disputed Orders`, `Disputed Value`, `Dispute Rate`, `Cash at Risk %` |
| Customer | `Customers`, `Cash per Customer`, `Repeat Customers`, `Repeat Customer Rate`, `Orders per Customer` |
| Concentration | `Sellers`, `Top 1 / 10 / 100 / 1,000 Sellers GMV %`, `Seller HHI`, `Cumulative GMV %` |
| Time intelligence | `Cash MoM %`, `Cash YoY %`, `Orders YoY %`, `AOV YoY %` |
