"""Run the whole pipeline end to end.

    python src/run_all.py

Stages
------
    1  fetch_data.py           download the source CSVs (skipped if present)
    2  build_db.py             load the warehouse and build the analytic layer
    3  clean_data.py           publish the cleaned tables and analysis extracts
    4  run_queries.py          execute the documented SQL and write the audit trail
    5  analyze.py              compute the findings and render the reports
    6  build_powerbi_data.py   publish the Power BI star schema
    7  build_powerbi_model.py  generate the Power BI project (PBIP)
    8  build_excel.py          build the Excel workbook
    9  make_figures.py         render the report figures
    10 build_pbit.py           compile the Power BI template (optional)

Every stage is idempotent: re-running the pipeline reproduces the same
outputs from the same inputs.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent


def run(script: str, label: str, optional: bool = False) -> bool:
    print(f"\n{'=' * 78}\n{label}\n{'=' * 78}")
    started = time.time()
    path = SRC_DIR / script
    if not path.exists():
        path = PROJECT_ROOT / script
    result = subprocess.run(
        [sys.executable, "-u", str(path)],
        cwd=PROJECT_ROOT,
    )
    elapsed = time.time() - started
    if result.returncode != 0:
        if optional:
            print(f"[run_all] {label} skipped (exit {result.returncode}) after {elapsed:.1f}s")
            return False
        print(f"[run_all] {label} FAILED after {elapsed:.1f}s")
        sys.exit(result.returncode)
    print(f"[run_all] {label} finished in {elapsed:.1f}s")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-fetch", action="store_true",
        help="do not attempt to download the source data (it must already be in data/raw)",
    )
    parser.add_argument(
        "--skip-pbit", action="store_true",
        help="do not compile the Power BI template",
    )
    args = parser.parse_args()

    if not args.skip_fetch:
        run("fetch_data.py", "1/10  Fetch the source data")
    else:
        print("\n[run_all] 1/10  Fetch skipped")

    run("build_db.py", "2/10  Build the warehouse and the analytic layer")
    run("clean_data.py", "3/10  Publish the cleaned tables")
    run("run_queries.py", "4/10  Execute the analysis SQL")
    run("analyze.py", "5/10  Compute the findings and render the reports")
    run("build_powerbi_data.py", "6/10  Publish the Power BI star schema")
    run("build_powerbi_model.py", "7/10  Generate the Power BI project")
    run("build_excel.py", "8/10  Build the Excel workbook")
    run("make_figures.py", "9/10  Render the report figures")

    if args.skip_pbit:
        print("\n[run_all] 10/10 Power BI template skipped")
    else:
        run("powerbi/build_pbit.py", "10/10 Compile the Power BI template", optional=True)

    print(f"\n{'=' * 78}")
    print("Pipeline complete. Deliverables:")
    for relative in [
        "marketplace_finance.db",
        "excel/Marketplace_Financial_Ops_Dashboard.xlsx",
        "powerbi/MarketplaceFinance.pbit",
        "powerbi/MarketplaceFinance/MarketplaceFinance.pbip",
        "reports/executive_summary.md",
        "reports/findings.md",
        "reports/business_decision_report.md",
        "reports/sql_results.md",
        "reports/data_quality.md",
    ]:
        path = PROJECT_ROOT / relative
        marker = "ok " if path.exists() else "-- "
        size = f"{path.stat().st_size:,} bytes" if path.exists() else "not built"
        print(f"  {marker} {relative:60s} {size}")
    print("=" * 78)


if __name__ == "__main__":
    main()
