# Data

## `data/raw/` — the source, untouched

Eight CSVs, downloaded by `python src/fetch_data.py` and verified by SHA-256
digest. Nothing in this folder is modified by the pipeline.

> **Not committed to the repository.** The raw CSVs are ~61 MB and are
> redistributed under the Olist licence; the fetch script verifies each
> file's digest, so a reviewer gets byte-identical data with one command:
> `python src/fetch_data.py`.

| File | Rows | Size | SHA-256 (first 16) |
|---|---:|---:|---|
| `olist_customers_dataset.csv` | 99,441 | 8,562,270 | `c26c17f59f3027a6` |
| `olist_order_items_dataset.csv` | 112,650 | 15,007,623 | `4f6abdbbc94036d0` |
| `olist_order_payments_dataset.csv` | 103,886 | 5,647,783 | `61674868ed7b872a` |
| `olist_order_reviews_dataset.csv` | 99,224 | 14,451,670 | `012b61c7593e34f5` |
| `olist_orders_dataset.csv` | 99,441 | 17,654,914 | `8df58ef3d2d7e994` |
| `olist_products_dataset.csv` | 32,951 | 2,379,446 | `3e6569628a17fbc7` |
| `olist_sellers_dataset.csv` | 3,095 | 163,589 | `31eb9bd50d684526` |
| `product_category_name_translation.csv` | 71 | 2,613 | `a81f0d1f27b27e72` |

