# Power BI — Marketplace Financial Operations dashboard

A star-schema semantic model with **59 DAX measures** and a **five-page report**,
built for the Head of Finance of an Olist-style marketplace: cash collected
versus revenue earned, refund exposure, payment cost-to-serve, reconciliation
control, counterparty concentration and dispute risk.

Everything here is **generated from code** by `src/build_powerbi_model.py`, so
the semantic model, the DAX catalogue and the report layout cannot drift apart.

```
powerbi/
├── MarketplaceFinance/
│   ├── MarketplaceFinance.pbip                 the project manifest
│   ├── MarketplaceFinance.SemanticModel/
│   │   ├── model.bim                           8 tables, 59 measures, 7 relationships
│   │   └── definition.pbism
│   ├── MarketplaceFinance.Report/
│   │   ├── report.json                         5 pages, 61 visuals
│   │   └── definition.pbir
│   └── Data/                                   8 star-schema CSVs (Power Query source)
├── measures.dax                                the DAX catalogue (generated)
├── data_model.md                               the model explained
├── power_query.md                              the Power Query definitions
├── build_pbit.py                               compiles the .pbit template
└── README.md
```

---

## 1. Opening the dashboard

### Option A — the PBIP project (recommended, verified)

1. Open **Power BI Desktop**.
2. `File > Open` and select
   `powerbi/MarketplaceFinance/MarketplaceFinance.pbip`.
3. Power BI Desktop loads the semantic model and the five report pages.
   The data is not loaded yet — trigger it once:
   `Home > Refresh`.
4. If the data source path is not resolved, open `Transform data`, and for each
   of the eight queries use **Home > Change Source** and point at
   `powerbi/MarketplaceFinance/Data/`. The path is the single literal
   `DataFolder` at the top of each query's M code.
5. `File > Save as` → `MarketplaceFinance.pbit` (or `.pbix`).

> **Verified on this machine.** Power BI Desktop 2.159.883.0 (October 2026
> release) opens the PBIP project: all eight tables appear in the Data pane and
> all five report pages are present. The refresh step was not completed here,
> so the rendered visuals after refresh have not been confirmed.

### Option B — the compiled template

