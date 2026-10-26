# Power Query definitions

The eight queries behind the star schema. Every one reads a CSV from the
project's own `Data/` folder, types its columns explicitly and sorts on its
key. They are generated from `src/build_powerbi_model.py`, so the expressions
here and the model in `model.bim` are the same object.

---

## 1. The pattern

```powerquery
let
    DataFolder = #"Data",
    Source = Csv.Document(
        File.Contents(DataFolder & "\\FactOrder.csv"),
        [Delimiter = ",", Columns = 34, Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    #"Changed Type" = Table.TransformColumnTypes(Source, {
        {"OrderKey", type text},
        {"DateKey", Int64.Type},
        {"CashCollected", type number},
        ...
    }),
    #"Sorted Rows" = Table.Sort(#"Changed Type", {{"OrderKey", Order.Ascending}})
in
    #"Sorted Rows"
```

Three things are deliberate:

- **`DataFolder` is a single literal at the top of every query.** Repointing the
  data source is one edit in eight places, or a single find-and-replace.
- **`Columns` and `Encoding` are stated explicitly** so the reader does not
  depend on the machine's regional delimiter or code page. `Encoding = 65001`
  is UTF-8.
- **Every column is typed.** Without this, Power BI infers a type from the
  first row and silently turns an id column into a number, which would break
  the joins.

---

## 2. The queries

| Query | Source | Rows | Sorted on |
|---|---|---:|---|
| `FactOrder` | `Data/FactOrder.csv` | 99,441 | `OrderKey` |
| `FactPayment` | `Data/FactPayment.csv` | 103,886 | `OrderKey` |
| `FactOrderItem` | `Data/FactOrderItem.csv` | 112,650 | `OrderKey` |
| `DimDate` | `Data/DimDate.csv` | 774 | `full_date` |
| `DimCustomer` | `Data/DimCustomer.csv` | 96,096 | `CashCollected` desc |
| `DimSeller` | `Data/DimSeller.csv` | 3,095 | `GMVRank` |
| `DimProduct` | `Data/DimProduct.csv` | 32,951 | `ProductKey` |
| `DimPaymentMethod` | `Data/DimPaymentMethod.csv` | 5 | `PaymentMethodKey` |

---

## 3. Type mapping

| CSV column family | Power Query type | DAX type in the model |
|---|---|---|
| `*Key`, `*_id`, `OrderStatus`, `StatusClass`, `PaymentMethodKey`, category and state names | `type text` | `string` |
| `DateKey`, counts, flags, ranks, `MaxInstallments`, `ReviewCount` | `Int64.Type` | `int64` |
| money (`GMV`, `CashCollected`, `Freight`, `PaymentValue`, `NetRevenue`, …) | `type number` | `double` |
| `full_date`, `month_start`, `FirstPurchaseDate`, `LastPurchaseDate` | `type date` | `dateTime` |

`DateKey` is a `yyyyMMdd` integer, which is the join key to `DimDate` and is
also the column the time-intelligence measures filter on.

---

## 4. Where the data comes from

The CSVs in `powerbi/MarketplaceFinance/Data/` are written by
`src/build_powerbi_data.py` from the SQLite warehouse built by
`src/build_db.py`. The chain is:

```
data/raw/*.csv  (Olist source, untouched)
      -> src/build_db.py        -> marketplace_finance.db
      -> src/build_powerbi_data.py -> powerbi/MarketplaceFinance/Data/*.csv
      -> src/build_powerbi_model.py -> model.bim + report.json
```

Nothing is hand-typed into the model: the schema in
`src/build_powerbi_model.py` drives the M expressions, the column list and the
DAX measures at the same time, and `tests/test_analysis.py` asserts that every
field a visual references actually exists in the model.

---

## 5. Refreshing

1. Open `powerbi/MarketplaceFinance/MarketplaceFinance.pbip` in Power BI Desktop.
2. `Home > Refresh`.
3. If the source path is not resolved, open `Transform data` and use
   `Home > Change Source` on each query, pointing at
   `powerbi/MarketplaceFinance/Data/`.

The refresh loads 8 tables and roughly 456,000 rows. The heaviest is
`FactOrderItem` at 112,650 rows; the model is comfortably small for a Desktop
workbook.

---

## 6. If the model is opened from a different folder

The path is relative (`Data\...`), so the `Data` folder must sit beside the
project. To make the model portable, either:

- keep `MarketplaceFinance/` as one folder and move it as a unit, or
- edit the `DataFolder` literal in each of the eight queries to an absolute
  path.

For a published template, the third option is to replace the CSV source with an
embedded dataset (Power Query → *Keep Rows* → *Merge Queries* is not enough;
the file must be embedded via the model settings), which is what Power BI
Desktop's own `Save as .pbit` does automatically.
