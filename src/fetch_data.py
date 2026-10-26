"""Download the Olist source CSVs into data/raw/.

The dataset is a public release by Olist. The canonical distribution is the
Kaggle page; the files below are fetched from Olist's own public GitHub
repository (`olist/work-at-olist-data`), which publishes the same CSVs under
the same names. Both references are recorded in data/README.md.

SHA-256 digests are verified after download so a partial or substituted file
cannot silently enter the pipeline.

Usage:
    python src/fetch_data.py
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

MIRROR_BASE = "https://raw.githubusercontent.com/olist/work-at-olist-data/master/datasets/"

EXPECTED_SHA256 = {
    "olist_customers_dataset.csv": "c26c17f59f3027a6a0dbeb8f1fa373c38f3323ecc84f225a8f4820e5bb288df8",
    "olist_order_items_dataset.csv": "4f6abdbbc94036d0df4a76fa0520c072e31a40119d70f7f370fba1e2285d2bcb",
    "olist_order_payments_dataset.csv": "61674868ed7b872aac3dcd95bf774448a88f6426b183f21be55f75af021ffdec",
    "olist_order_reviews_dataset.csv": "012b61c7593e34f51fa614efdf802b9c7056ce6aae5307ddb93236e7cfc797d7",
    "olist_orders_dataset.csv": "8df58ef3d2d7e9944010f7beecd9b75367f5588ec6e3c91cec19ae3345ef9ecf",
    "olist_products_dataset.csv": "3e6569628a17fbc75fd206ee357b59e20364b9afa90f5b6cd5b4d624c58aa9cc",
    "olist_sellers_dataset.csv": "31eb9bd50d684526a78f2389413ce61841e97692de7b828fe7d956b534586312",
    "product_category_name_translation.csv": "a81f0d1f27b27e7293f761bc79e3ce8f348ee39c4b3ed3e49bde38f478586278",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(filename: str) -> Path:
    target = config.RAW_DIR / filename
    if target.exists():
        print(f"[fetch] {filename}: already present ({target.stat().st_size:,} bytes)")
        return target
    url = MIRROR_BASE + filename
    print(f"[fetch] {filename} <- {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = response.read()
    target.write_bytes(payload)
    print(f"[fetch] {filename}: {len(payload):,} bytes written")
    return target


def main() -> None:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    for filename in config.RAW_TABLES.values():
        path = fetch(filename)
        digest = sha256(path)
        expected = EXPECTED_SHA256.get(filename)
        status = "unverified (no reference digest recorded)" if expected is None else (
            "OK" if digest == expected else "MISMATCH"
        )
        print(f"[fetch] {filename}: sha256={digest[:16]}... {status}")


if __name__ == "__main__":
    main()
