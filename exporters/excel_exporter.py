"""Excel 4-sheet report exporter module.

PLAN 6.2:
Generates Summary_<YYYY>-<MM>.xlsx with 4 sheets:
1. Invoice Overview: Date, Bill No, Vendor, Category, Subtotal, Tax, Total, Status, Source File.
2. Line Items Detail: Each line item with invoice_ref link.
3. Discrepancy Alerts: REVIEW_NEEDED / FAILED invoices with detailed reasons, link to file, and audit columns.
4. Duplicates: Suspected duplicate invoice pairs.
All numeric amounts formatted with openpyxl number_format.
Calls excel_safety for formula protection and atomic writes.
"""

from decimal import Decimal
from pathlib import Path
import re
from typing import Any, List, Optional, Tuple, Union
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from models.schema import CanonicalInvoice, InvoiceStatus, DocType
from exporters.excel_safety import sanitize_excel_cell, save_workbook_atomic

CURRENCY_FORMAT = "#,##0.00"
QTY_FORMAT = "#,##0.##"
MONTH_REGEX = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")


# Header column definitions matching PLAN 6.2
OVERVIEW_HEADERS = [
    "Ngày",
    "Số bill",
    "Nhà cung cấp",
    "Phân loại chi phí",
    "Tiền trước thuế",
    "Thuế",
    "Tổng tiền",
    "Trạng thái",
    "Tên file nguồn",
]

LINE_ITEMS_HEADERS = [
    "invoice_ref",
    "Tên hàng",
    "Số lượng",
    "Đơn vị",
    "Đơn giá",
    "Thành tiền",
    "Loại",
    "Lỗi tính toán",
]

ALERTS_HEADERS = [
    "Ngày",
    "Số bill",
    "Nhà cung cấp",
    "Trạng thái",
    "Lý do cảnh báo",
    "File gốc",
    "Corrected by",
    "Note",
]

DUPLICATES_HEADERS = [
    "Source A",
    "Source B",
    "Reason",
]


def _apply_header_style(ws, headers: List[str]) -> None:
    """Append header row and apply professional formatting."""
    ws.append(headers)
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
    ws.row_dimensions[1].height = 24


def _write_cell_value(
    ws,
    row: int,
    col: int,
    value: Any,
    *,
    is_amount: bool = False,
    is_qty: bool = False,
    align_center: bool = False,
) -> None:
    """Format and write value to cell, handling formula neutralization and number formatting."""
    cell = ws.cell(row=row, column=col)
    if value is None:
        cell.value = None
        return

    if is_amount:
        if isinstance(value, (int, float, Decimal)):
            cell.value = float(value)
            cell.number_format = CURRENCY_FORMAT
            cell.alignment = Alignment(horizontal="right", vertical="center")
        else:
            cell.value = sanitize_excel_cell(str(value))
    elif is_qty:
        if isinstance(value, (int, float, Decimal)):
            cell.value = float(value)
            cell.number_format = QTY_FORMAT
            cell.alignment = Alignment(horizontal="right", vertical="center")
        else:
            cell.value = sanitize_excel_cell(str(value))
    else:
        raw_val = value.value if hasattr(value, "value") else str(value)
        cell.value = sanitize_excel_cell(raw_val)
        if align_center:
            cell.alignment = Alignment(horizontal="center", vertical="center")


def _auto_fit_columns(ws) -> None:
    """Auto-adjust worksheet column widths within reasonable bounds."""
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(min(max_len + 3, 50), 12)


def _is_duplicate(inv: CanonicalInvoice) -> bool:
    return (
        inv.status in (InvoiceStatus.DUPLICATE, "DUPLICATE")
        or bool(getattr(inv, "is_duplicate", False))
    )


def _is_statement_or_other(inv: CanonicalInvoice) -> bool:
    doc_val = (inv.doc_type.value if hasattr(inv.doc_type, "value") else str(inv.doc_type or "")).lower()
    return doc_val in ("statement", "other")


