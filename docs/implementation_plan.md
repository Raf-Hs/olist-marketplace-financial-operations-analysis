# Implementation plan

How this project was built, and why each piece exists. Written as the plan that
was followed, with the decisions that changed along the way recorded honestly.

---

## Phase 0 — Dataset selection

**Goal.** Find a real, documented, publicly licensed financial dataset that
supports a genuine finance question, and rule out the alternatives on stated
criteria.

**Approach.** Screen candidates on five criteria — relevance to a real
financial decision, field coverage and record count, data quality and
documentation, compatibility with SQL / Excel / Power BI, and the number of
meaningful business questions it can answer.

**Shortlist and outcome.**

| Candidate | Outcome |
|---|---|
| Salad Money Open Banking (UK) | **Rejected** — access-restricted to UK academics through a Trusted Research Environment; not reproducible for a reviewer. |
| Receiver General Accounting Transactions (Canada) | **Rejected** — 91% null GL account codes; revenue cannot be classified. A data-quality project with no financial story. |
| USAspending federal awards | **Rejected** — spending only; no revenue, no customer, no payment instrument. |
| Olist Brazilian E-Commerce | **Chosen** — real, complete, multi-table, with revenue, cash, payment instrument, instalment depth, fulfilment, disputes, sellers and geography. |

**Decision recorded.** Olist was chosen over the alternatives because it is the
only candidate that models a *financial operations* business end to end: a
marketplace that collects the customer's money, holds it, pays the seller later
and has to refund it.

---

## Phase 1 — Business framing

**Goal.** Write down the business process, the stakeholder, the decision and
the questions, before touching a number.

**Output.** The marketplace revenue cycle described in
`docs/methodology.md §1`; the stakeholder (Head of Finance / Financial
Operations Manager); and one primary question — *how much has been collected
that has not been earned, what does the payment mix cost to serve, and where is
the cash at risk?*

**Decision recorded.** The analysis was framed around **cash-versus-revenue
reconciliation** rather than around growth, because a marketplace's headline
number (GMV) and its cash position are different populations and the dataset
contains enough information to measure the difference.

---

## Phase 2 — Warehouse and analytic layer

**Goal.** A warehouse where every financial number has one definition.

**Plan.**

1. `sql/01_schema.sql` — eight tables with types, keys and indexes.
2. `src/build_db.py` — load the CSVs, standardise types and whitespace,
   record every rule in a `dq_cleaning_rules` audit table, build the views.
3. `sql/02_views.sql` — six analytic views; `v_order_financials` is the
   order-level fact.
4. Materialise `fact_order_financials` for query performance.

**Problems hit and fixed.**

| Problem | Fix |
|---|---|
| `to_sql(if_exists="replace")` silently dropped the primary keys and all ten indexes, turning every correlated subquery into a full table scan | Load with `if_exists="append"` into the pre-created tables, and assert after the load that the declared indexes still exist |
| The order-level fact re-aggregated payments, items and reviews on every read — the analysis suite took 15 minutes | Materialise the fact from the view each run, and add `dq13_fact_table_reconciliation` to prove the two agree |
| `reviews.review_id` is not unique — 789 ids appear against two orders of the same customer | Composite primary key `(review_id, order_id)`; all rows retained; review-level counts use `COUNT(DISTINCT review_id)` |
| The like-for-like window `purchase_month BETWEEN '2017-01-01' AND '2018-08-01'` silently included **all** of 2017, understating growth by 120 percentage points | Filter on month-of-year and year explicitly: `CAST(strftime('%m', purchase_month) AS INTEGER) BETWEEN 1 AND 8 AND CAST(purchase_year AS INTEGER) IN (2017, 2018)` |

---

## Phase 3 — Analysis SQL

**Goal.** Every question answered by a documented, re-runnable query.

**Plan.** Five analysis files, each query carrying a `-- name:` /
`-- description:` header so `src/run_queries.py` can execute them all and
render `reports/sql_results.md` as the audit trail.

```
03_data_quality.sql               13 control checks
04_revenue_and_cash.sql           10 revenue, cash, trend and geography queries
05_payment_mix_and_cost.sql       10 payment mix, instalment and cost-model queries
06_exposure_and_reconciliation.sql 11 refund exposure, breaks and scorecard
07_concentration_and_risk.sql     11 concentration, logistics and dispute queries
```

**Problem hit and fixed.** Several compound `SELECT ... UNION ALL` statements
failed in SQLite with *ambiguous column name* and *datatype mismatch* because
the same table was joined under two names. Fixed by qualifying every column
with a table alias, wrapping ordered sub-queries in their own `FROM (...)`, and
replacing a `p99` CTE with a scalar subquery.

---

## Phase 4 — Findings and reports

**Goal.** Numbers first, narrative second, and no narrative that can disagree
with a number.

**Plan.** `src/analyze.py` computes the KPI set, writes
`reports/key_metrics.json`, and then renders `findings.md`,
`executive_summary.md` and `business_decision_report.md` **from that same
dictionary**. A sentence and the number beside it therefore cannot disagree.

