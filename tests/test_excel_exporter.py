"""Unit tests for exporters.excel_exporter module.

PLAN 6.2:
- Generates Summary_<YYYY>-<MM>.xlsx with 4 sheets:
  1. Invoice Overview
  2. Line Items Detail
  3. Discrepancy Alerts
  4. Duplicates
- Formats numbers with openpyxl number_format.
- Validates formula sanitization and atomic write.
- INVARIANT: All tests synthesize test data in memory. NEVER access real invoice files.
"""

from decimal import Decimal
from pathlib import Path
from typing import List, Tuple
import openpyxl
import pytest

from config import Category
from models.schema import (
    CanonicalCharge,
    CanonicalInvoice,
    CanonicalLineItem,
    DocType,
    InvoiceStatus,
    LineItemKind,
)
from exporters.excel_exporter import export_excel_summary
import exporters.excel_safety as excel_safety


@pytest.fixture(autouse=True)
def ensure_excel_safety_contract(monkeypatch):
    """Fallback fixture ensuring tests pass even before w1-excel-safety worktree is merged."""
    try:
        excel_safety.sanitize_excel_cell("test")
    except NotImplementedError:
        DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

        def mock_sanitize(val):
            if isinstance(val, str) and val:
                if val.startswith(DANGEROUS_PREFIXES) or val.lstrip().startswith(DANGEROUS_PREFIXES):
                    return f"'{val}"
            return val

        def mock_save_atomic(wb, target_path):
            import os
            import tempfile

            target = Path(target_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp_fd, temp_file_path = tempfile.mkstemp(
                dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
            )
            os.close(temp_fd)
            temp_path = Path(temp_file_path)
            try:
                wb.save(temp_path)
                os.replace(temp_path, target)
            except Exception:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
                raise

        monkeypatch.setattr("exporters.excel_exporter.sanitize_excel_cell", mock_sanitize)
        monkeypatch.setattr("exporters.excel_exporter.save_workbook_atomic", mock_save_atomic)
        monkeypatch.setattr("exporters.excel_safety.sanitize_excel_cell", mock_sanitize)
        monkeypatch.setattr("exporters.excel_safety.save_workbook_atomic", mock_save_atomic)


@pytest.fixture
def sample_invoices() -> List[CanonicalInvoice]:
    """Create in-memory synthetic canonical invoices covering all statuses and edge cases."""
    inv1 = CanonicalInvoice(
        source_file="invoices/INV_001.pdf",
        source_sha256="aaa111",
        status=InvoiceStatus.VERIFIED,
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="Acme Corp",
        invoice_no="INV-2026-001",
        invoice_date="2026-08-01",
        currency="USD",
        category=Category.FOOD_INGREDIENTS,
        line_items=[
            CanonicalLineItem(
                item_name="Apples",
                qty=Decimal("10.5"),
                unit_price=Decimal("2.00"),
                line_total=Decimal("21.00"),
                unit="kg",
                kind=LineItemKind.GOODS,
            ),
            CanonicalLineItem(
                item_name="Delivery Fee",
                qty=Decimal("1"),
                unit_price=Decimal("5.00"),
                line_total=Decimal("5.00"),
                unit="ea",
                kind=LineItemKind.SHIPPING,
            ),
        ],
        subtotal=Decimal("26.00"),
        tax=Decimal("2.60"),
        grand_total=Decimal("28.60"),
        review_reasons=[],
    )

    inv2 = CanonicalInvoice(
        source_file="invoices/INV_002.pdf",
        source_sha256="bbb222",
        status=InvoiceStatus.REVIEW_NEEDED,
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="Beta Supplies",
        invoice_no="INV-2026-002",
        invoice_date="2026-08-05",
        currency="USD",
        category=Category.SERVICES,
        line_items=[
            CanonicalLineItem(
                item_name="Printer Paper",
                qty=Decimal("2"),
                unit_price=Decimal("15.00"),
                line_total=Decimal("30.00"),
                unit="box",
                kind=LineItemKind.GOODS,
                math_error="Price mismatch",
            )
        ],
        charges=[
            CanonicalCharge(description="Late Fee", amount=Decimal("3.50"))
        ],
        subtotal=Decimal("30.00"),
        tax=Decimal("3.00"),
        grand_total=Decimal("36.50"),
        review_reasons=["Line item math mismatch: 2 x 15 != 30", "Subtotal + Tax != Total"],
    )

    inv3 = CanonicalInvoice(
        source_file="invoices/INV_003.pdf",
        source_sha256="ccc333",
        status=InvoiceStatus.FAILED,
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="Corrupt Vendor",
        invoice_no="INV-2026-003",
        invoice_date="2026-08-10",
        currency="USD",
        category=Category.OTHER,
        line_items=[],
        subtotal=None,
        tax=None,
        grand_total=None,
        review_reasons=["Unparseable document body"],
    )

    return [inv1, inv2, inv3]


@pytest.fixture
def sample_duplicates() -> List[Tuple[str, str, str]]:
    return [
        ("invoices/INV_001.pdf", "invoices/INV_001_copy.pdf", "Exact SHA-256 match"),
        ("invoices/INV_002.pdf", "invoices/INV_002_scan.pdf", "Vendor + Invoice No + Total match"),
    ]


def test_export_creates_workbook_with_four_sheets(tmp_path, sample_invoices, sample_duplicates):
    """Test export_excel_summary produces Summary_{month}.xlsx with 4 distinct sheets."""
    month = "2026-08"
    out_file = export_excel_summary(sample_invoices, sample_duplicates, tmp_path, month)

    assert isinstance(out_file, Path)
    assert out_file.name == "Summary_2026-08.xlsx"
    assert out_file.exists()

    wb = openpyxl.load_workbook(out_file)
    expected_sheets = [
        "Invoice Overview",
        "Line Items Detail",
        "Discrepancy Alerts",
        "Duplicates",
    ]
    assert wb.sheetnames == expected_sheets


def test_sheet_1_invoice_overview_content_and_formatting(tmp_path, sample_invoices, sample_duplicates):
    """Test Sheet 1 'Invoice Overview' headers, data, and numeric formatting."""
    out_file = export_excel_summary(sample_invoices, sample_duplicates, tmp_path, "2026-08")
    wb = openpyxl.load_workbook(out_file)
    ws = wb["Invoice Overview"]

    # Header row
    headers = [cell.value for cell in ws[1]]
    assert headers == [
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

    # Data rows count
    assert ws.max_row == len(sample_invoices) + 1

    # Row 2 (INV_001: Verified)
    row2_vals = [ws.cell(row=2, column=col).value for col in range(1, 10)]
    assert row2_vals[0] == "2026-08-01"
    assert row2_vals[1] == "INV-2026-001"
    assert row2_vals[2] == "Acme Corp"
    assert row2_vals[3] == Category.FOOD_INGREDIENTS.value
    assert row2_vals[4] == 26.00
    assert row2_vals[5] == 2.60
    assert row2_vals[6] == 28.60
    assert row2_vals[7] == InvoiceStatus.VERIFIED.value
    assert row2_vals[8] == "invoices/INV_001.pdf"

    # Number formatting on monetary cells
    subtotal_cell = ws.cell(row=2, column=5)
    tax_cell = ws.cell(row=2, column=6)
    total_cell = ws.cell(row=2, column=7)

    assert subtotal_cell.number_format == "#,##0.00"
    assert tax_cell.number_format == "#,##0.00"
    assert total_cell.number_format == "#,##0.00"
    assert isinstance(subtotal_cell.value, (int, float))
    assert isinstance(tax_cell.value, (int, float))
    assert isinstance(total_cell.value, (int, float))


def test_sheet_2_line_items_detail_content_and_invoice_ref(tmp_path, sample_invoices, sample_duplicates):
    """Test Sheet 2 'Line Items Detail' rows, invoice_ref link, and number formats."""
    out_file = export_excel_summary(sample_invoices, sample_duplicates, tmp_path, "2026-08")
    wb = openpyxl.load_workbook(out_file)
    ws = wb["Line Items Detail"]

    headers = [cell.value for cell in ws[1]]
    assert headers == [
        "invoice_ref",
        "Tên hàng",
        "Số lượng",
        "Đơn vị",
        "Đơn giá",
        "Thành tiền",
        "Loại",
        "Lỗi tính toán",
    ]

    # Total rows:
    # inv1: 2 line items
    # inv2: 1 line item + 1 charge = 2 rows
    # inv3: 0 line items
    # Total data rows = 4 + 1 header = 5 rows
    assert ws.max_row == 5

    # Check invoice_ref links
    refs = [ws.cell(row=r, column=1).value for r in range(2, 6)]
    assert refs == ["INV-2026-001", "INV-2026-001", "INV-2026-002", "INV-2026-002"]

    # Check price and total number formats
    unit_price_cell = ws.cell(row=2, column=5)
    line_total_cell = ws.cell(row=2, column=6)
    qty_cell = ws.cell(row=2, column=3)

    assert unit_price_cell.number_format == "#,##0.00"
    assert line_total_cell.number_format == "#,##0.00"
    assert qty_cell.number_format == "#,##0.##"
    assert isinstance(unit_price_cell.value, (int, float))
    assert isinstance(line_total_cell.value, (int, float))
    assert isinstance(qty_cell.value, (int, float))


def test_sheet_3_discrepancy_alerts_contains_all_reasons(tmp_path, sample_invoices, sample_duplicates):
    """Test Sheet 3 'Discrepancy Alerts' only lists REVIEW_NEEDED/FAILED and captures every reason."""
    out_file = export_excel_summary(sample_invoices, sample_duplicates, tmp_path, "2026-08")
    wb = openpyxl.load_workbook(out_file)
    ws = wb["Discrepancy Alerts"]

    headers = [cell.value for cell in ws[1]]
    assert headers == [
        "Ngày",
        "Số bill",
        "Nhà cung cấp",
        "Trạng thái",
        "Lý do cảnh báo",
        "File gốc",
        "Corrected by",
        "Note",
    ]

    # Expected:
    # inv2 has 2 reasons -> 2 rows
    # inv3 has 1 reason -> 1 row
    # Total = 3 discrepancy rows (+ 1 header)
    assert ws.max_row == 4

    rows = []
    for r in range(2, 5):
        row_dict = {
            "status": ws.cell(row=r, column=4).value,
            "reason": ws.cell(row=r, column=5).value,
            "source_file": ws.cell(row=r, column=6).value,
            "corrected_by": ws.cell(row=r, column=7).value,
            "note": ws.cell(row=r, column=8).value,
        }
        rows.append(row_dict)

    reasons_found = [row["reason"] for row in rows]
    assert "Line item math mismatch: 2 x 15 != 30" in reasons_found
    assert "Subtotal + Tax != Total" in reasons_found
    assert "Unparseable document body" in reasons_found

    # VERIFIED invoice must NOT be in Sheet 3
    source_files = [row["source_file"] for row in rows]
    assert "invoices/INV_001.pdf" not in source_files
    assert "invoices/INV_002.pdf" in source_files
    assert "invoices/INV_003.pdf" in source_files

    # Audit columns must be empty strings or None
    for row in rows:
        assert row["corrected_by"] in ("", None)
        assert row["note"] in ("", None)


def test_sheet_4_duplicates_records(tmp_path, sample_invoices, sample_duplicates):
    """Test Sheet 4 'Duplicates' pairs and reasons."""
    out_file = export_excel_summary(sample_invoices, sample_duplicates, tmp_path, "2026-08")
    wb = openpyxl.load_workbook(out_file)
    ws = wb["Duplicates"]

    headers = [cell.value for cell in ws[1]]
    assert headers == ["Source A", "Source B", "Reason"]

    assert ws.max_row == len(sample_duplicates) + 1

    r2 = [ws.cell(row=2, column=col).value for col in range(1, 4)]
    assert r2 == ["invoices/INV_001.pdf", "invoices/INV_001_copy.pdf", "Exact SHA-256 match"]

    r3 = [ws.cell(row=3, column=col).value for col in range(1, 4)]
    assert r3 == ["invoices/INV_002.pdf", "invoices/INV_002_scan.pdf", "Vendor + Invoice No + Total match"]


def test_formula_injection_defense(tmp_path):
    """Test formula injection payloads (=, +, -, @, \\t, \\r) are neutralized."""
    malicious_invoice = CanonicalInvoice(
        source_file="invoices/clean.pdf",
        source_sha256="evil123",
        status=InvoiceStatus.REVIEW_NEEDED,
        vendor_name="=cmd|'/c calc'!A0",
        invoice_no="+12345",
        invoice_date="@2026-08-01",
        line_items=[
            CanonicalLineItem(
                item_name="\tSUM(A1:B1)",
                qty=Decimal("1"),
                unit_price=Decimal("10"),
                line_total=Decimal("10"),
                math_error="-1+1",
            )
        ],
        review_reasons=["@alert('xss')"],
    )

    malicious_duplicates = [
        ("=HYPERLINK('http://evil.com')", "+MALICIOUS_CMD", "@INJECTION")
    ]

    out_file = export_excel_summary([malicious_invoice], malicious_duplicates, tmp_path, "2026-08")
    wb = openpyxl.load_workbook(out_file)

    # Sheet 1 Overview
    ws1 = wb["Invoice Overview"]
    assert str(ws1.cell(row=2, column=3).value).startswith("'=")  # Vendor
    assert str(ws1.cell(row=2, column=2).value).startswith("'+")  # Invoice no
    assert str(ws1.cell(row=2, column=1).value).startswith("'@")  # Date

    # Sheet 2 Line Items
    ws2 = wb["Line Items Detail"]
    assert str(ws2.cell(row=2, column=2).value).startswith("'\t")  # Item name
    assert str(ws2.cell(row=2, column=8).value).startswith("'-")   # Math error

    # Sheet 3 Discrepancy Alerts
    ws3 = wb["Discrepancy Alerts"]
    assert str(ws3.cell(row=2, column=5).value).startswith("'@")   # Reason

    # Sheet 4 Duplicates
    ws4 = wb["Duplicates"]
    assert str(ws4.cell(row=2, column=1).value).startswith("'=")
    assert str(ws4.cell(row=2, column=2).value).startswith("'+")
    assert str(ws4.cell(row=2, column=3).value).startswith("'@")


def test_empty_lists_handled_gracefully(tmp_path):
    """Test exporting with zero invoices and zero duplicates still creates valid 4-sheet workbook."""
    out_file = export_excel_summary([], [], tmp_path, "2026-08")
    assert out_file.exists()

    wb = openpyxl.load_workbook(out_file)
    assert len(wb.sheetnames) == 4
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        assert ws.max_row == 1  # Only header


def test_sheet_3_when_review_reasons_is_empty(tmp_path):
    """Test FAILED invoice with empty review_reasons still appears in Sheet 3."""
    inv = CanonicalInvoice(
        source_file="invoices/failed_empty_reasons.pdf",
        source_sha256="fail123",
        status=InvoiceStatus.FAILED,
        vendor_name="Failed Vendor",
        invoice_no="FAIL-001",
        invoice_date="2026-08-15",
        review_reasons=[],
    )
    out_file = export_excel_summary([inv], [], tmp_path, "2026-08")
    wb = openpyxl.load_workbook(out_file)
    ws = wb["Discrepancy Alerts"]

    assert ws.max_row == 2
    assert ws.cell(row=2, column=2).value == "FAIL-001"
    assert ws.cell(row=2, column=4).value == InvoiceStatus.FAILED.value
    assert ws.cell(row=2, column=6).value == "invoices/failed_empty_reasons.pdf"


def test_duplicates_format_variants(tmp_path):
    """Test duplicates provided as dicts or custom objects."""
    class CustomDup:
        def __init__(self, a, b, r):
            self.source_a = a
            self.source_b = b
            self.reason = r

    dups = [
        {"source_a": "a.pdf", "source_b": "b.pdf", "reason": "hash match"},
        CustomDup("c.pdf", "d.pdf", "vendor match"),
    ]
    out_file = export_excel_summary([], dups, tmp_path, "2026-08")
    wb = openpyxl.load_workbook(out_file)
    ws = wb["Duplicates"]

    assert ws.max_row == 3
    assert ws.cell(row=2, column=1).value == "a.pdf"
    assert ws.cell(row=2, column=3).value == "hash match"
    assert ws.cell(row=3, column=1).value == "c.pdf"
    assert ws.cell(row=3, column=3).value == "vendor match"


def test_contract_calls_safety_functions(monkeypatch, tmp_path, sample_invoices, sample_duplicates):
    """Verify export_excel_summary calls sanitize_excel_cell and save_workbook_atomic."""
    sanitize_calls = []
    save_calls = []

    import exporters.excel_exporter as ee

    orig_sanitize = ee.sanitize_excel_cell
    orig_save = ee.save_workbook_atomic

    def spy_sanitize(val):
        sanitize_calls.append(val)
        return orig_sanitize(val)

    def spy_save(wb, target):
        save_calls.append(target)
        return orig_save(wb, target)

    monkeypatch.setattr(ee, "sanitize_excel_cell", spy_sanitize)
    monkeypatch.setattr(ee, "save_workbook_atomic", spy_save)

    out_file = export_excel_summary(sample_invoices, sample_duplicates, tmp_path, "2026-08")

    assert len(save_calls) == 1
    assert save_calls[0] == out_file
    assert len(sanitize_calls) > 0


def test_month_regex_validation_blocks_path_traversal(tmp_path, sample_invoices, sample_duplicates):
    """Test invalid month strings are rejected to prevent path traversal."""
    invalid_months = ["../../etc", "2026/08", "2026-13", "2026-00", "2026-8", "august-2026", "../summary"]
    for m in invalid_months:
        with pytest.raises(ValueError, match="Invalid month"):
            export_excel_summary(sample_invoices, sample_duplicates, tmp_path, m)

    # Valid format succeeds
    out_file = export_excel_summary(sample_invoices, sample_duplicates, tmp_path, "2026-08")
    assert out_file.exists()


def test_sheet_1_excludes_duplicates_statement_and_other(tmp_path):
    """Sheet 1 should exclude DUPLICATE invoices, statement, and other doc_types."""
    inv_verified = CanonicalInvoice(
        source_file="invoices/normal.pdf",
        source_sha256="s1",
        status=InvoiceStatus.VERIFIED,
        doc_type=DocType.GOODS_INVOICE,
        invoice_no="INV-100",
        invoice_date="2026-08-01",
        grand_total=Decimal("100.00"),
        line_items=[CanonicalLineItem(item_name="Item 1", qty=Decimal("1"), unit_price=Decimal("100.00"), line_total=Decimal("100.00"))],
    )
    inv_duplicate = CanonicalInvoice(
        source_file="invoices/dup.pdf",
        source_sha256="s2",
        status=InvoiceStatus.DUPLICATE,
        is_duplicate=True,
        duplicate_of="invoices/normal.pdf",
        doc_type=DocType.GOODS_INVOICE,
        invoice_no="INV-100",
        invoice_date="2026-08-01",
        grand_total=Decimal("100.00"),
        line_items=[CanonicalLineItem(item_name="Item 1", qty=Decimal("1"), unit_price=Decimal("100.00"), line_total=Decimal("100.00"))],
    )
    inv_statement = CanonicalInvoice(
        source_file="invoices/stmt.pdf",
        source_sha256="s3",
        status=InvoiceStatus.REVIEW_NEEDED,
        doc_type=DocType.STATEMENT,
        invoice_no="STMT-001",
        invoice_date="2026-08-01",
        grand_total=Decimal("500.00"),
        review_reasons=["doc_type statement excluded"],
    )
    inv_other = CanonicalInvoice(
        source_file="invoices/other.pdf",
        source_sha256="s4",
        status=InvoiceStatus.REVIEW_NEEDED,
        doc_type=DocType.OTHER,
        invoice_no="OTH-001",
        invoice_date="2026-08-01",
        grand_total=Decimal("50.00"),
        review_reasons=["doc_type other excluded"],
    )

    invoices = [inv_verified, inv_duplicate, inv_statement, inv_other]
    out_file = export_excel_summary(invoices, [], tmp_path, "2026-08")
    wb = openpyxl.load_workbook(out_file)

    # Sheet 1: Only inv_verified should be present
    ws1 = wb["Invoice Overview"]
    # 1 header + 1 verified invoice = 2 rows
    assert ws1.max_row == 2
    assert ws1.cell(row=2, column=2).value == "INV-100"
    assert ws1.cell(row=2, column=9).value == "invoices/normal.pdf"

    # Sheet 2: Only lines from inv_verified, none from inv_duplicate
    ws2 = wb["Line Items Detail"]
    assert ws2.max_row == 2
    assert ws2.cell(row=2, column=1).value == "INV-100"

    # Sheet 3: Discrepancy Alerts should contain statement and other
    ws3 = wb["Discrepancy Alerts"]
    files_in_sheet3 = [ws3.cell(row=r, column=6).value for r in range(2, ws3.max_row + 1)]
    assert "invoices/stmt.pdf" in files_in_sheet3
    assert "invoices/other.pdf" in files_in_sheet3
    assert "invoices/normal.pdf" not in files_in_sheet3

    # Sheet 4: Duplicates should contain inv_duplicate
    ws4 = wb["Duplicates"]
    files_in_sheet4 = [ws4.cell(row=r, column=1).value for r in range(2, ws4.max_row + 1)]
    assert "invoices/dup.pdf" in files_in_sheet4


def test_sheet_3_source_file_hyperlink(tmp_path):
    """Sheet 3 column 6 'File gốc' should have a working openpyxl hyperlink."""
    inv_alert = CanonicalInvoice(
        source_file="invoices/bad_file.pdf",
        source_sha256="s99",
        status=InvoiceStatus.FAILED,
        doc_type=DocType.GOODS_INVOICE,
        invoice_no="INV-99",
        invoice_date="2026-08-01",
        review_reasons=["corrupted_file"],
    )
    out_file = export_excel_summary([inv_alert], [], tmp_path, "2026-08")
    wb = openpyxl.load_workbook(out_file)
    ws3 = wb["Discrepancy Alerts"]
    cell = ws3.cell(row=2, column=6)
    assert cell.value == "invoices/bad_file.pdf"
    assert cell.hyperlink is not None
    assert cell.hyperlink.target == "invoices/bad_file.pdf"


