"""Build the Excel deliverable: `excel/Marketplace_Financial_Ops_Dashboard.xlsx`.

The brief asks for the analysis to be done with SQL and Excel. This module is
the Excel half: a self-contained workbook that carries the KPI scoreboard, the
monthly and quarterly financials, the payment-method economics, the
reconciliation exception list, the concentration and logistics cuts, and the
data-quality audit - with native Excel charts, so a reader can re-cut any
series without touching Python.

Native Excel charts (not pasted images) are used on purpose: the reader can
right-click any chart and "Edit Data" to point it at a different range.

Sheets
------
    README            how to read the workbook, metric definitions, assumptions
    KPI Scorecard     the twelve KPIs, their basis and their definition
    Monthly Financials 25 months of cash, GMV, AOV, refund exposure + charts
    Revenue & Growth  like-for-like year-on-year and month-on-month movement
    Payment Mix       method mix, instalment profile, modelled cost, sensitivity
    Refund Exposure   exposure by status and by month
    Reconciliation    the break summary and the exception list
    Seller Concentration  Pareto table + chart
    Category Logistics    freight burden by category + chart
    Dispute Risk      dispute rate by instalment depth + chart
    Data Quality      every check and its result
    Order Records     the cleaned order-level fact, ready to pivot

Run after `analyze.py`:

    python src/build_excel.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

# ---------------------------------------------------------------------------
# House styling
# ---------------------------------------------------------------------------
NAVY = "1F3B57"
TEAL = "2A9D8F"
SAND = "E9C46A"
ORANGE = "F4A261"
RED = "E76F51"
GREY = "8D99AE"
LIGHT = "F4F1EC"
WHITE = "FFFFFF"
DARK = "2B2D42"

THIN = Side(style="thin", color="D8D8D8")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

MONEY_FMT = 'R$ #,##0.00'
MONEY0_FMT = 'R$ #,##0'
PCT_FMT = '0.00"%"'
PCT1_FMT = '0.0"%"'
INT_FMT = '#,##0'
NUM2_FMT = '#,##0.00'

TITLE_FONT = Font(name="Calibri", size=16, bold=True, color=NAVY)
SUB_FONT = Font(name="Calibri", size=10, italic=True, color=GREY)
HDR_FONT = Font(name="Calibri", size=10, bold=True, color=WHITE)
BODY_FONT = Font(name="Calibri", size=10, color=DARK)
BOLD_FONT = Font(name="Calibri", size=10, bold=True, color=DARK)

HDR_FILL = PatternFill("solid", fgColor=NAVY)
BAND_FILL = PatternFill("solid", fgColor=LIGHT)
WARN_FILL = PatternFill("solid", fgColor=SAND)
BAD_FILL = PatternFill("solid", fgColor=RED)
GOOD_FILL = PatternFill("solid", fgColor=TEAL)


def _title(ws, title: str, subtitle: str, width: int = 10) -> int:
    ws["A1"] = title
    ws["A1"].font = TITLE_FONT
    ws["A2"] = subtitle
    ws["A2"].font = SUB_FONT
    for col in range(1, width + 1):
        ws.column_dimensions[get_column_letter(col)].width = 16
    return 4


def _header(ws, row: int, headers: list[str]) -> int:
    for i, head in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=i, value=head)
        cell.font = HDR_FONT
        cell.fill = HDR_FILL
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 30
    return row + 1


def _write_rows(ws, df: pd.DataFrame, start_row: int, formats: dict[str, str] | None = None,
                band: bool = True, minimal: bool = False) -> int:
    """Write a frame to the sheet.

    `minimal=True` writes the values and the number formats but skips the
    per-cell font and border. On the 99,441-row Order Records sheet that is
    the difference between about eight minutes and about one: styling every
    cell of a sheet that wide costs roughly four times more than writing it.
    """
    formats = formats or {}
    if minimal:
        for r, values in enumerate(df.itertuples(index=False, name=None)):
            excel_row = start_row + r
            for c, (value, col) in enumerate(zip(values, df.columns), start=1):
                if isinstance(value, (int, float)) and pd.isna(value):
                    value = None
                cell = ws.cell(row=excel_row, column=c, value=value)
                if col in formats:
                    cell.number_format = formats[col]
        return start_row + len(df)

    for r, (_, row) in enumerate(df.iterrows()):
        excel_row = start_row + r
        for c, col in enumerate(df.columns, start=1):
            value = row[col]
            if isinstance(value, (int, float)) and pd.isna(value):
                value = None
            cell = ws.cell(row=excel_row, column=c, value=value)
            cell.font = BODY_FONT
            cell.border = BORDER
            if col in formats:
                cell.number_format = formats[col]
            if band and r % 2 == 1:
                cell.fill = BAND_FILL
    return start_row + len(df)


def _autosize(ws, min_width: int = 10, max_width: int = 46) -> None:
    for column_cells in ws.columns:
        letter = get_column_letter(column_cells[0].column)
        longest = 0
        for cell in column_cells:
            if cell.value is not None:
                longest = max(longest, len(str(cell.value)))
        ws.column_dimensions[letter].width = max(min_width, min(longest + 2, max_width))


def _note(ws, row: int, text: str, width: int = 10) -> int:
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = SUB_FONT
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=row, start_column=1, end_row=row + 2, end_column=width)
    ws.row_dimensions[row].height = 30
    return row + 4


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------
def sheet_readme(wb: Workbook, metrics: dict) -> None:
    ws = wb.create_sheet("README")
    row = _title(
        ws,
        "Olist Marketplace - Financial Operations Dashboard",
        "Every figure is produced by the SQL layer in sql/ and reproduced by src/analyze.py. "
        "Refreshed by running src/run_all.py.",
        width=8,
    )
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 96

    blocks = [
        ("What this workbook is", ""),
        ("Business question",
         "How much money did the marketplace collect that it has not earned, what does the "
         "payment mix cost to serve, and where is the cash at risk?"),
        ("Stakeholder",
         "Head of Finance / Financial Operations Manager at an Olist-style Brazilian "
         "marketplace (third-party sellers, multiple payment methods, customer funds "
         "collected before seller settlement)."),
        ("Dataset",
         f"{config.DATASET_NAME} - {config.DATASET_NATURE}. {config.DATASET_LICENSE}. "
         f"{metrics['headline']['orders']:,} orders, "
         f"{metrics['headline']['unique_customers']:,} customers, "
         f"{metrics['headline']['first_order_date']} to {metrics['headline']['last_order_date']}."),
        ("Currency", f"{config.CURRENCY} (Brazilian reais). All money columns are R$."),
        ("Reporting window",
         f"{config.CLEAN_WINDOW_LABEL} for all trend and year-on-year analysis. The full "
         "window is used for lifetime totals because the first and last months are "
         "partial (4 orders in Sep 2016 and 4 in Oct 2018)."),
        ("", ""),
        ("Metric definitions", ""),
        ("GMV",
         "SUM(order_items.price) - merchandise value ordered. Excludes freight, excludes "
         "cancelled and unavailable orders only where line items are absent."),
        ("Cash collected",
         "SUM(payments.payment_value) - what customers actually paid, across every "
         "payment row."),
        ("Refund exposure",
         "Cash collected on orders whose status is cancelled or unavailable. The source "
         "data contains NO refund table, so this is an EXPOSURE PROXY, not a record of "
         "refunds paid."),
        ("Net revenue",
         "Cash collected less refund exposure. The measure the finance team should "
         "manage on."),
        ("Expected charge",
         "GMV + freight for the order. The amount the order should have cost."),
        ("Reconciliation break",
         "An order where ABS(cash_collected - expected_charge) >= R$ 0.01."),
        ("Average order value",
         "Cash collected / orders with a payment."),
        ("Freight ratio",
         "Freight collected / GMV. A logistics burden on the order, not a logistics "
         "margin - the dataset holds no carrier cost."),
        ("Disputed order",
         "An order whose worst review score is 1 or 2 out of 5. A PROXY for a chargeback "
         "or complaint; no dispute table exists in the source."),
        ("Seller HHI",
         "Sum of squared seller GMV shares. Below 0.15 is an unconcentrated market."),
        ("", ""),
        ("Measured vs modelled", ""),
        ("Measured",
         "Everything marked 'measured' in the KPI Scorecard is computed directly from the "
         "source data."),
        ("Modelled",
         "The cost-to-serve figures on the Payment Mix sheet use published Brazilian "
         "acquiring market rates. They are NOT facts about this marketplace. The "
         "assumptions and a sensitivity band are published on the Assumptions block of "
         "the same sheet."),
        ("", ""),
        ("How to work with this file", ""),
        ("Recalculate",
         "All charts are native Excel charts. Right-click > Edit Data to re-point any "
         "series at a different range."),
        ("Pivot",
         "The 'Order Records' sheet carries the cleaned order-level fact (one row per "
         "order, every financial measure as a column). Select any cell and use "
         "Insert > PivotTable to re-cut the analysis."),
        ("Source of truth",
         "sql/04..07 hold the analysis queries; reports/sql_results.md holds their "
         "output. The workbook is a presentation layer over both."),
    ]
    for label, text in blocks:
        if label and not text:
            cell = ws.cell(row=row, column=1, value=label)
            cell.font = Font(name="Calibri", size=12, bold=True, color=NAVY)
        elif label:
            cell = ws.cell(row=row, column=1, value=label)
            cell.font = BOLD_FONT
            cell.alignment = Alignment(vertical="top")
            body = ws.cell(row=row, column=2, value=text)
            body.font = BODY_FONT
            body.alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[row].height = 15 * (1 + len(text) // 95)
        row += 1
    ws.sheet_view.showGridLines = False


def sheet_kpi_scorecard(wb: Workbook, metrics: dict) -> None:
    ws = wb.create_sheet("KPI Scorecard")
    row = _title(
        ws,
        "KPI scoreboard",
        "Twelve headline metrics. 'Basis' separates what is measured from what is modelled.",
        width=5,
    )
    h = metrics["headline"]
    c = metrics["cost_model"]
    rows = [
        ("KPI 01", "GMV (merchandise value)", h["gmv"], "BRL", "measured",
         "SUM(order_items.price)"),
        ("KPI 02", "Cash collected", h["cash_collected"], "BRL", "measured",
         "SUM(payments.payment_value)"),
        ("KPI 03", "Refund exposure", h["refund_exposure"], "BRL", "measured (proxy)",
         "Cash on cancelled / unavailable orders"),
        ("KPI 04", "Net revenue", h["net_revenue"], "BRL", "measured",
         "Cash collected less refund exposure"),
        ("KPI 05", "Average order value", h["aov"], "BRL", "measured",
         "Cash collected / orders"),
        ("KPI 06", "Freight ratio", h["freight_ratio_pct"], "% of GMV", "measured",
         "Freight collected / GMV"),
        ("KPI 07", "Reconciliation break rate", h["reconciliation_break_rate_pct"], "% of orders",
         "measured", "Orders failing cash-to-order reconciliation / orders"),
        ("KPI 08", "Value-weighted instalment depth",
         metrics["installments"]["value_weighted_average_installments"], "instalments",
         "measured", "SUM(instalments x value) / SUM(value) on card payments"),
        ("KPI 09", "Disputed value at risk", metrics["dispute_total"]["disputed_value"],
         "BRL", "measured (proxy)", "Cash on orders rated 1 or 2 out of 5"),
        ("KPI 10", "Seller HHI", metrics["seller_concentration"]["hhi"], "index", "measured",
         "Sum of squared seller GMV shares"),
        ("KPI 11", "Settlement float", h["settlement_float"], "BRL", "measured",
         "Cash collected on orders not yet delivered"),
        ("KPI 12", "Repeat customer rate",
         metrics["customer_economics"]["repeat_customer_rate_pct"], "% of customers",
         "measured", "Customers with >1 order / unique customers"),
    ]
    extra = [
        ("Memo", "Reconciliation gap (cash above expected charge)", h["reconciliation_gap"],
         "BRL", "measured", "Cash collected - (GMV + freight)"),
        ("Memo", "Modelled total payment cost", c["total_modelled_payment_cost"], "BRL",
         "MODELLED", "Market-rate acquiring + instalment funding model"),
        ("Memo", "Modelled instalment funding cost", c["installment_funding_cost"], "BRL",
         "MODELLED", "Funding rate per instalment x instalment-funded card value"),
        ("Memo", "Cash with no merchandise record",
         metrics["reconciliation"]["cash_without_merchandise"], "BRL", "measured",
         "Cash collected on orders with zero line items"),
    ]

    row = _header(ws, row, ["Ref", "Metric", "Value", "Unit", "Basis", "Definition"])
    for group in (rows, extra):
        for ref, name, value, unit, basis, definition in group:
            ws.cell(row=row, column=1, value=ref).font = BOLD_FONT
            ws.cell(row=row, column=2, value=name).font = BODY_FONT
            cell = ws.cell(row=row, column=3, value=float(value))
            cell.font = Font(name="Calibri", size=10, bold=True, color=NAVY)
            cell.number_format = (MONEY_FMT if unit == "BRL"
                                  else PCT_FMT if "%" in unit
                                  else NUM2_FMT)
            ws.cell(row=row, column=4, value=unit).font = BODY_FONT
            basis_cell = ws.cell(row=row, column=5, value=basis)
            basis_cell.font = Font(name="Calibri", size=10, bold=True,
                                   color=WHITE if basis.startswith("MODELLED") else DARK)
            basis_cell.fill = (BAD_FILL if basis.startswith("MODELLED")
                               else WARN_FILL if "proxy" in basis else GOOD_FILL)
            basis_cell.alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=6, value=definition).font = BODY_FONT
            for col in range(1, 7):
                ws.cell(row=row, column=col).border = BORDER
                if col in (1, 2, 6):
                    ws.cell(row=row, column=col).alignment = Alignment(wrap_text=True, vertical="top")
            row += 1
    _autosize(ws, 10, 52)
    ws.column_dimensions["B"].width = 42
    ws.column_dimensions["F"].width = 54
    row += 1
    _note(ws, row, "Modelled rows are shaded red. They depend on the published market rates "
                   "listed on the Payment Mix sheet and are the only figures in this workbook "
                   "that are not computed directly from the source data.", width=6)
    ws.sheet_view.showGridLines = False


def sheet_monthly(wb: Workbook, monthly: pd.DataFrame) -> None:
    ws = wb.create_sheet("Monthly Financials")
    row = _title(
        ws,
        "Monthly financials",
        "One row per calendar month. The first and last months are partial and are flagged.",
        width=9,
    )
    header_row = row
    row = _header(ws, row, ["Month", "Orders", "Active customers", "GMV", "Freight",
                            "Cash collected", "Refund exposure", "AOV", "Freight ratio %"])
    data_start = row
    row = _write_rows(
        ws, monthly, row,
        formats={
            "GMV": MONEY_FMT, "Freight": MONEY_FMT, "Cash collected": MONEY_FMT,
            "Refund exposure": MONEY_FMT, "AOV": MONEY_FMT,
            "Freight ratio %": PCT_FMT, "Orders": INT_FMT, "Active customers": INT_FMT,
        },
    )
    ws.conditional_formatting.add(
        f"H{data_start}:H{row - 1}",
        ColorScaleRule(start_type="min", start_color="63BE7B",
                       mid_type="percentile", mid_value=50, mid_color="FFEB84",
                       end_type="max", end_color="F8696B"),
    )

    chart = LineChart()
    chart.title = "Cash collected and GMV by month"
    chart.y_axis.title = "BRL"
    chart.x_axis.title = "Month"
    chart.height, chart.width = 9, 30
    data = Reference(ws, min_col=4, max_col=6, min_row=header_row, max_row=row - 1)
    cats = Reference(ws, min_col=1, min_row=data_start, max_row=row - 1)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.style = 2
    ws.add_chart(chart, "K5")

    chart2 = LineChart()
    chart2.title = "Refund exposure by month"
    chart2.y_axis.title = "BRL"
    chart2.height, chart2.width = 8, 30
    data2 = Reference(ws, min_col=7, min_row=header_row, max_row=row - 1)
    chart2.add_data(data2, titles_from_data=True)
    chart2.set_categories(cats)
    chart2.style = 4
    ws.add_chart(chart2, "K25")

    chart3 = LineChart()
    chart3.title = "Average order value by month"
    chart3.y_axis.title = "BRL"
    chart3.height, chart3.width = 8, 30
    data3 = Reference(ws, min_col=8, min_row=header_row, max_row=row - 1)
    chart3.add_data(data3, titles_from_data=True)
    chart3.set_categories(cats)
    chart3.style = 12
    ws.add_chart(chart3, "K43")

    _autosize(ws, 12, 18)
    ws.sheet_view.showGridLines = False


def sheet_growth(wb: Workbook, metrics: dict, monthly: pd.DataFrame) -> None:
    ws = wb.create_sheet("Revenue & Growth")
    y = metrics["yoy"]
    row = _title(
        ws,
        "Revenue growth and cash conversion",
        "Like-for-like comparison: months 1-8 of 2017 against months 1-8 of 2018, so the "
        "partial boundary months cannot distort the answer.",
        width=9,
    )
    row = _header(ws, row, ["Measure", "Jan-Aug 2017", "Jan-Aug 2018", "Change", "Change %"])
    pairs = [
        ("Orders", y["orders_2017"], y["orders_2018"], None, y["orders_growth_pct"], INT_FMT),
        ("Cash collected (BRL)", y["cash_2017"], y["cash_2018"], None, y["cash_growth_pct"], MONEY_FMT),
        ("Active customers", y["customers_2017"], y["customers_2018"], None,
         y["customers_growth_pct"], INT_FMT),
        ("Average order value (BRL)", y["aov_2017"], y["aov_2018"],
         y["aov_2018"] - y["aov_2017"], y["aov_growth_pct"], MONEY_FMT),
        ("Freight ratio (% of GMV)", y["freight_ratio_2017"], y["freight_ratio_2018"],
         y["freight_ratio_change_pts"], None, PCT_FMT),
        ("Refund exposure (BRL)", y["refund_exposure_2017"], y["refund_exposure_2018"],
         y["refund_exposure_2018"] - y["refund_exposure_2017"],
         y["refund_exposure_growth_pct"], MONEY_FMT),
        ("Refund exposure rate (% of cash)", y["refund_rate_2017"], y["refund_rate_2018"],
         round(y["refund_rate_2018"] - y["refund_rate_2017"], 3), None, PCT_FMT),
    ]
    for label, v1, v2, delta, delta_pct, fmt in pairs:
        ws.cell(row=row, column=1, value=label).font = BOLD_FONT
        ws.cell(row=row, column=2, value=float(v1)).number_format = fmt
        ws.cell(row=row, column=3, value=float(v2)).number_format = fmt
        if delta is not None:
            ws.cell(row=row, column=4, value=float(delta)).number_format = fmt
        if delta_pct is not None:
            ws.cell(row=row, column=5, value=float(delta_pct)).number_format = PCT_FMT
        for col in range(1, 6):
            ws.cell(row=row, column=col).font = BODY_FONT if col != 1 else BOLD_FONT
            ws.cell(row=row, column=col).border = BORDER
        row += 1

    row += 1
    row = _note(
        ws, row,
        "Read together: cash grew {:.1f}% like-for-like, orders grew {:.1f}% and average "
        "order value grew {:.2f}%. Growth is volume. The freight ratio moved {:+.2f} points "
        "over the same period, so logistics is not scaling with the business.".format(
            y["cash_growth_pct"], y["orders_growth_pct"], y["aov_growth_pct"],
            y["freight_ratio_change_pts"]),
        width=5,
    )

    # month-on-month table
    mom = monthly[["purchase_month", "orders", "cash_collected", "average_order_value"]].copy()
    mom["mom_cash_growth_pct"] = (mom["cash_collected"].pct_change() * 100).round(2)
    mom["mom_aov_growth_pct"] = (mom["average_order_value"].pct_change() * 100).round(2)
    mom = mom.rename(columns={"purchase_month": "Month", "orders": "Orders",
                               "cash_collected": "Cash collected",
                               "average_order_value": "AOV",
                               "mom_cash_growth_pct": "MoM cash %",
                               "mom_aov_growth_pct": "MoM AOV %"})
    row = _header(ws, row, list(mom.columns))
    row = _write_rows(ws, mom, row, formats={
        "Cash collected": MONEY_FMT, "AOV": MONEY_FMT, "MoM cash %": PCT_FMT,
        "MoM AOV %": PCT_FMT, "Orders": INT_FMT})
    _autosize(ws, 12, 22)
    ws.sheet_view.showGridLines = False


def sheet_payment_mix(wb: Workbook, metrics: dict, method: pd.DataFrame) -> None:
    ws = wb.create_sheet("Payment Mix")
    row = _title(
        ws,
        "Payment mix and modelled cost to serve",
        "The right-hand block is MODELLED from published market rates, not measured from "
        "this marketplace's data.",
        width=8,
    )
    row = _header(ws, row, ["Payment method", "Payment rows", "Orders", "Value (BRL)",
                            "% of value", "Average value", "Avg instalments"])
    display = method.rename(columns={
        "payment_type": "Payment method", "payment_rows": "Payment rows",
        "gross_value": "Value (BRL)", "pct_of_value": "% of value",
        "average_payment_value": "Average value", "average_installments": "Avg instalments",
        "installment_months": "Instalment months",
        "modelled_total_cost": "Modelled cost (BRL)"})
    keep = ["Payment method", "Payment rows", "Value (BRL)", "% of value",
            "Average value", "Avg instalments", "Instalment months",
            "Modelled cost (BRL)"]
    header_row = row - 1
    row = _write_rows(ws, display[keep], row, formats={
        "Value (BRL)": MONEY_FMT, "% of value": PCT_FMT, "Average value": MONEY_FMT,
        "Avg instalments": NUM2_FMT, "Payment rows": INT_FMT,
        "Instalment months": INT_FMT, "Modelled cost (BRL)": MONEY_FMT})

    chart = BarChart()
    chart.type = "col"
    chart.title = "Payment value by method"
    chart.y_axis.title = "BRL"
    chart.height, chart.width = 8, 20
    data = Reference(ws, min_col=4, min_row=header_row, max_row=row - 1)
    cats = Reference(ws, min_col=1, min_row=header_row + 1, max_row=row - 1)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.dLbls = DataLabelList()
    chart.dLbls.showVal = True
    ws.add_chart(chart, "I4")

    row += 2
    row = _note(ws, row, "Cost model assumptions (MODELLED - not facts about this marketplace)",
                width=8)
    row = _header(ws, row, ["Payment method", "Rate % of value", "Fixed fee (BRL)",
                            "Funding rate per instalment", "Assumption note"])
    for method_name, (pct_rate, fixed_fee, note) in config.PAYMENT_COST_MODEL.items():
        ws.cell(row=row, column=1, value=method_name).font = BODY_FONT
        ws.cell(row=row, column=2, value=pct_rate * 100).number_format = PCT_FMT
        ws.cell(row=row, column=3, value=fixed_fee).number_format = MONEY_FMT
        ws.cell(row=row, column=4, value=(
            config.INSTALLMENT_FUNDING_RATE if method_name == "credit_card" else 0.0)
        ).number_format = PCT_FMT
        ws.cell(row=row, column=5, value=note).font = BODY_FONT
        for col in range(1, 6):
            ws.cell(row=row, column=col).border = BORDER
        row += 1

    row += 1
    row = _header(ws, row, ["Modelled cost by method", "Acquiring cost", "Instalment funding",
                            "Total modelled cost", "% of that method's value"])
    for record in metrics["cost_model"]["by_method"]:
        ws.cell(row=row, column=1, value=record["payment_type"]).font = BODY_FONT
        ws.cell(row=row, column=2, value=record["acquiring_cost"]).number_format = MONEY_FMT
        ws.cell(row=row, column=3, value=record["installment_funding_cost"]).number_format = MONEY_FMT
        ws.cell(row=row, column=4, value=record["total_modelled_cost"]).number_format = MONEY_FMT
        share = 100 * record["total_modelled_cost"] / record["gross_value"] if record["gross_value"] else 0
        ws.cell(row=row, column=5, value=round(share, 3)).number_format = PCT_FMT
        for col in range(1, 6):
            ws.cell(row=row, column=col).border = BORDER
        row += 1

    row += 1
    row = _header(ws, row, ["Sensitivity: funding rate per instalment",
                            "Modelled instalment funding", "% of card value"])
    for record in metrics["cost_model"]["sensitivity"]:
        ws.cell(row=row, column=1, value=record["rate"] * 100).number_format = PCT_FMT
        ws.cell(row=row, column=2, value=record["installment_funding_cost"]).number_format = MONEY_FMT
        ws.cell(row=row, column=3, value=record["pct_of_card_value"]).number_format = PCT_FMT
        for col in range(1, 4):
            ws.cell(row=row, column=col).border = BORDER
        row += 1

    row += 1
    _note(ws, row,
          "Reading this sheet: the instalment-funding component is the single largest item "
          "in the modelled cost base. It survives the low end of the published rate band, "
          "so its DIRECTION is robust; its SIZE is assumption-dependent. No saving is "
          "claimed here because no contract and no experiment exists in the data.",
          width=8)
    _autosize(ws, 12, 56)
    ws.sheet_view.showGridLines = False


def sheet_refund_exposure(wb: Workbook, metrics: dict, monthly: pd.DataFrame) -> None:
    ws = wb.create_sheet("Refund Exposure")
    row = _title(
        ws,
        "Refund exposure",
        "Cash collected on orders that will never be fulfilled. The source data has no "
        "refund table: this is an exposure proxy, not a refunds ledger.",
        width=6,
    )
    row = _header(ws, row, ["Order status", "Orders", "Cash collected", "Refund exposure",
                            "Orders with no line items", "% without line items"])
    for record in metrics["refund_exposure"]:
        ws.cell(row=row, column=1, value=record["order_status"]).font = BODY_FONT
        ws.cell(row=row, column=2, value=record["orders"]).number_format = INT_FMT
        ws.cell(row=row, column=3, value=record["cash_collected"]).number_format = MONEY_FMT
        ws.cell(row=row, column=4, value=record["refund_exposure"]).number_format = MONEY_FMT
        ws.cell(row=row, column=5, value=record["orders_without_line_items"]).number_format = INT_FMT
        ws.cell(row=row, column=6, value=record["pct_without_line_items"]).number_format = PCT_FMT
        for col in range(1, 7):
            ws.cell(row=row, column=col).border = BORDER
        row += 1
    total = metrics["refund_exposure_total"]
    ws.cell(row=row, column=1, value="TOTAL").font = BOLD_FONT
    ws.cell(row=row, column=2, value=total["orders"]).number_format = INT_FMT
    ws.cell(row=row, column=3, value=total["cash_collected"]).number_format = MONEY_FMT
    ws.cell(row=row, column=4, value=total["refund_exposure"]).number_format = MONEY_FMT
    ws.cell(row=row, column=5, value=total["orders_without_line_items"]).number_format = INT_FMT
    for col in range(1, 7):
        ws.cell(row=row, column=col).border = BORDER
        ws.cell(row=row, column=col).fill = PatternFill("solid", fgColor=SAND)
    row += 2

    series = monthly[["purchase_month", "refund_exposure", "cash_collected",
                      "refund_exposure_pct"]].rename(columns={
        "purchase_month": "Month", "refund_exposure": "Refund exposure",
        "cash_collected": "Cash collected", "refund_exposure_pct": "Refund exposure %"})
    header_row = row
    row = _header(ws, row, list(series.columns))
    data_start = row
    row = _write_rows(ws, series, row, formats={
        "Refund exposure": MONEY_FMT, "Cash collected": MONEY_FMT,
        "Refund exposure %": PCT_FMT})

    chart = LineChart()
    chart.title = "Refund exposure by month"
    chart.y_axis.title = "BRL"
    chart.height, chart.width = 9, 26
    data = Reference(ws, min_col=2, min_row=header_row, max_row=row - 1)
    cats = Reference(ws, min_col=1, min_row=data_start, max_row=row - 1)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    ws.add_chart(chart, "H5")

    chart2 = LineChart()
    chart2.title = "Refund exposure rate, % of cash collected"
    chart2.y_axis.title = "% of cash collected"
    chart2.height, chart2.width = 8, 26
    data2 = Reference(ws, min_col=4, min_row=header_row, max_row=row - 1)
    chart2.add_data(data2, titles_from_data=True)
    chart2.set_categories(cats)
    ws.add_chart(chart2, "H25")
    _autosize(ws, 12, 22)
    ws.sheet_view.showGridLines = False


def sheet_reconciliation(wb: Workbook, metrics: dict, breaks: pd.DataFrame) -> None:
    ws = wb.create_sheet("Reconciliation")
    r = metrics["reconciliation"]
    row = _title(
        ws,
        "Cash-to-revenue reconciliation",
        "Expected charge = merchandise value + freight. A break is any order where the "
        "amount collected differs by R$ 0.01 or more.",
        width=6,
    )
    summary = [
        ("Expected charge (GMV + freight)", r["expected_charge"]),
        ("Cash collected", r["cash_collected"]),
        ("Net break", r["net_break"]),
        ("Gross break value", r["gross_break_value"]),
        ("Orders in break", r["orders_in_break"]),
        ("Break rate (% of orders)", r["break_rate_pct"]),
        ("Orders with cash but no line items", r["paid_orders_without_line_items"]),
        ("Cash on orders with no line items", r["cash_without_merchandise"]),
    ]
    row = _header(ws, row, ["Reconciliation summary", "Value"])
    for label, value in summary:
        ws.cell(row=row, column=1, value=label).font = BODY_FONT
        cell = ws.cell(row=row, column=2, value=float(value))
        cell.number_format = (PCT_FMT if "%" in label else
                               INT_FMT if "Orders" in label else MONEY_FMT)
        cell.font = Font(name="Calibri", size=10, bold=True, color=NAVY)
        ws.cell(row=row, column=1).border = BORDER
        ws.cell(row=row, column=2).border = BORDER
        row += 1

    row += 1
    row = _header(ws, row, ["Break reason", "Size band", "Orders", "Absolute break",
                            "Net break"])
    for record in metrics["break_structure"]:
        ws.cell(row=row, column=1, value=record["break_reason"]).font = BODY_FONT
        ws.cell(row=row, column=2, value=record["size_band"]).font = BODY_FONT
        ws.cell(row=row, column=3, value=record["orders"]).number_format = INT_FMT
        ws.cell(row=row, column=4, value=record["absolute_break"]).number_format = MONEY_FMT
        ws.cell(row=row, column=5, value=record["net_break"]).number_format = MONEY_FMT
        for col in range(1, 6):
            ws.cell(row=row, column=col).border = BORDER
        row += 1

    row += 2
    row = _note(ws, row,
                "Exception list below: every order that fails the reconciliation, largest "
                "first. This is the working list for a finance team. The break is REPORTED, "
                "never corrected - no amount in this workbook has been adjusted to make the "
                "books close.", width=6)
    row = _header(ws, row, ["Order ID", "Status", "Reason", "Size band", "GMV", "Freight",
                            "Expected charge", "Cash collected", "Break amount",
                            "Line items", "Purchase date"])
    display = breaks[["order_id", "order_status", "break_reason", "size_band", "gmv",
                      "freight", "expected_charge", "cash_collected", "break_amount",
                      "line_item_count", "purchase_date"]]
    row = _write_rows(ws, display, row, formats={
        "GMV": MONEY_FMT, "Freight": MONEY_FMT, "Expected charge": MONEY_FMT,
        "Cash collected": MONEY_FMT, "Break amount": MONEY_FMT,
        "Line items": INT_FMT}, band=False, minimal=True)
    ws.freeze_panes = f"A{row - len(display)}"
    ws.auto_filter.ref = f"A{row - len(display) - 1}:K{row - 1}"
    _autosize(ws, 12, 38)
    ws.sheet_view.showGridLines = False


def sheet_seller_concentration(wb: Workbook, metrics: dict, sellers: pd.DataFrame) -> None:
    ws = wb.create_sheet("Seller Concentration")
    s = metrics["seller_concentration"]
    row = _title(
        ws,
        "Seller concentration",
        "Counterparty dependency: how much of GMV sits with the largest sellers.",
        width=6,
    )
    summary = [
        ("Active sellers", s["sellers"], INT_FMT),
        ("Largest seller (% of GMV)", s["top1_pct"], PCT_FMT),
        ("Top 10 sellers (% of GMV)", s["top10_pct"], PCT_FMT),
        ("Top 100 sellers (% of GMV)", s["top100_pct"], PCT_FMT),
        ("Top 1,000 sellers (% of GMV)", s["top1000_pct"], PCT_FMT),
        ("Herfindahl-Hirschman index", s["hhi"], "0.00000"),
        ("Sellers above 1% of GMV", s["sellers_above_1pct"], INT_FMT),
    ]
    row = _header(ws, row, ["Concentration measure", "Value"])
    for label, value, fmt in summary:
        ws.cell(row=row, column=1, value=label).font = BODY_FONT
        ws.cell(row=row, column=2, value=float(value)).number_format = fmt
        ws.cell(row=row, column=1).border = BORDER
        ws.cell(row=row, column=2).border = BORDER
        row += 1
    row += 1
    _note(ws, row,
          "An HHI below 0.15 indicates an unconcentrated market. Counterparty dependency "
          "is not a material risk here; the concentration that matters is regional - Sao "
          "Paulo hosts 1,849 of the 3,095 sellers and 64.4% of GMV.", width=6)
    row += 4

    pareto = sellers.head(300).rename(columns={
        "seller_id": "Seller", "seller_state": "State", "gmv_rank": "Rank",
        "seller_gmv": "GMV", "pct_of_total_gmv": "% of GMV",
        "cumulative_pct_of_gmv": "Cumulative % of GMV"})
    header_row = row
    row = _header(ws, row, list(pareto.columns))
    row = _write_rows(ws, pareto, row, formats={
        "GMV": MONEY_FMT, "% of GMV": PCT_FMT, "Cumulative % of GMV": PCT_FMT,
        "Rank": INT_FMT})

    chart = LineChart()
    chart.title = "Concentration curve (top 300 sellers)"
    chart.y_axis.title = "Cumulative % of GMV"
    chart.height, chart.width = 9, 30
    data = Reference(ws, min_col=6, min_row=header_row, max_row=row - 1)
    cats = Reference(ws, min_col=3, min_row=header_row + 1, max_row=row - 1)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    ws.add_chart(chart, "H5")
    _autosize(ws, 12, 30)
    ws.sheet_view.showGridLines = False


def sheet_category_logistics(wb: Workbook, metrics: dict, categories: pd.DataFrame) -> None:
    ws = wb.create_sheet("Category Logistics")
    row = _title(
        ws,
        "Logistics cost-to-serve by product category",
        "Freight collected as a share of merchandise value. A burden on the order, not a "
        "logistics margin - the dataset holds no carrier cost.",
        width=6,
    )
    display = categories.rename(columns={
        "category_english": "Category", "gmv": "GMV", "freight": "Freight",
        "freight_ratio_pct": "Freight ratio %", "line_item_count": "Line items"})
    keep = ["Category", "GMV", "Freight", "Freight ratio %", "Line items"]
    header_row = row
    row = _header(ws, row, keep)
    row = _write_rows(ws, display[keep], row, formats={
        "GMV": MONEY_FMT, "Freight": MONEY_FMT, "Freight ratio %": PCT_FMT,
        "Line items": INT_FMT})
    ws.conditional_formatting.add(
        f"D{header_row + 1}:D{row - 1}",
        ColorScaleRule(start_type="min", start_color="63BE7B",
                       mid_type="percentile", mid_value=50, mid_color="FFEB84",
                       end_type="max", end_color="F8696B"),
    )

    chart = BarChart()
    chart.type = "bar"
    chart.title = "Freight burden by category"
    chart.x_axis.title = "% of merchandise value"
    chart.height, chart.width = 16, 22
    data = Reference(ws, min_col=4, min_row=header_row, max_row=row - 1)
    cats = Reference(ws, min_col=1, min_row=header_row + 1, max_row=row - 1)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    ws.add_chart(chart, "H4")
    _autosize(ws, 12, 30)
    ws.sheet_view.showGridLines = False


def sheet_dispute_risk(wb: Workbook, metrics: dict) -> None:
    ws = wb.create_sheet("Dispute Risk")
    row = _title(
        ws,
        "Dispute risk and consumer credit",
        "Disputed = an order whose worst review score is 1 or 2 out of 5. A proxy for a "
        "chargeback or complaint; the source data records no disputes.",
        width=6,
    )
    header_row = row
    row = _header(ws, row, ["Instalment bucket", "Orders", "Cash collected", "Average order value",
                            "Disputed orders", "Dispute rate %", "Disputed value"])
    for record in metrics["dispute_by_installments"]:
        ws.cell(row=row, column=1, value=record["instalment_bucket"]).font = BODY_FONT
        ws.cell(row=row, column=2, value=record["orders"]).number_format = INT_FMT
        ws.cell(row=row, column=3, value=record["cash"]).number_format = MONEY_FMT
        ws.cell(row=row, column=4, value=record["average_order_value"]).number_format = MONEY_FMT
        ws.cell(row=row, column=5, value=record["disputed_orders"]).number_format = INT_FMT
        ws.cell(row=row, column=6, value=record["dispute_rate_pct"]).number_format = PCT_FMT
        ws.cell(row=row, column=7, value=record["disputed_value"]).number_format = MONEY_FMT
        for col in range(1, 8):
            ws.cell(row=row, column=col).border = BORDER
        row += 1

    chart = BarChart()
    chart.type = "col"
    chart.title = "Dispute rate by instalment depth"
    chart.y_axis.title = "% of orders disputed"
    chart.height, chart.width = 9, 24
    data = Reference(ws, min_col=6, min_row=header_row, max_row=row - 1)
    cats = Reference(ws, min_col=1, min_row=header_row + 1, max_row=row - 1)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.dLbls = DataLabelList()
    chart.dLbls.showVal = True
    ws.add_chart(chart, "I4")

    row += 2
    _note(ws, row,
          "This is an ASSOCIATION in the data, not a demonstrated cause. Longer instalment "
          "plans may select for riskier baskets, or may simply correlate with higher-value "
          "and more complex orders. No causal claim is made and no intervention has been "
          "measured.", width=7)
    _autosize(ws, 12, 24)
    ws.sheet_view.showGridLines = False


def sheet_data_quality(wb: Workbook, metrics: dict) -> None:
    ws = wb.create_sheet("Data Quality")
    row = _title(
        ws,
        "Data-quality audit",
        "Every check run against the loaded warehouse, with the number of records it "
        "touched. Zero is the expected result for integrity checks.",
        width=5,
    )
    row = _header(ws, row, ["Rule", "Table", "Type", "Records affected", "Description"])
    for record in metrics["data_quality"]:
        ws.cell(row=row, column=1, value=record["rule_code"]).font = BOLD_FONT
        ws.cell(row=row, column=2, value=record["table_name"]).font = BODY_FONT
        ws.cell(row=row, column=3, value=record["rule_type"]).font = BODY_FONT
        ws.cell(row=row, column=4, value=record["records_affected"]).number_format = INT_FMT
        ws.cell(row=row, column=5, value=record["rule_description"]).font = BODY_FONT
        for col in range(1, 6):
            ws.cell(row=row, column=col).border = BORDER
            ws.cell(row=row, column=col).alignment = Alignment(wrap_text=True, vertical="top")
        if record["rule_code"].startswith("V-"):
            ws.cell(row=row, column=4).fill = (
                BAD_FILL if record["records_affected"] else GOOD_FILL)
        row += 1
    row += 2
    _note(ws, row,
          "The full check output, including the row-level detail behind each finding, is in "
          "reports/data_quality.md and reports/data_quality.json.", width=5)
    _autosize(ws, 12, 60)
    ws.sheet_view.showGridLines = False


def sheet_order_records(wb: Workbook, orders: pd.DataFrame) -> None:
    ws = wb.create_sheet("Order Records")
    row = _title(
        ws,
        "Cleaned order-level fact - ready to pivot",
        "One row per order with every financial measure as a column. Select any cell and "
        "use Insert > PivotTable to re-cut the analysis without touching Python.",
        width=8,
    )
    display = orders[[
        "order_id", "purchase_date", "purchase_month", "purchase_quarter",
        "customer_unique_id", "customer_state", "order_status", "status_class",
        "primary_payment_type", "line_item_count", "seller_count", "gmv",
        "freight_total", "expected_charge", "cash_collected", "recon_delta",
        "recon_break_flag", "refund_exposure_value", "net_revenue",
        "settlement_float_value", "payment_count", "max_installments",
        "review_count", "worst_review_score", "disputed_flag", "delivery_days",
        "days_late_vs_promise"]]
    display = display.rename(columns={
        "order_id": "Order ID", "purchase_date": "Purchase date",
        "purchase_month": "Month", "purchase_quarter": "Quarter",
        "customer_unique_id": "Customer", "customer_state": "Customer state",
        "order_status": "Order status", "status_class": "Status class",
        "primary_payment_type": "Payment method", "line_item_count": "Line items",
        "seller_count": "Sellers", "gmv": "GMV", "freight_total": "Freight",
        "expected_charge": "Expected charge", "cash_collected": "Cash collected",
        "recon_delta": "Reconciliation break", "recon_break_flag": "In break",
        "refund_exposure_value": "Refund exposure", "net_revenue": "Net revenue",
        "settlement_float_value": "Settlement float", "payment_count": "Payments",
        "max_installments": "Instalments", "review_count": "Reviews",
        "worst_review_score": "Worst score", "disputed_flag": "Disputed",
        "delivery_days": "Delivery days", "days_late_vs_promise": "Days late"})
    header_row = row
    row = _header(ws, row, list(display.columns))
    row = _write_rows(ws, display, row, formats={
        "GMV": MONEY_FMT, "Freight": MONEY_FMT, "Expected charge": MONEY_FMT,
        "Cash collected": MONEY_FMT, "Reconciliation break": MONEY_FMT,
        "Refund exposure": MONEY_FMT, "Net revenue": MONEY_FMT,
        "Settlement float": MONEY_FMT}, band=False, minimal=True)
    ws.freeze_panes = f"A{header_row + 1}"
    ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(display.columns))}{row - 1}"
    _autosize(ws, 11, 24)
    ws.sheet_view.showGridLines = False


# ---------------------------------------------------------------------------
def main() -> None:
    metrics = json.loads(
        (config.REPORTS_DIR / "key_metrics.json").read_text(encoding="utf-8")
    )
    conn = sqlite3.connect(config.DB_PATH)

    monthly = pd.read_sql_query(
        """
        SELECT purchase_month, COUNT(*) AS orders,
               COUNT(DISTINCT customer_unique_id) AS active_customers,
               ROUND(SUM(gmv),2) AS gmv, ROUND(SUM(freight_total),2) AS freight,
               ROUND(SUM(cash_collected),2) AS cash_collected,
               ROUND(SUM(refund_exposure_value),2) AS refund_exposure,
               ROUND(SUM(cash_collected)/COUNT(*),2) AS average_order_value,
               ROUND(100.0*SUM(freight_total)/SUM(gmv),2) AS freight_ratio_pct,
               ROUND(100.0*SUM(refund_exposure_value)/SUM(cash_collected),3) AS refund_exposure_pct
        FROM fact_order_financials GROUP BY purchase_month ORDER BY purchase_month
        """, conn)
    method = pd.read_csv(config.PROCESSED_FILES["payment_method_financials"])
    sellers = pd.read_csv(config.PROCESSED_FILES["seller_concentration"])
    breaks = pd.read_csv(config.PROCESSED_FILES["reconciliation_breaks"])
    categories = pd.read_sql_query(
        "SELECT category_english, ROUND(category_gmv,2) AS gmv, ROUND(category_freight,2) AS freight, "
        "freight_ratio_pct, line_item_count FROM v_category_financials "
        "WHERE category_gmv > 0 ORDER BY gmv DESC", conn)
    orders = pd.read_csv(config.PROCESSED_FILES["clean_orders"])
    conn.close()

    wb = Workbook()
    wb.remove(wb.active)

    sheet_readme(wb, metrics)
    sheet_kpi_scorecard(wb, metrics)
    sheet_monthly(wb, monthly)
    sheet_growth(wb, metrics, monthly)
    sheet_payment_mix(wb, metrics, method)
    sheet_refund_exposure(wb, metrics, monthly)
    sheet_reconciliation(wb, metrics, breaks)
    sheet_seller_concentration(wb, metrics, sellers)
    sheet_category_logistics(wb, metrics, categories)
    sheet_dispute_risk(wb, metrics)
    sheet_data_quality(wb, metrics)
    sheet_order_records(wb, orders)

    config.EXCEL_DIR.mkdir(parents=True, exist_ok=True)
    wb.save(config.EXCEL_PATH)
    print(f"[build_excel] wrote {config.EXCEL_PATH} ({len(wb.sheetnames)} sheets: "
          f"{', '.join(wb.sheetnames)})")


if __name__ == "__main__":
    main()