def export_excel_summary(
    invoices: List[CanonicalInvoice],
    duplicates: List[Tuple[str, str, str]],
    output_dir: Union[str, Path],
    month: str,
) -> Path:
    """Generate Excel 4-sheet summary workbook.

    Args:
        invoices: List of parsed CanonicalInvoice instances.
        duplicates: List of duplicate pairs detected (source_a, source_b, reason).
        output_dir: Directory to save workbook.
        month: Target month string 'YYYY-MM'.

    Returns:
        Path to the written .xlsx file.
    """
    if not isinstance(month, str) or not MONTH_REGEX.match(month):
        raise ValueError(f"Invalid month format: {month!r}. Expected YYYY-MM (e.g. '2026-08').")

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"Summary_{month}.xlsx"

    wb = openpyxl.Workbook()

    # Sheet 1: Invoice Overview
    # Exclude DUPLICATE, statement, and other from main cost overview
    ws_overview = wb.active if wb.active is not None else wb.create_sheet(title="Invoice Overview")
    ws_overview.title = "Invoice Overview"
    _apply_header_style(ws_overview, OVERVIEW_HEADERS)

    overview_invoices = [
        inv for inv in invoices
        if not _is_duplicate(inv) and not _is_statement_or_other(inv)
    ]

    for row_idx, inv in enumerate(overview_invoices, start=2):
        cat_val = inv.category.value if hasattr(inv.category, "value") else str(inv.category or "")
        stat_val = inv.status.value if hasattr(inv.status, "value") else str(inv.status or "")
        bill_no = inv.invoice_no if inv.invoice_no else Path(inv.source_file).name

        _write_cell_value(ws_overview, row_idx, 1, inv.invoice_date, align_center=True)
        _write_cell_value(ws_overview, row_idx, 2, bill_no)
        _write_cell_value(ws_overview, row_idx, 3, inv.vendor_name)
        _write_cell_value(ws_overview, row_idx, 4, cat_val)
        _write_cell_value(ws_overview, row_idx, 5, inv.subtotal, is_amount=True)
        _write_cell_value(ws_overview, row_idx, 6, inv.tax, is_amount=True)
        _write_cell_value(ws_overview, row_idx, 7, inv.grand_total, is_amount=True)
        _write_cell_value(ws_overview, row_idx, 8, stat_val, align_center=True)
        _write_cell_value(ws_overview, row_idx, 9, inv.source_file)

    _auto_fit_columns(ws_overview)

    # Sheet 2: Line Items Detail
    # Exclude DUPLICATE invoice line items to avoid double counting
    ws_lines = wb.create_sheet(title="Line Items Detail")
    _apply_header_style(ws_lines, LINE_ITEMS_HEADERS)

    line_row_idx = 2
    for inv in invoices:
        if _is_duplicate(inv):
            continue

        ref = inv.invoice_no if inv.invoice_no else Path(inv.source_file).name

        for item in inv.line_items:
            kind_val = item.kind.value if hasattr(item.kind, "value") else str(item.kind or "")
            _write_cell_value(ws_lines, line_row_idx, 1, ref)
            _write_cell_value(ws_lines, line_row_idx, 2, item.item_name)
            _write_cell_value(ws_lines, line_row_idx, 3, item.qty, is_qty=True)
            _write_cell_value(ws_lines, line_row_idx, 4, item.unit or "")
            _write_cell_value(ws_lines, line_row_idx, 5, item.unit_price, is_amount=True)
            _write_cell_value(ws_lines, line_row_idx, 6, item.line_total, is_amount=True)
            _write_cell_value(ws_lines, line_row_idx, 7, kind_val, align_center=True)
            _write_cell_value(ws_lines, line_row_idx, 8, item.math_error or "")
            line_row_idx += 1

        for charge in inv.charges:
            _write_cell_value(ws_lines, line_row_idx, 1, ref)
            _write_cell_value(ws_lines, line_row_idx, 2, charge.description)
            _write_cell_value(ws_lines, line_row_idx, 3, None, is_qty=True)
            _write_cell_value(ws_lines, line_row_idx, 4, "")
            _write_cell_value(ws_lines, line_row_idx, 5, charge.amount, is_amount=True)
            _write_cell_value(ws_lines, line_row_idx, 6, charge.amount, is_amount=True)
            _write_cell_value(ws_lines, line_row_idx, 7, "charge", align_center=True)
            _write_cell_value(ws_lines, line_row_idx, 8, "")
            line_row_idx += 1

    _auto_fit_columns(ws_lines)

    # Sheet 3: Discrepancy Alerts
    # Captures REVIEW_NEEDED, FAILED, and excluded statement/other invoices
    ws_alerts = wb.create_sheet(title="Discrepancy Alerts")
    _apply_header_style(ws_alerts, ALERTS_HEADERS)

    alert_row_idx = 2
    for inv in invoices:
        if _is_duplicate(inv):
            continue

        is_stmt_other = _is_statement_or_other(inv)
        is_review_or_failed = (
            inv.status in (InvoiceStatus.REVIEW_NEEDED, InvoiceStatus.FAILED, "REVIEW_NEEDED", "FAILED")
            or bool(inv.review_reasons)
            or is_stmt_other
        )
        if not is_review_or_failed:
            continue

        stat_val = inv.status.value if hasattr(inv.status, "value") else str(inv.status or "")
        bill_no = inv.invoice_no if inv.invoice_no else Path(inv.source_file).name
        if inv.review_reasons:
            reasons = inv.review_reasons
        elif is_stmt_other:
            doc_val = inv.doc_type.value if hasattr(inv.doc_type, "value") else str(inv.doc_type or "")
            reasons = [f"Excluded document type: {doc_val}"]
        else:
            reasons = [""]

        for reason in reasons:
            _write_cell_value(ws_alerts, alert_row_idx, 1, inv.invoice_date, align_center=True)
            _write_cell_value(ws_alerts, alert_row_idx, 2, bill_no)
            _write_cell_value(ws_alerts, alert_row_idx, 3, inv.vendor_name)
            _write_cell_value(ws_alerts, alert_row_idx, 4, stat_val, align_center=True)
            _write_cell_value(ws_alerts, alert_row_idx, 5, reason)
            _write_cell_value(ws_alerts, alert_row_idx, 6, inv.source_file)

            # Add clickable hyperlink for quick inspection of original file
            if inv.source_file:
                cell_file = ws_alerts.cell(row=alert_row_idx, column=6)
                cell_file.hyperlink = str(inv.source_file)
                cell_file.font = Font(name="Calibri", size=11, color="0563C1", underline="single")

            _write_cell_value(ws_alerts, alert_row_idx, 7, "")  # Corrected by
            _write_cell_value(ws_alerts, alert_row_idx, 8, "")  # Note
            alert_row_idx += 1

    _auto_fit_columns(ws_alerts)

    # Sheet 4: Duplicates
    # Captures duplicate pairs and any invoice marked as DUPLICATE
    ws_duplicates = wb.create_sheet(title="Duplicates")
    _apply_header_style(ws_duplicates, DUPLICATES_HEADERS)

    dup_row_idx = 2
    seen_dup_sources = set()

    for dup in duplicates:
        if isinstance(dup, (tuple, list)):
            source_a = dup[0] if len(dup) > 0 else ""
            source_b = dup[1] if len(dup) > 1 else ""
            reason = dup[2] if len(dup) > 2 else ""
        elif isinstance(dup, dict):
            source_a = dup.get("source_a", "")
            source_b = dup.get("source_b", "")
            reason = dup.get("reason", "")
        else:
            source_a = getattr(dup, "source_a", "")
            source_b = getattr(dup, "source_b", "")
            reason = getattr(dup, "reason", "")

        _write_cell_value(ws_duplicates, dup_row_idx, 1, source_a)
        _write_cell_value(ws_duplicates, dup_row_idx, 2, source_b)
        _write_cell_value(ws_duplicates, dup_row_idx, 3, reason)
        dup_row_idx += 1
        if source_a:
            seen_dup_sources.add(source_a)

    for inv in invoices:
        if _is_duplicate(inv) and inv.source_file not in seen_dup_sources:
            orig = getattr(inv, "duplicate_of", "") or ""
            _write_cell_value(ws_duplicates, dup_row_idx, 1, inv.source_file)
            _write_cell_value(ws_duplicates, dup_row_idx, 2, orig)
            _write_cell_value(ws_duplicates, dup_row_idx, 3, "Duplicate invoice")
            dup_row_idx += 1
            seen_dup_sources.add(inv.source_file)

    _auto_fit_columns(ws_duplicates)

    # Save atomically
    save_workbook_atomic(wb, target_path)
    return target_path