**Provenance.** Brazilian E-Commerce Public Dataset by Olist. Canonical
distribution: [Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce).
Files retrieved from Olist's own public repository,
[`olist/work-at-olist-data`](https://github.com/olist/work-at-olist-data/tree/master/datasets),
which publishes the same CSVs under the same names.

**Licence.** CC BY-NC-SA 4.0 — non-commercial use, attribution and share-alike
required.

**Nature.** Real commercial data from a Brazilian marketplace, anonymised by
Olist: names, contacts and addresses replaced; transaction economics preserved.
Company names inside review text were replaced with *Game of Thrones* house
names. **Not synthetic, not simulated.**

---

## Field dictionary

### `customers` — 99,441 rows, one row per customer profile

| Field | Type | Notes |
|---|---|---|
| `customer_id` | text | Primary key. **Not a reliable person key** — see the note below. |
| `customer_unique_id` | text | The person key. 96,096 distinct values across 99,441 rows. |
| `customer_zip_code_prefix` | int | First five digits of the postal code |
| `customer_city` | text | Delivery city, lower-cased at load |
| `customer_state` | text | Delivery state (27 states), lower-cased at load |

> **Identity fragmentation.** 2,997 real customers appear under more than one
> `customer_id`; one appears under 17. Counting customers on `customer_id`
> overstates the base by 3.5% and understates the repeat rate. Every customer
> metric in this project uses `customer_unique_id`.

### `orders` — 99,441 rows, one row per order

| Field | Type | Notes |
|---|---|---|
| `order_id` | text | Primary key |
| `customer_id` | text | Foreign key → `customers` |
| `order_status` | text | `delivered`, `shipped`, `canceled`, `unavailable`, `invoiced`, `processing`, `created`, `approved` |
| `order_purchase_timestamp` | timestamp | Order placed. The analysis date spine |
| `order_approved_at` | timestamp | Payment approved |
| `order_delivered_carrier_date` | timestamp | Handed to the carrier |
| `order_delivered_customer_date` | timestamp | Delivered to the customer |
| `order_estimated_delivery_date` | timestamp | The promise date |

> **775 orders carry no line items at all** (164 `canceled`, 603 `unavailable`,
> 8 in flight). 772 of them have cash collected — R$ 162,591.95. They are kept
> and flagged, never deleted.

### `order_items` — 112,650 rows, one row per line item

| Field | Type | Notes |
|---|---|---|
| `order_id` | text | Foreign key → `orders` |
| `order_item_id` | int | Line sequence within the order. Composite key with `order_id` |
| `product_id` | text | Foreign key → `products` |
| `seller_id` | text | Foreign key → `sellers` |
| `shipping_limit_date` | timestamp | Seller dispatch deadline |
| `price` | decimal | **Merchandise value** of the item |
| `freight_value` | decimal | **Freight charged** to the customer for the item |

> 4,119 items (3.66%) have a freight charge larger than the merchandise value,
> by R$ 27,659.95 in aggregate.

### `payments` — 103,886 rows, one row per payment transaction

| Field | Type | Notes |
|---|---|---|
| `order_id` | text | Foreign key → `orders`. 99,440 of the 99,441 orders carry at least one payment row |
| `payment_sequential` | int | Sequence of the payment on the order. Composite key with `order_id` |
| `payment_type` | text | `credit_card`, `boleto`, `voucher`, `debit_card`, `not_defined` |
| `payment_installments` | int | Instalment count. `0` → NULL (2 rows, on `not_defined` payments only). Maximum 24 |
| `payment_value` | decimal | Amount collected. Nine rows are zero |

> **There is no payment date, no settlement date and no refund record.** Cash
> timing cannot be analysed, and refund exposure can only be inferred from
> order status.

### `reviews` — 99,224 rows

| Field | Type | Notes |
|---|---|---|
| `review_id` | text | **Not unique** — 789 ids each appear against two orders of the same customer, with identical score, text and timestamps |
| `order_id` | text | Foreign key → `orders`. Composite key with `review_id` |
| `review_score` | int | 1–5. **1 or 2 is treated as a dispute proxy** |
| `review_comment_title` | text | Free text |
| `review_comment_message` | text | Free text, in Brazilian Portuguese |
| `review_creation_date` | date | When the customer wrote the review |
| `review_answer_timestamp` | timestamp | When the seller answered |

> 547 orders carry more than one review row, so the table must be aggregated
> before use. Order-level attribution keeps every link; review-level counts use
> `COUNT(DISTINCT review_id)`.

### `products` — 32,951 rows

| Field | Type | Notes |
|---|---|---|
| `product_id` | text | Primary key |
| `product_category_name` | text | Portuguese category. 13 products have no English translation |
| `product_name_lenght` | int | *Source spelling* — character count of the name |
| `product_description_lenght` | int | Character count of the description |
| `product_photos_qty` | int | Number of photos |
| `product_weight_g` | int | Weight in grams |
| `product_length_cm`, `product_height_cm`, `product_width_cm` | int | Dimensions in centimetres |

### `sellers` — 3,095 rows

| Field | Type | Notes |
|---|---|---|
| `seller_id` | text | Primary key |
| `seller_zip_code_prefix` | int | First five digits of the postal code |
| `seller_city` | text | Lower-cased at load |
| `seller_state` | text | Lower-cased at load. São Paulo hosts 1,849 sellers and 64.4% of GMV |

### `product_category_name_translation` — 71 rows

| Field | Type | Notes |
|---|---|---|
| `product_category_name` | text | Portuguese category. Primary key |
| `product_category_name_english` | text | English label used throughout the analysis |

---

## `data/processed/` — analysis-ready outputs

Written by `src/clean_data.py`. None of these files edit an amount; they are
re-cuts of the warehouse at the grain each analysis needs. Git-ignored —
regenerate with `python src/clean_data.py`.

| File | Rows | Grain |
|---|---:|---|
| `clean_orders.csv` | 99,441 | one row per order, every financial measure as a column |
| `clean_payments.csv` | 103,886 | one row per payment, with refund exposure and instalment credit flagged |
| `clean_order_items.csv` | 112,650 | one row per line item, joined to product, seller and category |
| `monthly_financials.csv` | 25 | one row per calendar month, with `month_coverage` flagging the partial months |
| `payment_method_financials.csv` | 5 | one row per payment method, with the modelled cost columns |
| `seller_concentration.csv` | 3,095 | one row per seller with GMV rank and cumulative share |
| `reconciliation_breaks.csv` | 1,220 | the exception list, largest break first |
| `kpi_summary.csv` | 12 | the twelve headline KPIs with their basis |
| `cleaning_log.csv` | 7 | the seven cleaning rules, their rationale and reversibility |

---

## `powerbi/MarketplaceFinance/Data/` — the BI star schema

Written by `src/build_powerbi_data.py`. Git-ignored — regenerate with
`python src/build_powerbi_data.py`.

| File | Rows | Grain |
|---|---:|---|
| `FactOrder.csv` | 99,441 | one row per order — the financial fact |
| `FactPayment.csv` | 103,886 | one row per payment |
| `FactOrderItem.csv` | 112,650 | one row per line item |
| `DimDate.csv` | 774 | one row per calendar day |
| `DimCustomer.csv` | 96,096 | one row per real customer (`customer_unique_id`) |
| `DimSeller.csv` | 3,095 | one row per seller |
| `DimProduct.csv` | 32,951 | one row per product |
| `DimPaymentMethod.csv` | 5 | one row per payment method, carrying the modelled rates |
