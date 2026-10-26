"""Generate the Power BI project (PBIP): semantic model + report pages.

Pipeline step 3b:  load -> clean -> query -> report.

The PBIP project under `powerbi/MarketplaceFinance/` is the *editable source*
of the dashboard. `powerbi/build_pbit.py` compiles it into
`powerbi/MarketplaceFinance.pbit`, the template that Power BI Desktop opens.

Generating the model from code (rather than hand-editing JSON) means the
DAX measures, the column list and the Power Query expressions cannot drift
apart: one schema definition drives all three.

Design notes
------------
* Every visual carries ONE measure plus an optional category and series.
  That is the form Power BI Desktop resolves most reliably from a
  template that has never been opened interactively.
* Date filtering reaches FactPayment and FactOrderItem through the order
  table rather than through a second relationship to DimDate, which avoids
  the ambiguous-path error Power BI raises when a fact has two active
  paths to the same dimension.
* The modelled cost rates live in DimPaymentMethod, so the cost-to-serve
  numbers can be re-run against different assumptions without editing any
  measure.

Usage:
    python src/build_powerbi_model.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

PROJECT_NAME = "MarketplaceFinance"
PROJECT_ID = "3fe2c584-3ed4-4f61-980b-22434e378dd1"
PBIP_DIR = config.POWERBI_DIR / PROJECT_NAME
MODEL_DIR = PBIP_DIR / f"{PROJECT_NAME}.SemanticModel"
REPORT_DIR = PBIP_DIR / f"{PROJECT_NAME}.Report"
PBIR_DIR = REPORT_DIR / "definition"

MONEY = 'R$#,##0'
MONEY2 = 'R$#,##0.00'
PCT = '0.0"%"'
PCT2 = '0.00"%"'
NUM = '#,##0'
NUM2 = '#,##0.00'

# ---------------------------------------------------------------------------
# Schema: table -> list of (column name, data type, is_key)
# ---------------------------------------------------------------------------
SCHEMA: dict[str, list[tuple[str, str, bool]]] = {
    "FactOrder": [
        ("OrderKey", "string", True),
        ("DateKey", "int64", False),
        ("CustomerKey", "string", False),
        ("PaymentMethodKey", "string", False),
        ("OrderStatus", "string", False),
        ("StatusClass", "string", False),
        ("PurchaseMonth", "string", False),
        ("PurchaseYear", "int64", False),
        ("PurchaseQuarter", "string", False),
        ("CustomerState", "string", False),
        ("LineItemCount", "int64", False),
        ("SellerCount", "int64", False),
        ("ProductCount", "int64", False),
        ("MerchandiseValue", "double", False),
        ("FreightCollected", "double", False),
        ("ExpectedCharge", "double", False),
        ("CashCollected", "double", False),
        ("ReconDelta", "double", False),
        ("ReconBreak", "int64", False),
        ("PaymentCount", "int64", False),
        ("MaxInstallments", "int64", False),
        ("InstallmentMonths", "int64", False),
        ("RefundExposure", "double", False),
        ("NetRevenue", "double", False),
        ("SettlementFloat", "double", False),
        ("VoucherValue", "double", False),
        ("CardValue", "double", False),
        ("BoletoValue", "double", False),
        ("DebitCardValue", "double", False),
        ("ReviewCount", "int64", False),
        ("WorstReviewScore", "int64", False),
        ("DisputedFlag", "int64", False),
        ("DeliveryDays", "double", False),
        ("DaysLateVsPromise", "double", False),
    ],
    "FactPayment": [
        ("OrderKey", "string", False),
        ("PaymentSequence", "int64", False),
        ("PaymentMethodKey", "string", False),
        ("Installments", "int64", False),
        ("PaymentValue", "double", False),
        ("RefundExposure", "double", False),
        ("VoucherValue", "double", False),
        ("InstallmentCreditValue", "double", False),
        ("StatusClass", "string", False),
        ("CustomerState", "string", False),
    ],
    "FactOrderItem": [
        ("OrderKey", "string", False),
        ("OrderItemKey", "int64", True),
        ("ProductKey", "string", False),
        ("SellerKey", "string", False),
        ("Price", "double", False),
        ("FreightValue", "double", False),
        ("LineCharge", "double", False),
        ("FreightOverPrice", "int64", False),
        ("LargeLine", "int64", False),
        ("ProductWeightG", "double", False),
        ("SellerState", "string", False),
    ],
    "DimDate": [
        ("DateKey", "int64", True),
        ("full_date", "dateTime", False),
        ("year", "int64", False),
        ("MonthNumber", "int64", False),
        ("quarter_key", "string", False),
        ("month_start", "dateTime", False),
        ("day_of_week", "int64", False),
        ("is_weekend", "int64", False),
    ],
    "DimCustomer": [
        ("CustomerKey", "string", True),
        ("CustomerState", "string", False),
        ("ZipCodePrefix", "int64", False),
        ("OrderCount", "int64", False),
        ("CashCollected", "double", False),
        ("CustomerGMV", "double", False),
        ("RefundExposure", "double", False),
        ("DisputedOrders", "int64", False),
        ("FirstPurchaseDate", "dateTime", False),
        ("LastPurchaseDate", "dateTime", False),
        ("AverageOrderValue", "double", False),
        ("IsRepeat", "int64", False),
        ("SettlementFloat", "double", False),
        ("InstallmentMonths", "int64", False),
    ],
    "DimSeller": [
        ("SellerKey", "string", True),
        ("SellerState", "string", False),
        ("SellerCity", "string", False),
        ("GMVRank", "int64", False),
        ("SellerGMV", "double", False),
        ("OrderCount", "int64", False),
        ("ProductCount", "int64", False),
        ("SellerFreight", "double", False),
        ("FreightRatioPct", "double", False),
        ("AverageOrderValue", "double", False),
    ],
    "DimProduct": [
        ("ProductKey", "string", True),
        ("ProductCategory", "string", False),
        ("CategoryEnglish", "string", False),
        ("ProductWeightG", "double", False),
        ("ProductLengthCm", "double", False),
        ("ProductHeightCm", "double", False),
        ("ProductWidthCm", "double", False),
        ("ProductPhotosQty", "double", False),
        ("LineItemCount", "int64", False),
        ("ProductGMV", "double", False),
    ],
    "DimPaymentMethod": [
        ("PaymentMethodKey", "string", True),
        ("PaymentType", "string", False),
        ("Description", "string", False),
        ("RatePct", "double", False),
        ("FixedFee", "double", False),
        ("FundingRatePerInstallment", "double", False),
        ("IsPromotional", "int64", False),
        ("AssumptionNote", "string", False),
    ],
}

DATA_CATEGORY = {
    "FactOrder": "Fact",
    "FactPayment": "Fact",
    "FactOrderItem": "Fact",
    "DimDate": "Time",
    "DimCustomer": "Dimension",
    "DimSeller": "Dimension",
    "DimProduct": "Dimension",
    "DimPaymentMethod": "Dimension",
}

HIDE_IN_REPORT = {
    "FactOrder": ["OrderKey", "DateKey", "CustomerKey", "PaymentMethodKey"],
    "FactPayment": ["OrderKey", "PaymentMethodKey"],
    "FactOrderItem": ["OrderKey", "OrderItemKey", "ProductKey", "SellerKey"],
}

# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------
RELATIONSHIPS = [
    ("FactOrder_DimDate", "FactOrder", "DateKey", "DimDate", "DateKey"),
    ("FactOrder_DimCustomer", "FactOrder", "CustomerKey", "DimCustomer", "CustomerKey"),
    # NOTE: DimPaymentMethod is related to FactPayment ONLY. Relating it to
    # FactOrder as well creates two paths from FactPayment to the dimension
    # (FactPayment -> FactOrder -> DimPaymentMethod and
    # FactPayment -> DimPaymentMethod) and Power BI refuses to load a model
    # with an ambiguous path (PFE_XL_USERELATIONSHIP_AMBIGUOUS_PATH).
    # Order-level payment-method breakdowns use the plain text column
    # FactOrder[PaymentMethodKey], which needs no relationship.
    ("FactPayment_FactOrder", "FactPayment", "OrderKey", "FactOrder", "OrderKey"),
    ("FactPayment_DimPaymentMethod", "FactPayment", "PaymentMethodKey", "DimPaymentMethod", "PaymentMethodKey"),
    ("FactOrderItem_FactOrder", "FactOrderItem", "OrderKey", "FactOrder", "OrderKey"),
    ("FactOrderItem_DimProduct", "FactOrderItem", "ProductKey", "DimProduct", "ProductKey"),
    ("FactOrderItem_DimSeller", "FactOrderItem", "SellerKey", "DimSeller", "SellerKey"),
]

# ---------------------------------------------------------------------------
# Measures
# ---------------------------------------------------------------------------
MEASURES: dict[str, list[tuple[str, str, str]]] = {
    "FactOrder": [
        ("GMV", "SUM ( FactOrder[MerchandiseValue] )", MONEY),
        ("Cash Collected", "SUM ( FactOrder[CashCollected] )", MONEY),
        ("Freight Collected", "SUM ( FactOrder[FreightCollected] )", MONEY),
        ("Expected Charge", "SUM ( FactOrder[ExpectedCharge] )", MONEY),
        ("Refund Exposure", "SUM ( FactOrder[RefundExposure] )", MONEY),
        ("Net Revenue", "SUM ( FactOrder[NetRevenue] )", MONEY),
        ("Settlement Float", "SUM ( FactOrder[SettlementFloat] )", MONEY),
        ("Voucher Credit", "SUM ( FactOrder[VoucherValue] )", MONEY),
        ("Orders", "COUNTROWS ( FactOrder[OrderKey] )", NUM),
        ("Customers", "DISTINCTCOUNT ( FactOrder[CustomerKey] )", NUM),
        ("Average Order Value", "DIVIDE ( [Cash Collected], [Orders] )", MONEY2),
        ("Cash per Customer", "DIVIDE ( [Cash Collected], [Customers] )", MONEY2),
        ("Revenue vs Expected", "[Cash Collected] - [Expected Charge]", MONEY),
        ("Net Revenue % of Cash", "DIVIDE ( [Net Revenue], [Cash Collected] )", PCT2),
        ("Refund Exposure Rate", "DIVIDE ( [Refund Exposure], [Cash Collected] )", PCT2),
        ("Freight Ratio", "DIVIDE ( [Freight Collected], [GMV] )", PCT),
        (
            "Reconciliation Break Orders",
            "CALCULATE ( COUNTROWS ( FactOrder[OrderKey] ), FactOrder[ReconBreak] = 1 )",
            NUM,
        ),
        (
            "Reconciliation Break Rate",
            "DIVIDE ( [Reconciliation Break Orders], [Orders] )",
            PCT2,
        ),
        (
            "Gross Break Value",
            "SUMX ( FILTER ( FactOrder, FactOrder[ReconBreak] = 1 ), ABS ( FactOrder[ReconDelta] ) )",
            MONEY,
        ),
        (
            "Net Break Amount",
            "SUMX ( FILTER ( FactOrder, FactOrder[ReconBreak] = 1 ), FactOrder[ReconDelta] )",
            MONEY,
        ),
        (
            "Cash Without Merchandise",
            "SUMX ( FILTER ( FactOrder, FactOrder[LineItemCount] = 0 ), FactOrder[CashCollected] )",
            MONEY,
        ),
        (
            "Orders With Reviews",
            "CALCULATE ( COUNTROWS ( FactOrder[OrderKey] ), NOT ISBLANK ( FactOrder[WorstReviewScore] ) )",
            NUM,
        ),
        (
            "Disputed Orders",
            "CALCULATE ( COUNTROWS ( FactOrder[OrderKey] ), FactOrder[DisputedFlag] = 1 )",
            NUM,
        ),
        ("Dispute Rate", "DIVIDE ( [Disputed Orders], [Orders With Reviews] )", PCT),
        (
            "Disputed Value",
            "CALCULATE ( SUM ( FactOrder[CashCollected] ), FactOrder[DisputedFlag] = 1 )",
            MONEY,
        ),
        ("Cash at Risk %", "DIVIDE ( [Disputed Value], [Cash Collected] )", PCT),
        (
            "Repeat Customers",
            "CALCULATE ( COUNTROWS ( DimCustomer[CustomerKey] ), DimCustomer[IsRepeat] = 1 )",
            NUM,
        ),
        ("Repeat Customer Rate", "DIVIDE ( [Repeat Customers], [Customers] )", PCT2),
        ("Orders per Customer", "DIVIDE ( [Orders], [Customers] )", NUM2),
        (
            "Cash MoM %",
            "VAR Prev = CALCULATE ( [Cash Collected], DATEADD ( DimDate[full_date], -1, MONTH ) ) "
            "RETURN DIVIDE ( [Cash Collected] - Prev, Prev )",
            PCT,
        ),
        (
            "Cash YoY %",
            "VAR Prev = CALCULATE ( [Cash Collected], SAMEPERIODLASTYEAR ( DimDate[full_date] ) ) "
            "RETURN DIVIDE ( [Cash Collected] - Prev, Prev )",
            PCT,
        ),
        (
            "Orders YoY %",
            "VAR Prev = CALCULATE ( [Orders], SAMEPERIODLASTYEAR ( DimDate[full_date] ) ) "
            "RETURN DIVIDE ( [Orders] - Prev, Prev )",
            PCT,
        ),
        (
            "AOV YoY %",
            "VAR Prev = CALCULATE ( [Average Order Value], SAMEPERIODLASTYEAR ( DimDate[full_date] ) ) "
            "RETURN DIVIDE ( [Average Order Value] - Prev, Prev )",
            PCT,
        ),
        (
            "Contribution After Payment Cost",
            "[Net Revenue] - [Modelled Total Payment Cost]",
            MONEY,
        ),
        (
            "Contribution Margin %",
            "DIVIDE ( [Contribution After Payment Cost], [Net Revenue] )",
            PCT,
        ),
    ],
    "FactPayment": [
        ("Payment Value", "SUM ( FactPayment[PaymentValue] )", MONEY),
        ("Payment Rows", "COUNTROWS ( FactPayment[OrderKey] )", NUM),
        (
            "Modelled Acquiring Cost",
            "SUMX ( FactPayment, FactPayment[PaymentValue] * RELATED ( DimPaymentMethod[RatePct] ) "
            "+ RELATED ( DimPaymentMethod[FixedFee] ) )",
            MONEY,
        ),
        (
            "Modelled Installment Funding",
            "SUMX ( FactPayment, IF ( FactPayment[PaymentMethodKey] = \"credit_card\", "
            "FactPayment[PaymentValue] * RELATED ( DimPaymentMethod[FundingRatePerInstallment] ) "
            "* ( FactPayment[Installments] - 1 ), 0 ) )",
            MONEY,
        ),
        (
            "Modelled Total Payment Cost",
            "[Modelled Acquiring Cost] + [Modelled Installment Funding]",
            MONEY,
        ),
        (
            "Value Weighted Average Installments",
            "DIVIDE ( SUMX ( FactPayment, FactPayment[Installments] * FactPayment[PaymentValue] ), [Payment Value] )",
            NUM2,
        ),
        ("Installment Funded Value", "SUM ( FactPayment[InstallmentCreditValue] )", MONEY),
        ("Voucher Credit (payments)", "SUM ( FactPayment[VoucherValue] )", MONEY),
    ],
    "FactOrderItem": [
        ("Line Items", "COUNTROWS ( FactOrderItem[OrderItemKey] )", NUM),
        ("Merchandise Value", "SUM ( FactOrderItem[Price] )", MONEY),
        ("Freight on Items", "SUM ( FactOrderItem[FreightValue] )", MONEY),
        ("Freight Intensity %", "DIVIDE ( [Freight on Items], [Merchandise Value] )", PCT),
        (
            "Items Freight Exceeds Price",
            "CALCULATE ( COUNTROWS ( FactOrderItem[OrderItemKey] ), FactOrderItem[FreightOverPrice] = 1 )",
            NUM,
        ),
        (
            "Items Freight Exceeds Price %",
            "DIVIDE ( [Items Freight Exceeds Price], [Line Items] )",
            PCT,
        ),
    ],
    "DimSeller": [
        ("Sellers", "COUNTROWS ( DimSeller[SellerKey] )", NUM),
        (
            "Top 1 Seller GMV %",
            "DIVIDE ( CALCULATE ( SUM ( DimSeller[SellerGMV] ), DimSeller[GMVRank] = 1 ), [GMV] )",
            PCT,
        ),
        (
            "Top 10 Sellers GMV %",
            "DIVIDE ( CALCULATE ( SUM ( DimSeller[SellerGMV] ), DimSeller[GMVRank] <= 10 ), [GMV] )",
            PCT,
        ),
        (
            "Top 100 Sellers GMV %",
            "DIVIDE ( CALCULATE ( SUM ( DimSeller[SellerGMV] ), DimSeller[GMVRank] <= 100 ), [GMV] )",
            PCT,
        ),
        (
            "Seller HHI",
            "VAR T = [GMV] RETURN SUMX ( DimSeller, DIVIDE ( DimSeller[SellerGMV], T ) ^ 2 )",
            "0.00000",
        ),
        (
            "Cumulative GMV %",
            "VAR r = DimSeller[GMVRank] "
            "RETURN DIVIDE ( CALCULATE ( SUM ( DimSeller[SellerGMV] ), "
            "FILTER ( ALL ( DimSeller ), DimSeller[GMVRank] <= r ) ), [GMV] )",
            PCT,
        ),
    ],
    "DimCustomer": [
        ("Customers (dimension)", "COUNTROWS ( DimCustomer[CustomerKey] )", NUM),
        (
            "Repeat Customers (dimension)",
            "CALCULATE ( COUNTROWS ( DimCustomer[CustomerKey] ), DimCustomer[IsRepeat] = 1 )",
            NUM,
        ),
    ],
    "DimPaymentMethod": [
        ("Payment Methods", "COUNTROWS ( DimPaymentMethod[PaymentMethodKey] )", NUM),
        (
            "Modelled Acquiring Cost %",
            "DIVIDE ( [Modelled Acquiring Cost], [Payment Value] )",
            PCT2,
        ),
    ],
}


# ---------------------------------------------------------------------------
# Power Query
# ---------------------------------------------------------------------------
def _m_expression(table: str, columns: list[tuple[str, str, bool]]) -> str:
    dax_type = {
        "string": "type text",
        "int64": "Int64.Type",
        "double": "type number",
        "dateTime": "type date",
        "boolean": "type logical",
    }
    types = ", ".join(f'{{"{name}", {dax_type[dtype]}}}' for name, dtype, _ in columns)
    sort_column = next((name for name, _, is_key in columns if is_key), columns[0][0])
    return (
        "let\n"
        '    DataFolder = #"Data",\n'
        f'    Source = Csv.Document(File.Contents(DataFolder & "\\\\{table}.csv"),'
        f"[Delimiter=\",\", Columns={len(columns)}, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),\n"
        f'    #"Changed Type" = Table.TransformColumnTypes(Source,{{{types}}}),\n'
        f'    #"Sorted Rows" = Table.Sort(#"Changed Type",{{{{"{sort_column}", Order.Ascending}}}})\n'
        "in\n"
        '    #"Sorted Rows"'
    )


def build_model() -> dict:
    tables = []
    datasource_queries: list[dict] = []
    for table, columns in SCHEMA.items():
        hidden = HIDE_IN_REPORT.get(table, [])
        model_columns = []
        for name, dtype, is_key in columns:
            column = {
                "name": name,
                "dataType": dtype,
                "sourceColumn": name,
            }
            if is_key:
                column["isKey"] = True
            if name in hidden:
                column["isHidden"] = True
            model_columns.append(column)

        table_def = {
            "name": table,
            "dataCategory": DATA_CATEGORY[table],
            "columns": model_columns,
            # In the PBIP semantic-model format the Power Query definition
            # lives in the partition's `source.expression`. The older
            # `datasourceQueries` array is rejected outright by Power BI
            # Desktop ("Unrecognized JSON property: datasourceQueries").
            "partitions": [
                {
                    "name": table,
                    "mode": "import",
                    "source": {
                        "type": "m",
                        "expression": _m_expression(table, columns),
                    },
                }
            ],
            "annotations": [],
            "measures": [
                {"name": name, "expression": expression, "formatString": fmt}
                for name, expression, fmt in MEASURES.get(table, [])
            ],
        }
        if table == "DimDate":
            table_def["annotations"] = [
                {"name": "__PBI_TimeTableEnabled", "value": "true"}
            ]
        tables.append(table_def)

    relationships = [
        {
            "name": name,
            "fromTable": from_table,
            "fromColumn": from_column,
            "toTable": to_table,
            "toColumn": to_column,
        }
        for name, from_table, from_column, to_table, to_column in RELATIONSHIPS
    ]

    return {
        "name": PROJECT_NAME,
        "compatibilityLevel": 1500,
        "model": {
            "culture": "en-GB",
            "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "annotations": [{"name": "PBI_QueryOrder", "value": "[]"}],
            "tables": tables,
            "relationships": relationships,
            "cultures": [],
            "expressions": [],
        },
    }


# ---------------------------------------------------------------------------
# Report pages
# ---------------------------------------------------------------------------
PAGE_WIDTH = 1600
PAGE_HEIGHT = 900


def _card(name: str, x: int, y: int, w: int, h: int, measure: str, title: str,
          z: int = 0) -> dict:
    return {
        "x": x, "y": y, "z": z, "width": w, "height": h,
        "config": json.dumps(
            {
                "name": name,
                "layouts": [
                    {"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z}}
                ],
                "singleVisual": {
                    "visualType": "card",
                    "projections": {"Values": {"queryRef": measure}},
                    "vcObjects": {
                        "title": [
                            {
                                "properties": {
                                    "text": {"expr": {"Literal": {"Value": f"'{title}'"}}}
                                }
                            }
                        ],
                        "labels": [
                            {
                                "properties": {
                                    "color": {"solid": {"color": {"expr": {"Literal": {"Value": "'#1F3B57'"}}}}},
                                    "fontSize": {"expr": {"Literal": {"Value": "20D"}}},
                                }
                            }
                        ],
                    },
                },
            }
        ),
        "filters": "[]",
        "query": "",
        "dataTransforms": "",
    }


def _chart(name: str, x: int, y: int, w: int, h: int, visual_type: str,
           values: str, category: str | None, series: str | None, title: str,
           z: int = 0, legend: bool = True) -> dict:
    projections: dict[str, dict] = {"Values": {"queryRef": values}}
    if category:
        projections["Category"] = {"queryRef": category}
    if series:
        projections["Series"] = {"queryRef": series}

    vc_objects: dict = {
        "title": [
            {"properties": {"text": {"expr": {"Literal": {"Value": f"'{title}'"}}}}}
        ]
    }
    if not legend:
        vc_objects["legend"] = [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}]
    if visual_type in ("lineChart", "areaChart"):
        vc_objects["labels"] = [
            {
                "properties": {
                    "show": {"expr": {"Literal": {"Value": "false"}}},
                }
            }
        ]

    return {
        "x": x, "y": y, "z": z, "width": w, "height": h,
        "config": json.dumps(
            {
                "name": name,
                "layouts": [
                    {"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z}}
                ],
                "singleVisual": {
                    "visualType": visual_type,
                    "projections": projections,
                    "vcObjects": vc_objects,
                },
            }
        ),
        "filters": "[]",
        "query": "",
        "dataTransforms": "",
    }


def _slicer(name: str, x: int, y: int, w: int, h: int, field: str, title: str,
            z: int = 0) -> dict:
    return {
        "x": x, "y": y, "z": z, "width": w, "height": h,
        "config": json.dumps(
            {
                "name": name,
                "layouts": [
                    {"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z}}
                ],
                "singleVisual": {
                    "visualType": "slicer",
                    "projections": {"Values": {"queryRef": field}},
                    "vcObjects": {
                        "title": [
                            {"properties": {"text": {"expr": {"Literal": {"Value": f"'{title}'"}}}}}
                        ],
                        "data": [
                            {
                                "properties": {
                                    "mode": {"expr": {"Literal": {"Value": "'Between'"}}}
                                }
                            }
                        ],
                    },
                },
            }
        ),
        "filters": "[]",
        "query": "",
        "dataTransforms": "",
    }


def _textbox(name: str, x: int, y: int, w: int, h: int, text: str, size: int = 14,
             bold: bool = False, colour: str = "#1F3B57", z: int = 0) -> dict:
    return {
        "x": x, "y": y, "z": z, "width": w, "height": h,
        "config": json.dumps(
            {
                "name": name,
                "layouts": [
                    {"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z}}
                ],
                "singleVisual": {
                    "visualType": "textbox",
                    "vcObjects": {
                        "general": [
                            {
                                "properties": {
                                    "paragraphs": [
                                        {
                                            "textRuns": [
                                                {
                                                    "value": text,
                                                    "textStyle": {
                                                        "fontSize": f"{size}pt",
                                                        "fontWeight": "bold" if bold else "normal",
                                                        "color": colour,
                                                        "fontFamily": "Segoe UI",
                                                    },
                                                }
                                            ],
                                            "horizontalTextAlignment": "left",
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                },
            }
        ),
        "filters": "[]",
        "query": "",
        "dataTransforms": "",
    }


def _table(name: str, x: int, y: int, w: int, h: int, fields: list[str], title: str,
           z: int = 0) -> dict:
    projections = {"Values": [{"queryRef": f} for f in fields]}
    return {
        "x": x, "y": y, "z": z, "width": w, "height": h,
        "config": json.dumps(
            {
                "name": name,
                "layouts": [
                    {"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z}}
                ],
                "singleVisual": {
                    "visualType": "tableEx",
                    "projections": projections,
                    "vcObjects": {
                        "title": [
                            {"properties": {"text": {"expr": {"Literal": {"Value": f"'{title}'"}}}}}
                        ]
                    },
                },
            }
        ),
        "filters": "[]",
        "query": "",
        "dataTransforms": "",
    }


def _page(name: str, display: str, ordinal: int, visuals: list[dict]) -> dict:
    return {
        "id": ordinal,
        "name": name,
        "displayName": display,
        "visualContainers": visuals,
        "config": json.dumps(
            {
                "visualInteractions": [],
                "filters": "[]",
                "objects": {
                    "background": [
                        {
                            "properties": {
                                "color": {"solid": {"color": {"expr": {"Literal": {"Value": "'#FFFFFF'"}}}}}
                            }
                        }
                    ]
                },
            }
        ),
        "displayOption": 1,
        "width": PAGE_WIDTH,
        "height": PAGE_HEIGHT,
    }


def build_report() -> dict:
    pages = []

    # ---------------------------------------------------- 1. Executive overview
    visuals = [
        _textbox("title", 20, 15, 1100, 45,
                 "Olist Marketplace - Financial Operations Overview", 20, True),
        _textbox("subtitle", 20, 58, 1400, 26,
                 "Cash collected vs revenue earned | refund exposure | payment cost-to-serve | reconciliation control",
                 11, False, "#8D99AE"),
    ]
    cards = [
        ("GMV", "GMV (merchandise value)"),
        ("Cash Collected", "Cash collected"),
        ("Net Revenue", "Net revenue (after refund exposure)"),
        ("Refund Exposure", "Refund exposure"),
        ("Average Order Value", "Average order value"),
        ("Reconciliation Break Rate", "Reconciliation break rate"),
    ]
    for i, (measure, label) in enumerate(cards):
        visuals.append(_card(f"card{i}", 20 + i * 260, 95, 240, 95, measure, label, z=i))
    visuals.append(
        _chart("chartCash", 20, 205, 780, 330, "lineChart", "Cash Collected",
               "DimDate[month_start]", None, "Cash collected by month", z=10)
    )
    visuals.append(
        _chart("chartStatus", 820, 205, 760, 330, "clusteredColumnChart", "Cash Collected",
               "FactOrder[StatusClass]", None, "Cash collected by order status", z=11)
    )
    visuals.append(
        _card("cardGap", 20, 550, 380, 95, "Revenue vs Expected",
              "Cash collected above the expected charge", z=12)
    )
    visuals.append(
        _card("cardFloat", 420, 550, 380, 95, "Settlement Float",
              "Cash held on orders not yet delivered", z=13)
    )
    visuals.append(
        _card("cardNetPct", 820, 550, 380, 95, "Net Revenue % of Cash",
              "Net revenue as a share of cash collected", z=14)
    )
    visuals.append(
        _card("cardBreak", 1220, 550, 360, 95, "Gross Break Value",
              "Gross value of reconciliation breaks", z=15)
    )
    visuals.append(
        _textbox("note", 20, 665, 1560, 60,
                 "Cash collected is measured. Refund exposure is cash collected against orders that were cancelled or became "
                 "unavailable - the source data contains no refund table, so this is an exposure proxy, not a refunds ledger. "
                 "Modelled payment cost is not shown on this page: it depends on published market-rate assumptions.",
                 11, False, "#8D99AE")
    )
    pages.append(_page("ExecutiveOverview", "Executive Overview", 0, visuals))

    # ------------------------------------------------- 2. Revenue and growth
    visuals = [
        _textbox("title", 20, 15, 1100, 45, "Revenue, Growth and Cash Conversion", 20, True),
        _textbox("subtitle", 20, 58, 1400, 26,
                 "Growth decomposition on a like-for-like basis (Jan-Aug 2017 vs Jan-Aug 2018)",
                 11, False, "#8D99AE"),
        _slicer("slYear", 1300, 95, 280, 120, "DimDate[year]", "Year"),
        _chart("chartTrend", 20, 95, 780, 330, "lineChart", "Cash Collected",
               "DimDate[month_start]", "DimDate[year]", "Cash collected by month and year", z=10),
        _chart("chartQuarter", 820, 95, 760, 330, "clusteredColumnChart", "Net Revenue",
               "FactOrder[PurchaseQuarter]", None, "Net revenue by quarter", z=11),
        _card("cardYoY", 20, 445, 380, 95, "Cash YoY %", "Cash collected, year on year", z=12),
        _card("cardOrdYoY", 420, 445, 380, 95, "Orders YoY %", "Order volume, year on year", z=13),
        _card("cardAovYoY", 820, 445, 380, 95, "AOV YoY %", "Average order value, year on year", z=14),
        _chart("chartState", 1220, 95, 360, 630, "barChart", "Cash Collected",
               "DimCustomer[CustomerState]", None, "Cash collected by customer state", z=15),
        _chart("chartAov", 20, 560, 780, 300, "lineChart", "Average Order Value",
               "DimDate[month_start]", None, "Average order value by month", z=16),
        _card("cardRepeat", 820, 560, 380, 95, "Repeat Customer Rate",
              "Customers with more than one order", z=17),
        _card("cardPerCust", 1220, 745, 360, 95, "Cash per Customer",
              "Cash collected per customer", z=18),
    ]
    pages.append(_page("RevenueGrowth", "Revenue and Growth", 1, visuals))

    # ----------------------------------------------- 3. Payment mix and cost
    visuals = [
        _textbox("title", 20, 15, 1100, 45, "Payment Mix and Modelled Cost to Serve", 20, True),
        _textbox("subtitle", 20, 58, 1400, 26,
                 "MODELLED: acquiring and instalment-funding rates are published market benchmarks held in DimPaymentMethod, "
                 "not measured facts about this marketplace",
                 11, False, "#E76F51"),
        _chart("chartMix", 20, 95, 520, 330, "clusteredColumnChart", "Payment Value",
               "FactPayment[PaymentMethodKey]", None, "Payment value by method", z=10),
        _chart("chartInst", 560, 95, 520, 330, "clusteredColumnChart", "Payment Value",
               "FactPayment[Installments]", None, "Payment value by instalment count", z=11),
        _chart("chartMethodCost", 1100, 95, 480, 330, "clusteredColumnChart",
               "Modelled Total Payment Cost", "FactPayment[PaymentMethodKey]", None,
               "Modelled payment cost by method", z=12),
        _card("cardVwInst", 20, 445, 380, 95, "Value Weighted Average Installments",
              "Value-weighted average instalment depth", z=13),
        _card("cardInstValue", 420, 445, 380, 95, "Installment Funded Value",
              "Card value settled on an instalment plan", z=14),
        _card("cardPayCost", 820, 445, 380, 95, "Modelled Total Payment Cost",
              "Modelled total payment cost", z=15),
        _card("cardContrib", 1220, 445, 360, 95, "Contribution After Payment Cost",
              "Net revenue less modelled payment cost", z=16),
        _table("tblMethod", 20, 560, 780, 300,
               ["DimPaymentMethod[PaymentType]", "DimPaymentMethod[Description]",
                "DimPaymentMethod[RatePct]", "DimPaymentMethod[FixedFee]",
                "DimPaymentMethod[FundingRatePerInstallment]", "DimPaymentMethod[AssumptionNote]"],
               "Cost model assumptions (editable in DimPaymentMethod)"),
        _card("cardVoucher", 820, 560, 380, 95, "Voucher Credit",
              "Marketplace-funded promotional credit", z=17),
        _card("cardMargin", 1220, 560, 360, 95, "Contribution Margin %",
              "Contribution as a share of net revenue", z=18),
    ]
    pages.append(_page("PaymentCostToServe", "Payment Mix and Cost to Serve", 2, visuals))

    # ----------------------------------------- 4. Exposure and reconciliation
    visuals = [
        _textbox("title", 20, 15, 1100, 45, "Refund Exposure and Reconciliation Control", 20, True),
        _textbox("subtitle", 20, 58, 1400, 26,
                 "Cash collected but owed back, and cash that cannot be tied to any merchandise record",
                 11, False, "#8D99AE"),
        _slicer("slStatus", 1290, 95, 290, 130, "FactOrder[StatusClass]", "Order status class"),
        _slicer("slMethod", 1290, 235, 290, 130, "FactOrder[PaymentMethodKey]", "Payment method"),
        _card("cardExpRate", 20, 95, 380, 95, "Refund Exposure Rate",
              "Refund exposure as a share of cash", z=10),
        _card("cardBreakRate", 420, 95, 380, 95, "Reconciliation Break Rate",
              "Orders failing the cash-to-order reconciliation", z=11),
        _card("cardGrossBreak", 820, 95, 380, 95, "Gross Break Value",
              "Absolute value of the reconciliation breaks", z=12),
        _card("cardNoMerch", 1220, 95, 360, 95, "Cash Without Merchandise",
              "Cash on orders with no line items", z=13),
        _chart("chartExposure", 20, 205, 780, 320, "lineChart", "Refund Exposure",
               "DimDate[month_start]", None, "Refund exposure by month", z=14),
        _chart("chartExpStatus", 820, 205, 450, 320, "clusteredColumnChart", "Refund Exposure",
               "FactOrder[OrderStatus]", None, "Refund exposure by order status", z=15),
        _chart("chartBreakType", 20, 545, 780, 300, "clusteredColumnChart", "Gross Break Value",
               "FactOrder[StatusClass]", None, "Reconciliation break value by status", z=16),
        _table("tblExceptions", 820, 545, 760, 300,
               ["FactOrder[OrderKey]", "FactOrder[OrderStatus]", "FactOrder[CashCollected]",
                "FactOrder[ExpectedCharge]", "FactOrder[ReconDelta]", "FactOrder[LineItemCount]"],
               "Reconciliation exceptions (filter ReconBreak = 1 for the full list)"),
    ]
    pages.append(_page("ExposureAndControl", "Exposure and Reconciliation", 3, visuals))

    # ------------------------------- 5. Concentration, logistics and dispute
    visuals = [
        _textbox("title", 20, 15, 1200, 45, "Concentration, Logistics Cost and Dispute Risk", 20, True),
        _textbox("subtitle", 20, 58, 1400, 26,
                 "Counterparty concentration, freight burden by category, and the dispute rate by instalment depth",
                 11, False, "#8D99AE"),
        _card("cardHhi", 20, 95, 380, 95, "Seller HHI", "Seller concentration index", z=10),
        _card("cardTop10", 420, 95, 380, 95, "Top 10 Sellers GMV %",
              "Share of GMV from the ten largest sellers", z=11),
        _card("cardSellers", 820, 95, 380, 95, "Sellers", "Active sellers", z=12),
        _card("cardFreight", 1220, 95, 360, 95, "Freight Ratio",
              "Freight collected as a share of GMV", z=13),
        _chart("chartPareto", 20, 205, 780, 330, "lineChart", "Cumulative GMV %",
               "DimSeller[GMVRank]", None, "Seller concentration curve (Pareto)", z=14),
        _chart("chartCatFreight", 820, 205, 760, 330, "barChart", "Freight Intensity %",
               "DimProduct[CategoryEnglish]", None, "Freight burden by product category", z=15),
        _chart("chartDispute", 20, 555, 780, 290, "clusteredColumnChart", "Dispute Rate",
               "FactOrder[MaxInstallments]", None,
               "Dispute rate by instalment depth (score 1 or 2 out of 5)", z=16),
        _chart("chartDisputeValue", 820, 555, 760, 290, "clusteredColumnChart", "Disputed Value",
               "FactOrder[StatusClass]", None, "Disputed value at risk by order status", z=17),
    ]
    pages.append(_page("ConcentrationAndRisk", "Concentration and Risk", 4, visuals))

    return {
        "id": 0,
        "resourcePackages": [],
        "sections": pages,
        "config": json.dumps(
            {
                "activeSectionIndex": 0,
                "defaultDrillFilterOtherVisuals": True,
                "settings": {"useStylableVisualContainerHeader": True},
            }
        ),
        "layoutOptimization": 0,
        "publicCustomVisuals": [],
        "pods": [],
    }


def write_measures_dax(model: dict) -> None:
    """Export the DAX catalogue as a readable .dax file.

    The file is generated from the same definitions that build model.bim, so
    the documentation and the model can never disagree.
    """
    lines = [
        "// " + PROJECT_NAME + " - DAX measure catalogue",
        "//",
        "// Generated by src/build_powerbi_model.py from the same definitions that",
        "// build the semantic model, so this file and the model cannot disagree.",
        "//",
        "// Modelled measures (marked MODELLED) depend on the rates held in",
        "// DimPaymentMethod. Edit those rates there and every modelled measure",
        "// re-computes - no DAX edit is needed.",
        "",
    ]
    for table in model["model"]["tables"]:
        measures = table.get("measures", [])
        if not measures:
            continue
        lines.append(f"// ===== {table['name']} " + "=" * (58 - len(table["name"])))
        lines.append("")
        for measure in measures:
            expression = measure["expression"]
            lines.append(f"{measure['name']} =")
            for part in expression.split(" "):
                pass
            lines.append(f"    {expression}")
            lines.append(f"    // format: {measure.get('formatString', '')}")
            lines.append("")
        lines.append("")
    path = config.POWERBI_DIR / "measures.dax"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[build_powerbi_model] wrote measures.dax: "
          f"{sum(len(t.get('measures', [])) for t in model['model']['tables'])} measures")


# ---------------------------------------------------------------------------
# PBIR (Power BI Enhanced Report Format)
#
# Power BI Desktop loads a PBIP report from the `definition/` folder in the
# PBIR format. The legacy `report.json` format carries field bindings in a
# `singleVisual.projections` block, which Power BI Desktop parses for the
# visual type, position and title but DISCARDS - the visuals then render
# empty. The PBIR format binds fields through `visual.query.queryState`,
# which is what the generator emits here.
#
# Each projection entry is:
#   {"field": {"Measure"|"Column": {"Expression": {"SourceRef": {"Entity": ...}},
#                                    "Property": ...}},
#    "Property": ..., "Name": "Table.Property"}
# and `visual.projections` maps the visual ROLE ("Y", "Category", "Values",
# ...) to the same fields by `queryRef`.
# ---------------------------------------------------------------------------
PBIR_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
CHART_ROLES = {"lineChart", "clusteredColumnChart", "barChart", "areaChart",
               "stackedColumnChart", "columnChart"}


def resolve_field(ref: str) -> tuple[str, str, bool]:
    """Resolve a query reference into (table, property, is_measure).

    Accepts "Table[Property]" for a column and a bare measure name for a
    measure, which is how the report definitions refer to them.
    """
    if "[" in ref:
        table, prop = ref.split("[", 1)
        return table, prop.rstrip("]"), False
    for table, measures in MEASURES.items():
        for name, _expression, _fmt in measures:
            if name == ref:
                return table, name, True
    raise KeyError(f"cannot resolve field reference {ref!r}")


def _pbir_projection(ref: str) -> dict:
    table, prop, is_measure = resolve_field(ref)
    kind = "Measure" if is_measure else "Column"
    return {
        "field": {
            kind: {
                "Expression": {"SourceRef": {"Entity": table}},
                "Property": prop,
            }
        },
        "Property": prop,
        "Name": f"{table}.{prop}",
    }


def build_pbir(report: dict) -> None:
    """Write the PBIR `definition/` folder for the report."""
    pages_dir = PBIR_DIR / "pages"
    if PBIR_DIR.exists():
        import shutil
        shutil.rmtree(PBIR_DIR)
    pages_dir.mkdir(parents=True, exist_ok=True)

    (PBIR_DIR / "version.json").write_text(
        json.dumps(
            {
                "$schema": f"{PBIR_SCHEMA}/versionMetadata/1.0.0/schema.json",
                "version": "2.0.0",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (PBIR_DIR / "report.json").write_text(
        json.dumps(
            {
                "$schema": f"{PBIR_SCHEMA}/report/3.3.0/schema.json",
                "themeCollection": {},
                "objects": {},
                "settings": {
                    "useStylableVisualContainerHeader": True,
                    "defaultDrillFilterOtherVisuals": True,
                    "useEnhancedTooltips": False,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    page_order = []
    for section in report["sections"]:
        page_name = section["name"]
        page_order.append(page_name)
        page_dir = pages_dir / page_name
        visuals_dir = page_dir / "visuals"
        visuals_dir.mkdir(parents=True, exist_ok=True)

        (page_dir / "page.json").write_text(
            json.dumps(
                {
                    "$schema": f"{PBIR_SCHEMA}/page/2.1.0/schema.json",
                    "name": page_name,
                    "displayName": section["displayName"],
                    "displayOption": "FitToPage",
                    "height": section.get("height", PAGE_HEIGHT),
                    "width": section.get("width", PAGE_WIDTH),
                    "objects": {
                        "background": [
                            {
                                "properties": {
                                    "color": {
                                        "solid": {
                                            "color": {
                                                "expr": {"Literal": {"Value": "'#FFFFFF'"}}
                                            }
                                        }
                                    }
                                }
                            }
                        ]
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        for visual in section["visualContainers"]:
            cfg = json.loads(visual["config"])
            single = cfg.get("singleVisual", {})
            visual_type = single.get("visualType", "textbox")
            projections = single.get("projections", {})

            query_state: dict[str, dict] = {}
            projection_map: dict[str, list[dict]] = {}

            for role, value in projections.items():
                refs = value if isinstance(value, list) else [value]
                refs = [r["queryRef"] for r in refs]
                # a chart takes its measure in the "Y" role; a card, a table
                # and a slicer take it in "Values"
                if role == "Values" and visual_type in CHART_ROLES:
                    role = "Y"
                entries = [_pbir_projection(ref) for ref in refs]
                query_state[role] = {"projections": entries}
                projection_map[role] = [
                    {"queryRef": entry["Name"]} for entry in entries
                ]

            visual_object: dict = {
                "visualType": visual_type,
            }
            if query_state:
                visual_object["query"] = {"queryState": query_state}
            if projection_map:
                visual_object["projections"] = projection_map
            if single.get("vcObjects"):
                visual_object["visualContainerObjects"] = single["vcObjects"]

            (visuals_dir / cfg["name"] / "visual.json").parent.mkdir(
                parents=True, exist_ok=True)
            (visuals_dir / cfg["name"] / "visual.json").write_text(
                json.dumps(
                    {
                        "$schema": f"{PBIR_SCHEMA}/visualContainer/2.14.0/schema.json",
                        "name": cfg["name"],
                        "position": {
                            "x": visual["x"],
                            "y": visual["y"],
                            "z": visual["z"],
                            "height": visual["height"],
                            "width": visual["width"],
                            "tabOrder": visual["z"],
                        },
                        "visual": visual_object,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

    (pages_dir / "pages.json").write_text(
        json.dumps(
            {
                "$schema": f"{PBIR_SCHEMA}/pagesMetadata/1.1.0/schema.json",
                "pageOrder": page_order,
                "activePageName": page_order[0] if page_order else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # the project-level platform descriptor
    (REPORT_DIR / ".platform").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
                "metadata": {"type": "Report", "displayName": PROJECT_NAME},
                "config": {"version": "2.0", "logicalId": PROJECT_ID},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[build_powerbi_model] wrote PBIR definition: {len(page_order)} pages")


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    model = build_model()
    (MODEL_DIR / "model.bim").write_text(json.dumps(model, indent=2), encoding="utf-8")
    print(f"[build_powerbi_model] wrote model.bim: {len(model['model']['tables'])} tables, "
          f"{sum(len(t['measures']) for t in model['model']['tables'])} measures, "
          f"{len(model['model']['relationships'])} relationships")
    write_measures_dax(model)

    report = build_report()
    (REPORT_DIR / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    visuals = sum(len(s["visualContainers"]) for s in report["sections"])
    print(f"[build_powerbi_model] wrote report.json: {len(report['sections'])} pages, {visuals} visuals")
    build_pbir(report)

    (REPORT_DIR / "definition.pbir").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
                "version": "4.0",
                "datasetReference": {"byPath": {"path": f"../{PROJECT_NAME}.SemanticModel"}},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (MODEL_DIR / "definition.pbism").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
                "version": "1.0",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (PBIP_DIR / f"{PROJECT_NAME}.pbip").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
                "version": "1.0",
                "artifacts": [{"report": {"path": f"{PROJECT_NAME}.Report"}}],
                "settings": {"enableAutoRecovery": True},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[build_powerbi_model] wrote PBIP project at {PBIP_DIR}")


if __name__ == "__main__":
    main()