**Structure of every finding** — what the data shows · why it happens · why it
matters · what a manager could consider · what is still missing · what the
finding does *not* prove.

**Guard rail.** `tests/test_analysis.py::test_reports_never_claim_an_unmeasured_impact`
fails the build if any report contains "saved R$", "reduced costs by",
"prevented fraud", "increased profit by" or "eliminated the loss".

---

## Phase 5 — Excel workbook

**Goal.** A self-contained workbook a stakeholder can use without Python.

**Plan.** 12 sheets, native Excel charts (so the reader can right-click →
*Edit Data* and re-point a series), conditional formatting on the key ratios,
and an *Order Records* sheet carrying the cleaned order-level fact ready for
`Insert > PivotTable`.

---

## Phase 6 — Power BI model

**Goal.** A star schema, a measure layer and a five-page report, generated from
code so the model, the DAX catalogue and the report layout cannot drift apart.

**Plan.**

- `src/build_powerbi_data.py` → 8 star-schema CSVs into
  `powerbi/MarketplaceFinance/Data/`.
- `src/build_powerbi_model.py` → `model.bim`, `report.json`, `definition.pbir`,
  `definition.pbism`, the `.pbip` manifest and `measures.dax`, all from one
  schema definition.
- `powerbi/build_pbit.py` → compiles the template with `pbi-tools`.

**Design decisions.**

- One measure per visual, with an optional category and series. That is the
  form Power BI Desktop resolves most reliably from a template that has never
  been opened interactively.
- Date filtering reaches `FactPayment` and `FactOrderItem` through `FactOrder`
  rather than through a second relationship to `DimDate`.
- The modelled rates live in `DimPaymentMethod`, so the cost-to-serve numbers
  can be re-run against different assumptions by editing one table — no DAX
  edit required.

**Problems hit and fixed.**

| Problem | Fix |
|---|---|
| `datasourceQueries` nested inside `model` | Rejected by Power BI Desktop: *"Unrecognized JSON property: datasourceQueries"*. The Power Query definition belongs in `partition.source.expression`; the property was removed entirely. |
| `datasourceQueries` at the model root | Also rejected. Removed. |
| Ambiguous path: `FactPayment → FactOrder → DimPaymentMethod` and `FactPayment → DimPaymentMethod` | `DimPaymentMethod` is related to `FactPayment` only. Order-level payment-method breakdowns use the plain text column `FactOrder[PaymentMethodKey]`, which needs no relationship. |
| *"The 'GMV' measure cannot be created because a column with the same name already exists"* | The fact columns were renamed: `GMV → MerchandiseValue`, `GMV → CustomerGMV` (DimCustomer), `GMV → ProductGMV` (DimProduct). The measure keeps the name `GMV`. |
| The `.pbit` produced by `pbi-tools` 1.2.0 is rejected by Power BI Desktop 2.159.883.0 | Verified with a control test against an existing project, which fails identically — an upstream format incompatibility, not a defect in this model. The PBIP project **does** load in the current Desktop; see `powerbi/README.md` for the open-and-refresh steps and the workaround. |

---

## Phase 7 — Validation

**Goal.** Prove the numbers, and prove the pipeline is honest.

**Plan.** 30 automated checks in `tests/test_analysis.py`:

- **Structural** — published row counts, referential integrity, key uniqueness,
  no negative or null amounts, fact-vs-view reconciliation.
- **Financial identities** — cash = Σ payments; expected charge = GMV + freight;
  net revenue = cash − exposure; the break flag agrees with the R$ 0.01
  tolerance computed independently.
- **Regression-locked figures** — the headline totals, the like-for-like growth
  rates, the instalment exposure, the seller HHI.
- **Behavioural** — the dispute gradient is monotone; the cost-model
  sensitivity brackets the base rate; contribution stays positive.
- **Cross-deliverable** — the CSV KPI summary matches the JSON metrics; the
  Power BI report references only measures and columns that exist; no measure
  shadows a column; every report file is present and non-trivial; no report
  contains an unmeasured impact claim.

---

## Phase 8 — Documentation

`README.md` for the portfolio reader, `docs/methodology.md` for the analyst,
`docs/implementation_plan.md` (this file) for the builder, `data/README.md`
for the data dictionary, and `powerbi/README.md` for the BI handoff.

---

## What I would do next

1. **Replace the proxies with the real tables.** Refund transactions and
   chargebacks would turn two proxies into measurements and would let the
   reserve policy be set on data rather than on an estimate.
2. **Build the recurring close pack.** The pipeline is already
   parameterised by month; the monthly manager's pack should be a scheduled
   run of it, not a manual rebuild.
3. **Add logistics cost and gross margin.** Without them, freight ratio and
   contribution stay proxies and the cost-to-serve model stays partial.
4. **Instrument the transaction anomaly score.** A composite risk score
   (reconciliation break × instalment depth × freight-to-price ratio × basket
   size vs category norm) would turn a one-off exception list into a control
   that runs on every close.