`powerbi/MarketplaceFinance.pbit` is built by `powerbi/build_pbit.py`, which
compiles the PBIP with the [`pbi-tools`](https://pbi.tools/) CLI:

```bash
python powerbi/build_pbit.py --download-tools     # fetches pbi-tools if needed
python powerbi/build_pbit.py --pbi-tools <path to pbi-tools.core.exe>
```

**Known version caveat.** `pbi-tools` 1.2.0 writes a `.pbit` in the legacy
template format (`Version` = `1.28`). Power BI Desktop 2.159.883.0 rejects that
format with *"is incompatible with your current version of Microsoft Power BI
Desktop"*. This was confirmed with a control test against an independently
produced `.pbit`, which fails identically — it is an upstream format
incompatibility, not a defect in this model. The `.pbit` is therefore committed
for completeness, but **Option A is the supported route** on a current Desktop.

---

## 2. The model

### Facts

| Table | Grain | Rows | Carries |
|---|---|---:|---|
| `FactOrder` | one row per order | 99,441 | GMV, freight, expected charge, cash collected, reconciliation break, refund exposure, net revenue, settlement float, instalment depth, review score, dispute flag, fulfilment timings |
| `FactPayment` | one row per payment | 103,886 | payment value, method, instalments, refund exposure, voucher credit, instalment credit |
| `FactOrderItem` | one row per line item | 112,650 | price, freight, product, seller, category, freight-over-price flag |

### Dimensions

| Table | Rows | Notes |
|---|---:|---|
| `DimDate` | 774 | Continuous spine, marked as the date table |
| `DimCustomer` | 96,096 | Keyed on `customer_unique_id` — 2,997 people are split across several `customer_id` values in the source |
| `DimSeller` | 3,095 | GMV rank, freight ratio |
| `DimProduct` | 32,951 | Category and English label |
| `DimPaymentMethod` | 5 | **Carries the modelled cost rates** — edit here, not in DAX |

### Relationships

```
DimDate      1 ────< FactOrder
DimCustomer  1 ────< FactOrder
DimSeller    1 ────< FactOrderItem
DimProduct   1 ────< FactOrderItem
FactOrder    1 ────< FactPayment
FactOrder    1 ────< FactOrderItem
DimPaymentMethod 1 ──< FactPayment
```

`DimPaymentMethod` is related to `FactPayment` **only**. Relating it to
`FactOrder` as well would give `FactPayment` two paths to the same dimension
and Power BI refuses to load the model
(`PFE_XL_USERELATIONSHIP_AMBIGUOUS_PATH`). Order-level payment-method
breakdowns therefore use the plain text column `FactOrder[PaymentMethodKey]`,
which needs no relationship.

Date filtering reaches `FactPayment` and `FactOrderItem` through `FactOrder`,
so there is exactly one path from each fact to `DimDate`.

---

## 3. The report pages

| Page | Contents |
|---|---|
| **Executive Overview** | Six KPI cards (GMV, cash collected, net revenue, refund exposure, AOV, break rate) · cash collected by month · cash by order status · the reconciliation gap, the settlement float, net revenue as a share of cash, and gross break value |
| **Revenue and Growth** | Cash by month and year · net revenue by quarter · cash collected by customer state · YoY cards for cash, orders and AOV · AOV by month · repeat rate and cash per customer · a year slicer |
| **Payment Mix and Cost to Serve** | Payment value by method · payment value by instalment count · modelled cost by method · value-weighted instalment depth, instalment-funded value, total modelled cost, contribution and contribution margin · the assumption table, editable in `DimPaymentMethod` |
| **Exposure and Reconciliation** | Refund exposure rate, break rate, gross break value and cash-without-merchandise cards · refund exposure by month and by status · break value by status · the exception table · status-class and payment-method slicers |
| **Concentration and Risk** | Seller HHI, top-10 share, seller count, freight ratio · the concentration (Pareto) curve · freight burden by category · dispute rate by instalment depth · disputed value by status |

---

## 4. The measures

The full catalogue is in [`measures.dax`](measures.dax) (59 measures). The ones
that carry the analysis:

| Measure | Definition |
|---|---|
| `GMV` | `SUM ( FactOrder[MerchandiseValue] )` |
| `Cash Collected` | `SUM ( FactOrder[CashCollected] )` |
| `Net Revenue` | `SUM ( FactOrder[NetRevenue] )` |
| `Refund Exposure` | `SUM ( FactOrder[RefundExposure] )` |
| `Reconciliation Break Rate` | `DIVIDE ( [Reconciliation Break Orders], [Orders] )` |
| `Gross Break Value` | `SUMX ( FILTER ( FactOrder, FactOrder[ReconBreak] = 1 ), ABS ( FactOrder[ReconDelta] ) )` |
| `Cash Without Merchandise` | `SUMX ( FILTER ( FactOrder, FactOrder[LineItemCount] = 0 ), FactOrder[CashCollected] )` |
| `Dispute Rate` | `DIVIDE ( [Disputed Orders], [Orders With Reviews] )` |
| `Value Weighted Average Installments` | `DIVIDE ( SUMX ( FactPayment, FactPayment[Installments] * FactPayment[PaymentValue] ), [Payment Value] )` |
| `Modelled Acquiring Cost` | `SUMX ( FactPayment, FactPayment[PaymentValue] * RELATED ( DimPaymentMethod[RatePct] ) + RELATED ( DimPaymentMethod[FixedFee] ) )` |
| `Modelled Installment Funding` | `SUMX ( FactPayment, IF ( FactPayment[PaymentMethodKey] = "credit_card", FactPayment[PaymentValue] * RELATED ( DimPaymentMethod[FundingRatePerInstallment] ) * ( FactPayment[Installments] - 1 ), 0 ) )` |
| `Seller HHI` | `VAR T = [GMV] RETURN SUMX ( DimSeller, DIVIDE ( DimSeller[SellerGMV], T ) ^ 2 )` |
| `Cumulative GMV %` | running total across `DimSeller[GMVRank]`, for the Pareto curve |

### Re-running the cost model on different assumptions

The modelled rates live in `DimPaymentMethod`:

| Column | Value |
|---|---|
| `RatePct` | acquiring rate as a share of the payment value |
| `FixedFee` | per-transaction fee in BRL |
| `FundingRatePerInstallment` | instalment-funding premium (1.99% base case) |

Edit them in Power BI Desktop, refresh, and every modelled measure
re-computes. No DAX edit is needed. This is the intended way to answer
"what if the acquirer rate were 2.5%?".

---

## 5. The report is emitted in two formats

Power BI Desktop reads a PBIP report from the `definition/` folder in the
**PBIR** format. Field bindings live in `visual.query.queryState`, and that is
where the generator puts them — 50 data visuals across the five pages.

The legacy `report.json` sits alongside it as a portable copy of the same
layout, but note that Power BI Desktop **discards the `projections` block** in
that legacy file: on its own it would render empty visuals. Use the PBIP
project, not the legacy file.

---

## 6. Rebuilding

```bash
python src/build_powerbi_data.py    # Data/*.csv      (8 star-schema files)
python src/build_powerbi_model.py    # model.bim, report.json, measures.dax
python powerbi/build_pbit.py --download-tools   # the .pbit template
```

`src/build_powerbi_model.py` writes `model.bim`, `report.json`,
`definition.pbir`, `definition.pbism`, the `.pbip` manifest and `measures.dax`
from a single schema definition, so the model and its documentation are always
the same object.

---

## 7. Technical notes

- **PBIP format requirements.** In the PBIP semantic-model format the Power
  Query definition lives in `partition.source.expression`. The older
  `datasourceQueries` array is rejected outright by Power BI Desktop
  (*"Unrecognized JSON property: datasourceQueries"*) whether it sits inside
  `model` or at the root.
- **A measure may not shadow a column** in the same table. The fact columns
  were renamed (`GMV → MerchandiseValue`, `CustomerGMV`, `ProductGMV`) so the
  `GMV` measure can keep its name.
- **Every visual carries one measure** plus an optional category and series —
  the form Power BI Desktop resolves most reliably from a template that has
  never been opened interactively.
- **The data is embedded in the project folder**, not in the model, so the
  template can be regenerated at any time from the CSVs.
