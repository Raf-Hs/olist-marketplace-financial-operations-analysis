"""Render the figures used in the README and the markdown reports.

These are supporting exhibits, not the deliverable: the Excel workbook and
the Power BI model carry the interactive versions. Every figure is drawn from
`reports/key_metrics.json` and the processed CSVs, so a figure can never show
a number the report does not.

Usage:
    python src/make_figures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

NAVY = "#1F3B57"
TEAL = "#2A9D8F"
SAND = "#E9C46A"
ORANGE = "#F4A261"
RED = "#E76F51"
GREY = "#8D99AE"
LIGHT = "#F4F1EC"

plt.rcParams.update(
    {
        "figure.dpi": 130,
        "savefig.dpi": 130,
        "font.family": "DejaVu Sans",
        "axes.edgecolor": "#CCCCCC",
        "axes.labelcolor": NAVY,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.titlecolor": NAVY,
        "xtick.color": "#555555",
        "ytick.color": "#555555",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    }
)


def _save(fig, name: str) -> None:
    config.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = config.FIGURES_DIR / f"{name}.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"[make_figures] wrote {path.name}")


def fig_monthly(metrics: dict) -> None:
    monthly = pd.DataFrame(metrics["monthly"])
    monthly = monthly[monthly["purchase_month"] >= "2017-01-01"]
    monthly = monthly[monthly["purchase_month"] <= "2018-08-01"]

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                             gridspec_kw={"height_ratios": [2, 1]})

    ax = axes[0]
    ax.plot(monthly["purchase_month"], monthly["cash"], color=NAVY,
            linewidth=2.2, marker="o", markersize=4, label="Cash collected")
    ax.plot(monthly["purchase_month"], monthly["gmv"], color=TEAL,
            linewidth=1.8, linestyle="--", label="GMV (merchandise value)")
    ax.set_ylabel("BRL")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda v, _: f"{v / 1_000_000:.1f}M"))
    ax.legend(frameon=False, loc="upper left")
    ax.set_title("Cash collected and GMV by month (Jan 2017 - Aug 2018)")
    ax.grid(axis="y", color=LIGHT)
    ax.set_axisbelow(True)

    ax2 = axes[1]
    colours = [RED if v > 2.0 else (ORANGE if v > 1.0 else TEAL)
               for v in monthly["refund_exposure_pct"]]
    ax2.bar(monthly["purchase_month"], monthly["refund_exposure_pct"], color=colours)
    ax2.set_ylabel("Refund exposure\n(% of cash collected)")
    ax2.tick_params(axis="x", rotation=60, labelsize=8)
    ax2.grid(axis="y", color=LIGHT)
    ax2.set_axisbelow(True)
    ax2.set_title("Refund exposure rate by month")
    fig.tight_layout()
    _save(fig, "01_monthly_cash_and_refund_exposure")


def fig_payment_mix(metrics: dict) -> None:
    mix = pd.DataFrame(metrics["payment_mix"])
    cost = pd.DataFrame(metrics["cost_model"]["by_method"])

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    ax = axes[0]
    colours = [NAVY, TEAL, SAND, ORANGE, GREY]
    ax.bar(mix["payment_type"], mix["pct_of_value"], color=colours[:len(mix)])
    for i, v in enumerate(mix["pct_of_value"]):
        ax.text(i, v + 0.7, f"{v:.2f}%", ha="center", fontsize=9, color=NAVY)
    ax.set_ylabel("% of collected value")
    ax.set_title("Collected value by payment method")
    ax.grid(axis="y", color=LIGHT)
    ax.set_axisbelow(True)

    ax2 = axes[1]
    bottom = 0.0
    acquiring = cost["acquiring_cost"].tolist()
    funding = cost["installment_funding_cost"].tolist()
    x = range(len(cost))
    ax2.bar(x, acquiring, color=TEAL, label="Acquiring (modelled)")
    ax2.bar(x, funding, bottom=acquiring, color=RED, label="Instalment funding (modelled)")
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(cost["payment_type"], fontsize=9)
    ax2.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda v, _: f"{v / 1000:.0f}k"))
    ax2.set_ylabel("BRL")
    ax2.set_title("Modelled payment cost by method")
    ax2.legend(frameon=False, fontsize=9)
    ax2.grid(axis="y", color=LIGHT)
    ax2.set_axisbelow(True)
    fig.tight_layout()
    _save(fig, "02_payment_mix_and_modelled_cost")


def fig_reconciliation(metrics: dict) -> None:
    structure = pd.DataFrame(metrics["break_structure"])
    short_band = {
        "a. rounding (< R$1)": "< R$1",
        "b. R$1 - R$100": "R$1-100",
        "c. R$100 - R$1,000": "R$100-1k",
        "d. R$1,000+": "R$1,000+",
    }
    labels = [
        f"{'no items' if reason == 'no line items at all' else 'has items'}\n{short_band[band]}"
        for reason, band in zip(structure["break_reason"], structure["size_band"])
    ]
    colours = [RED if reason == "no line items at all" else ORANGE
               for reason in structure["break_reason"]]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    ax = axes[0]
    ax.bar(labels, structure["absolute_break"], color=colours)
    ax.set_ylabel("Absolute break value (BRL)")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda v, _: f"{v / 1000:.0f}k"))
    ax.set_title("Where the cash-to-revenue break sits")
    ax.tick_params(axis="x", labelsize=7)
    ax.grid(axis="y", color=LIGHT)
    ax.set_axisbelow(True)

    ax2 = axes[1]
    months = pd.DataFrame(metrics["monthly"])
    months = months[(months["purchase_month"] >= "2017-01-01")
                     & (months["purchase_month"] <= "2018-08-01")]
    ax2.plot(months["purchase_month"], months["refund_exposure_pct"],
             color=RED, marker="o", markersize=4, linewidth=1.8)
    ax2.set_ylabel("Refund exposure (% of cash collected)")
    ax2.set_title("Refund exposure rate by month")
    ax2.tick_params(axis="x", rotation=60, labelsize=8)
    ax2.grid(axis="y", color=LIGHT)
    ax2.set_axisbelow(True)
    fig.tight_layout()
    _save(fig, "03_reconciliation_break_and_exposure")


def fig_concentration(metrics: dict) -> None:
    sellers = pd.read_csv(config.PROCESSED_FILES["seller_concentration"])
    top = sellers.head(300)

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(top["gmv_rank"], top["cumulative_pct_of_gmv"], color=NAVY, linewidth=2.2)
    ax.axhline(80, color=RED, linestyle=":", linewidth=1.4)
    ax.text(230, 81, "80% of GMV", color=RED, fontsize=9)
    ax.set_xlabel("Seller rank")
    ax.set_ylabel("Cumulative % of GMV")
    ax.set_title("Seller concentration curve - the 80% of GMV sits with "
                 f"{int((top['cumulative_pct_of_gmv'] < 80).sum())} sellers")
    ax.grid(color=LIGHT)
    ax.set_axisbelow(True)
    fig.tight_layout()
    _save(fig, "04_seller_concentration_curve")


def fig_logistics(metrics: dict) -> None:
    categories = pd.DataFrame(metrics["category_freight"])
    top = categories.head(14).sort_values("freight_ratio_pct")

    fig, ax = plt.subplots(figsize=(10, 6))
    colours = [RED if v >= 20 else (ORANGE if v >= 16 else TEAL)
               for v in top["freight_ratio_pct"]]
    ax.barh(top["category_english"], top["freight_ratio_pct"], color=colours)
    ax.set_xlabel("Freight collected as % of merchandise value")
    ax.set_title("Logistics burden by product category (heaviest first)")
    ax.grid(axis="x", color=LIGHT)
    ax.set_axisbelow(True)
    fig.tight_layout()
    _save(fig, "05_logistics_burden_by_category")


def fig_dispute(metrics: dict) -> None:
    dispute = pd.DataFrame(metrics["dispute_by_installments"])

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(dispute["instalment_bucket"], dispute["dispute_rate_pct"], color=NAVY)
    for bar, rate in zip(bars, dispute["dispute_rate_pct"]):
        ax.text(bar.get_x() + bar.get_width() / 2, rate + 0.35,
                f"{rate:.2f}%", ha="center", fontsize=9, color=NAVY)
    ax.set_ylabel("Disputed orders (% of orders in the bucket)")
    ax.set_xlabel("Card instalment depth")
    ax.set_title("Dispute rate rises with instalment depth")
    ax.grid(axis="y", color=LIGHT)
    ax.set_axisbelow(True)
    fig.tight_layout()
    _save(fig, "06_dispute_rate_by_instalment_depth")


def fig_growth(metrics: dict) -> None:
    y = metrics["yoy"]
    labels = ["Cash collected", "Orders", "Customers", "Average order value"]
    values = [y["cash_growth_pct"], y["orders_growth_pct"], y["customers_growth_pct"],
              y["aov_growth_pct"]]
    colours = [NAVY, TEAL, TEAL, SAND]

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(labels, values, color=colours)
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 2,
                f"+{v:.2f}%", ha="center", fontsize=10, color=NAVY)
    ax.set_ylabel("Year-on-year change (%)")
    ax.set_title("Like-for-like growth, Jan-Aug 2017 vs Jan-Aug 2018")
    ax.set_ylim(0, max(values) * 1.18)
    ax.grid(axis="y", color=LIGHT)
    ax.set_axisbelow(True)
    fig.tight_layout()
    _save(fig, "07_like_for_like_growth")


def fig_scorecard(metrics: dict) -> None:
    h = metrics["headline"]
    c = metrics["cost_model"]
    labels = ["GMV", "Cash collected", "Net revenue", "Refund exposure",
              "Settlement float", "Modelled payment cost"]
    values = [h["gmv"], h["cash_collected"], h["net_revenue"], h["refund_exposure"],
              h["settlement_float"], c["total_modelled_payment_cost"]]
    colours = [NAVY, TEAL, TEAL, RED, ORANGE, GREY]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(labels, values, color=colours)
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, v + max(values) * 0.02,
                f"R$ {v / 1_000_000:.2f}M", ha="center", fontsize=9, color=NAVY)
    ax.set_ylabel("BRL")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda v, _: f"{v / 1_000_000:.0f}M"))
    ax.set_title("Where the money is - measured against modelled")
    ax.set_ylim(0, max(values) * 1.18)
    ax.grid(axis="y", color=LIGHT)
    ax.set_axisbelow(True)
    fig.tight_layout()
    _save(fig, "08_financial_scorecard")


def main() -> None:
    metrics = json.loads(
        (config.REPORTS_DIR / "key_metrics.json").read_text(encoding="utf-8")
    )
    fig_scorecard(metrics)
    fig_monthly(metrics)
    fig_growth(metrics)
    fig_payment_mix(metrics)
    fig_reconciliation(metrics)
    fig_concentration(metrics)
    fig_logistics(metrics)
    fig_dispute(metrics)


if __name__ == "__main__":
    main()
