-- ===========================================================================
--  01_schema.sql  |  Olist Marketplace - Financial Operations & Revenue Analytics
-- ---------------------------------------------------------------------------
--  Physical layer: the eight Olist source tables, loaded verbatim from
--  data/raw/*.csv with explicit types and keys.
--
--  DESIGN NOTES
--  * Timestamps are stored as TEXT in ISO-8601 'YYYY-MM-DD HH:MM:SS' form.
--    SQLite's date()/strftime() functions parse that form natively, which
--    keeps the layer portable and readable inside Power BI's SQL connector
--    and inside Excel (via the ODBC/Text driver).
--  * Money is stored as REAL. The source amounts carry 2 decimal places, so
--    no rounding is lost. Reconciliation comparisons apply a tolerance of
--    R$ 0.01 (config.RECON_TOLERANCE) to absorb binary floating point noise.
--  * No row is filtered, de-duplicated or re-valued here. Cleaning happens in
--    the cleaning rules table `dq_cleaning_rules` and in src/clean_data.py.
-- ===========================================================================

PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_category_financials;
DROP VIEW  IF EXISTS v_seller_performance;
DROP VIEW  IF EXISTS v_item_financials;
DROP VIEW  IF EXISTS v_payment_detail;
DROP VIEW  IF EXISTS v_order_financials;
DROP VIEW  IF EXISTS dim_date;
DROP TABLE IF EXISTS dq_cleaning_rules;
DROP TABLE IF EXISTS product_category_translation;
DROP TABLE IF EXISTS sellers;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;

-- ---------------------------------------------------------------------------
-- customers : one row per customer *profile*. A repeat buyer may appear as
-- several customer_id values sharing one customer_unique_id (a known
-- fragmentation in the source data - measured, not assumed, in 04).
-- ---------------------------------------------------------------------------
CREATE TABLE customers (
    customer_id             TEXT PRIMARY KEY,
    customer_unique_id      TEXT NOT NULL,
    customer_zip_code_prefix INTEGER,
    customer_city           TEXT,
    customer_state          TEXT
);

-- ---------------------------------------------------------------------------
-- orders : the order header. This is the spine for every financial figure.
-- ---------------------------------------------------------------------------
CREATE TABLE orders (
    order_id                       TEXT PRIMARY KEY,
    customer_id                    TEXT NOT NULL REFERENCES customers(customer_id),
    order_status                   TEXT NOT NULL,
    order_purchase_timestamp       TEXT NOT NULL,
    order_approved_at              TEXT,
    order_delivered_carrier_date   TEXT,
    order_delivered_customer_date  TEXT,
    order_estimated_delivery_date  TEXT
);

CREATE INDEX idx_orders_customer  ON orders(customer_id);
CREATE INDEX idx_orders_status    ON orders(order_status);
CREATE INDEX idx_orders_purchase  ON orders(order_purchase_timestamp);

-- ---------------------------------------------------------------------------
-- order_items : line items. price = merchandise value sold to the customer,
-- freight_value = logistics charge collected from the customer.
-- ---------------------------------------------------------------------------
CREATE TABLE order_items (
    order_id          TEXT NOT NULL REFERENCES orders(order_id),
    order_item_id     INTEGER NOT NULL,
    product_id        TEXT REFERENCES products(product_id),
    seller_id         TEXT REFERENCES sellers(seller_id),
    shipping_limit_date TEXT,
    price             REAL NOT NULL,
    freight_value     REAL NOT NULL,
    PRIMARY KEY (order_id, order_item_id)
);

CREATE INDEX idx_items_order   ON order_items(order_id);
CREATE INDEX idx_items_seller  ON order_items(seller_id);
CREATE INDEX idx_items_product ON order_items(product_id);

-- ---------------------------------------------------------------------------
-- payments : what the customer actually paid. A minority of orders carry more
-- than one payment row (split payment). There is NO payment date, NO
-- settlement date and NO refund record in the source - a hard limitation on
-- any cash-timing analysis, documented in docs/methodology.md.
-- ---------------------------------------------------------------------------
CREATE TABLE payments (
    order_id             TEXT NOT NULL REFERENCES orders(order_id),
    payment_sequential   INTEGER NOT NULL,
    payment_type         TEXT NOT NULL,
    payment_installments INTEGER,
    payment_value        REAL NOT NULL,
    PRIMARY KEY (order_id, payment_sequential)
);

CREATE INDEX idx_payments_order  ON payments(order_id);
CREATE INDEX idx_payments_type   ON payments(payment_type);

-- ---------------------------------------------------------------------------
-- reviews : post-delivery satisfaction survey. review_score is the only
-- outcome signal in the dataset and is used as a dispute / chargeback proxy.
--
-- NOTE on the key: 789 review_id values in the source are each recorded
-- against TWO different orders belonging to the same customer, with
-- identical score, text and timestamps - one review submission duplicated
-- across two orders. The natural key of a review ROW is therefore
-- (review_id, order_id), not review_id. All rows are retained: both
-- order-level links are real (the customer did review both orders).
-- Review-LEVEL counts use COUNT(DISTINCT review_id) - see V-REV-DUPID.
-- ---------------------------------------------------------------------------
CREATE TABLE reviews (
    review_id             TEXT NOT NULL,
    order_id              TEXT NOT NULL REFERENCES orders(order_id),
    review_score          INTEGER,
    review_comment_title  TEXT,
    review_comment_message TEXT,
    review_creation_date  TEXT,
    review_answer_timestamp TEXT,
    PRIMARY KEY (review_id, order_id)
);

CREATE INDEX idx_reviews_order ON reviews(order_id);
CREATE INDEX idx_reviews_id    ON reviews(review_id);

CREATE TABLE products (
    product_id             TEXT PRIMARY KEY,
    product_category_name  TEXT,
    product_name_lenght    REAL,
    product_description_lenght REAL,
    product_photos_qty     REAL,
    product_weight_g       REAL,
    product_length_cm      REAL,
    product_height_cm      REAL,
    product_width_cm       REAL
);

CREATE TABLE sellers (
    seller_id             TEXT PRIMARY KEY,
    seller_zip_code_prefix INTEGER,
    seller_city           TEXT,
    seller_state          TEXT
);

CREATE TABLE product_category_translation (
    product_category_name        TEXT PRIMARY KEY,
    product_category_name_english TEXT
);

-- ---------------------------------------------------------------------------
-- dq_cleaning_rules : audit trail of every rule applied to the data, with the
-- number of records each rule touched. Written by src/build_db.py from the
-- same constants the Python pipeline uses, so the audit cannot drift.
-- ---------------------------------------------------------------------------
CREATE TABLE dq_cleaning_rules (
    rule_id     INTEGER PRIMARY KEY,
    rule_code   TEXT NOT NULL,
    table_name  TEXT NOT NULL,
    rule_description TEXT NOT NULL,
    rule_type   TEXT NOT NULL,          -- 'validation' | 'standardisation' | 'exclusion'
    action_taken TEXT NOT NULL,
    records_in INTEGER,
    records_out INTEGER,
    records_affected INTEGER
);

-- ---------------------------------------------------------------------------
-- fact_order_financials : the MATERIALISED order-level fact.
--
-- `v_order_financials` (sql/02_views.sql) is the definition; this table is
-- its snapshot, rebuilt from it on every run by src/build_db.py and indexed
-- for aggregation. The analysis queries read this table so that a 99,441-row
-- order-level fact is not re-aggregated from three child tables on every
-- read. `dq13_fact_table_reconciliation` proves the two agree.
--
-- The table is created with CREATE TABLE ... AS SELECT by src/build_db.py
-- rather than declared here, because its shape is defined by the view.
-- ---------------------------------------------------------------------------
