"""Unit tests for JSONL streaming exporter (PLAN 6.1).

INVARIANTS:
1. Tests must NEVER access real invoice files.
2. Only synthetic in-memory test data is used.
"""

from decimal import Decimal
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from config import Category, SCHEMA_VERSION
from core.types import Provenance
from exporters.jsonl_exporter import JSONLExporter
from models.schema import (
    CanonicalInvoice,
    CanonicalLineItem,
    CanonicalCharge,
    DocType,
    InvoiceStatus,
    LineItemKind,
)


def _make_sample_invoice(
    source_file: str = "synthetic_inv_001.pdf",
    source_sha256: str = "deadbeef00112233445566778899aabbccddeeff00112233445566778899aabb",
    invoice_no: str = "INV-2026-001",
    grand_total: str = "1234.56",
) -> CanonicalInvoice:
    """Helper creating a synthetic CanonicalInvoice for tests (no real files used)."""
    return CanonicalInvoice(
        source_file=source_file,
        source_sha256=source_sha256,
        status=InvoiceStatus.VERIFIED,
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="Acme Supplies Co.",
        invoice_no=invoice_no,
        invoice_no_prov=Provenance(page=1, bbox=(10.0, 20.0, 100.0, 30.0), ocr_conf=1.0, source="pdf_text"),
        invoice_date="2026-08-15",
        invoice_date_prov=Provenance(page=1, bbox=(10.0, 35.0, 80.0, 45.0), ocr_conf=1.0, source="pdf_text"),
        due_date="2026-09-15",
        currency="USD",
        category=Category.FOOD_INGREDIENTS,
        line_items=[
            CanonicalLineItem(
                item_name="Widget A",
                qty=Decimal("10.5"),
                qty_prov=Provenance(page=1, bbox=(50.0, 100.0, 70.0, 110.0), ocr_conf=0.98, source="ocr"),
                unit_price=Decimal("100.00"),
                unit_price_prov=Provenance(page=1, bbox=(80.0, 100.0, 110.0, 110.0), ocr_conf=0.98, source="ocr"),
                line_total=Decimal("1050.00"),
                line_total_prov=Provenance(page=1, bbox=(120.0, 100.0, 160.0, 110.0), ocr_conf=0.98, source="ocr"),
                unit="kg",
                kind=LineItemKind.GOODS,
                checkable=True,
            ),
            CanonicalLineItem(
                item_name="Handling Discount",
                qty=Decimal("1"),
                unit_price=Decimal("-50.00"),
                line_total=Decimal("-50.00"),
                kind=LineItemKind.DISCOUNT,
                checkable=True,
            ),
        ],
        charges=[
            CanonicalCharge(
                description="Delivery surcharge",
                amount=Decimal("25.00"),
                amount_prov=Provenance(page=1, bbox=(120.0, 200.0, 160.0, 210.0), ocr_conf=0.95, source="ocr"),
            )
        ],
        subtotal=Decimal("1000.00"),
        subtotal_prov=Provenance(page=1, bbox=(120.0, 220.0, 160.0, 230.0), ocr_conf=0.99, source="pdf_text"),
        tax=Decimal("100.00"),
        tax_prov=Provenance(page=1, bbox=(120.0, 240.0, 160.0, 250.0), ocr_conf=0.99, source="pdf_text"),
        discount=Decimal("50.00"),
        shipping=Decimal("10.00"),
        tip=Decimal("0.00"),
        fees=[Decimal("15.00"), Decimal("10.00")],
        grand_total=Decimal(grand_total),
        grand_total_prov=Provenance(page=1, bbox=(120.0, 260.0, 160.0, 270.0), ocr_conf=1.0, source="pdf_text"),
        amount_due=Decimal(grand_total),
        review_reasons=[],
        schema_version=SCHEMA_VERSION,
        is_duplicate=False,
    )


def test_write_single_invoice(tmp_path: Path) -> None:
    """Verify writing a single invoice produces a valid JSON line with matching fields."""
    out_file = tmp_path / "invoices.jsonl"
    exporter = JSONLExporter(out_file)

    invoice = _make_sample_invoice()
    exporter.write_invoice(invoice)

    assert out_file.exists()
    lines = out_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    data = json.loads(lines[0])
    assert data["source_file"] == invoice.source_file
    assert data["source_sha256"] == invoice.source_sha256
    assert data["vendor_name"] == "Acme Supplies Co."
    assert data["invoice_no"] == "INV-2026-001"
    assert data["status"] == "VERIFIED"
    assert data["doc_type"] == "goods_invoice"
    assert len(data["line_items"]) == 2
    assert len(data["charges"]) == 1


def test_write_multiple_invoices_streaming(tmp_path: Path) -> None:
    """Verify multiple invoices are streamed line-by-line in sequential order."""
    out_file = tmp_path / "invoices.jsonl"
    exporter = JSONLExporter(out_file)

    invoices = [
        _make_sample_invoice(invoice_no=f"INV-00{i}", grand_total=f"{100 * i}.50")
        for i in range(1, 4)
    ]

    for inv in invoices:
        exporter.write_invoice(inv)

    lines = out_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3

    for i, line in enumerate(lines, start=1):
        parsed = json.loads(line)
        assert parsed["invoice_no"] == f"INV-00{i}"
        assert parsed["grand_total"] == f"{100 * i}.50"


def test_decimal_serialized_as_strings(tmp_path: Path) -> None:
    """Verify all Decimal fields are serialized strictly as strings to preserve precision."""
    out_file = tmp_path / "invoices.jsonl"
    exporter = JSONLExporter(out_file)

    invoice = _make_sample_invoice(grand_total="999999999999.85")
    exporter.write_invoice(invoice)

    raw_content = out_file.read_text(encoding="utf-8").strip()
    data = json.loads(raw_content)

    # Decimal fields must be of type str in JSON dict
    assert isinstance(data["grand_total"], str)
    assert data["grand_total"] == "999999999999.85"

    assert isinstance(data["subtotal"], str)
    assert data["subtotal"] == "1000.00"

    assert isinstance(data["tax"], str)
    assert data["tax"] == "100.00"

    assert isinstance(data["discount"], str)
    assert data["discount"] == "50.00"

    assert isinstance(data["shipping"], str)
    assert data["shipping"] == "10.00"

    assert isinstance(data["tip"], str)
    assert data["tip"] == "0.00"

    # Line item decimals
    line_0 = data["line_items"][0]
    assert isinstance(line_0["qty"], str)
    assert line_0["qty"] == "10.5"
    assert isinstance(line_0["unit_price"], str)
    assert line_0["unit_price"] == "100.00"
    assert isinstance(line_0["line_total"], str)
    assert line_0["line_total"] == "1050.00"

    line_1 = data["line_items"][1]
    assert isinstance(line_1["qty"], str)
    assert line_1["qty"] == "1"
    assert isinstance(line_1["unit_price"], str)
    assert line_1["unit_price"] == "-50.00"
    assert isinstance(line_1["line_total"], str)
    assert line_1["line_total"] == "-50.00"

    # Charge amount
    assert isinstance(data["charges"][0]["amount"], str)
    assert data["charges"][0]["amount"] == "25.00"

    # Fees list
    assert all(isinstance(f, str) for f in data["fees"])
    assert data["fees"] == ["15.00", "10.00"]

    # Verify directly in raw json string that quotes surround numeric strings
    assert '"grand_total": "999999999999.85"' in raw_content
    assert '"qty": "10.5"' in raw_content
    assert '"unit_price": "-50.00"' in raw_content


def test_immediate_flush_behavior(tmp_path: Path) -> None:
    """Verify flush is explicitly called immediately on each invoice and failure write."""
    import builtins
    out_file = tmp_path / "invoices.jsonl"
    exporter = JSONLExporter(out_file)

    orig_open = builtins.open
    flush_calls = []

    class FileSpy:
        def __init__(self, f):
            self._f = f

        def flush(self):
            flush_calls.append("flush")
            return self._f.flush()

        def __enter__(self):
            self._f.__enter__()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return self._f.__exit__(exc_type, exc_val, exc_tb)

        def __getattr__(self, name):
            return getattr(self._f, name)

    def spy_open(*args, **kwargs):
        f = orig_open(*args, **kwargs)
        return FileSpy(f)

    with patch("builtins.open", side_effect=spy_open):
        exporter.write_invoice(_make_sample_invoice())
        assert len(flush_calls) >= 1

        flush_count_after_inv = len(flush_calls)
        exporter.write_failure("bad_file.pdf", "UNREADABLE_FILE")
        assert len(flush_calls) > flush_count_after_inv


def test_append_mode_preserves_old_records(tmp_path: Path) -> None:
    """Verify reopening/creating another exporter appends rather than overwriting."""
    out_file = tmp_path / "invoices.jsonl"

    # Run 1
    exp1 = JSONLExporter(out_file)
    exp1.write_invoice(_make_sample_invoice(invoice_no="INV-A"))

    # Run 2 (e.g. simulated resume after crash/restart)
    exp2 = JSONLExporter(out_file)
    exp2.write_invoice(_make_sample_invoice(invoice_no="INV-B"))

    lines = out_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    parsed_numbers = [json.loads(line)["invoice_no"] for line in lines]
    assert parsed_numbers == ["INV-A", "INV-B"]


def test_write_failure_default_path(tmp_path: Path) -> None:
    """Verify failure logs write to output_dir/failures.jsonl with only file_path and error_code."""
    out_file = tmp_path / "output" / "invoices.jsonl"
    exporter = JSONLExporter(out_file)

    exporter.write_failure("synthetic_corrupt.pdf", "CORRUPTED_PDF_HEADER")
    exporter.write_failure("synthetic_empty.png", "EMPTY_FILE")

    expected_failure_file = tmp_path / "output" / "failures.jsonl"
    assert expected_failure_file.exists()

    lines = expected_failure_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    entry1 = json.loads(lines[0])
    assert entry1 == {
        "file_path": "synthetic_corrupt.pdf",
        "error_code": "CORRUPTED_PDF_HEADER",
    }
    # Invariant: failures.jsonl must never contain extracted text, tokens, or raw payload
    assert set(entry1.keys()) == {"file_path", "error_code"}

    entry2 = json.loads(lines[1])
    assert entry2 == {
        "file_path": "synthetic_empty.png",
        "error_code": "EMPTY_FILE",
    }


def test_write_failure_custom_path(tmp_path: Path) -> None:
    """Verify custom failure file path is respected."""
    out_file = tmp_path / "invoices.jsonl"
    custom_fail = tmp_path / "custom_logs" / "custom_fail.jsonl"

    exporter = JSONLExporter(out_file, failure_file=custom_fail)
    exporter.write_failure("failed_doc.pdf", "LEAK_GUARD_REJECTED")

    assert custom_fail.exists()
    assert not (tmp_path / "failures.jsonl").exists()

    entry = json.loads(custom_fail.read_text(encoding="utf-8").strip())
    assert entry == {
        "file_path": "failed_doc.pdf",
        "error_code": "LEAK_GUARD_REJECTED",
    }


def test_provenance_and_metadata_preserved(tmp_path: Path) -> None:
    """Verify Provenance and schema version are retained accurately in JSONL dict."""
    out_file = tmp_path / "invoices.jsonl"
    exporter = JSONLExporter(out_file)

    invoice = _make_sample_invoice()
    exporter.write_invoice(invoice)

    line = out_file.read_text(encoding="utf-8").strip()
    data = json.loads(line)

    assert data["schema_version"] == SCHEMA_VERSION
    assert "invoice_no_prov" in data
    assert data["invoice_no_prov"]["page"] == 1
    assert data["invoice_no_prov"]["bbox"] == [10.0, 20.0, 100.0, 30.0]
    assert data["invoice_no_prov"]["source"] == "pdf_text"
    assert data["invoice_no_prov"]["ocr_conf"] == 1.0


def test_directory_creation_and_context_manager(tmp_path: Path) -> None:
    """Verify deep directory creation and context manager support."""
    deep_out = tmp_path / "a" / "b" / "c" / "invoices.jsonl"
    deep_fail = tmp_path / "x" / "y" / "z" / "failures.jsonl"

    with JSONLExporter(deep_out, failure_file=deep_fail) as exporter:
        exporter.write_invoice(_make_sample_invoice())
        exporter.write_failure("mock.pdf", "ERR_TEST")

    assert deep_out.exists()
    assert deep_fail.exists()


def test_string_paths_and_unicode_handling(tmp_path: Path) -> None:
    """Verify string arguments for paths and non-ASCII UTF-8 characters are handled properly."""
    str_out = str(tmp_path / "unicode_output" / "invoices.jsonl")
    str_fail = str(tmp_path / "unicode_output" / "custom_failures.jsonl")

    exporter = JSONLExporter(str_out, failure_file=str_fail)

    inv = _make_sample_invoice(
        invoice_no="HĐ-2026/08-0099",
        grand_total="500000.00",
    )
    inv.vendor_name = "Công ty TNHH Thực Phẩm Tươi Sống Sài Gòn"
    inv.line_items = [
        CanonicalLineItem(
            item_name="Cà phê Robusta Đắk Lắk (Loại 1)",
            qty=Decimal("5.25"),
            unit_price=Decimal("95000.00"),
            line_total=Decimal("498750.00"),
            unit="KG",
        )
    ]

    exporter.write_invoice(inv)
    exporter.write_failure("lỗi_hóa_đơn_01.pdf", "ENCODING_ERROR")

    # Verify invoice UTF-8 preservation
    out_lines = Path(str_out).read_text(encoding="utf-8").strip().splitlines()
    assert len(out_lines) == 1
    data = json.loads(out_lines[0])
    assert data["vendor_name"] == "Công ty TNHH Thực Phẩm Tươi Sống Sài Gòn"
    assert data["line_items"][0]["item_name"] == "Cà phê Robusta Đắk Lắk (Loại 1)"
    assert data["line_items"][0]["qty"] == "5.25"

    # Verify failure UTF-8 preservation
    fail_lines = Path(str_fail).read_text(encoding="utf-8").strip().splitlines()
    assert len(fail_lines) == 1
    fail_data = json.loads(fail_lines[0])
    assert fail_data["file_path"] == "lỗi_hóa_đơn_01.pdf"
    assert fail_data["error_code"] == "ENCODING_ERROR"


def test_rewrite_invoices_atomic_success(tmp_path: Path) -> None:
    """Verify rewrite_invoices_atomic correctly rewrites JSONL file atomically."""
    from exporters.jsonl_exporter import rewrite_invoices_atomic

    out_file = tmp_path / "invoices.jsonl"
    out_file.write_text("old_content\n", encoding="utf-8")

    inv1 = _make_sample_invoice(invoice_no="INV-1", grand_total="100.00")
    inv2 = _make_sample_invoice(invoice_no="INV-2", grand_total="200.00")

    rewrite_invoices_atomic(out_file, [inv1, inv2])

    lines = out_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    d1 = json.loads(lines[0])
    d2 = json.loads(lines[1])
    assert d1["invoice_no"] == "INV-1"
    assert d2["invoice_no"] == "INV-2"


def test_rewrite_invoices_atomic_failure_preserves_target(tmp_path: Path) -> None:
    """Verify rewrite_invoices_atomic failure does not corrupt original file."""
    from exporters.jsonl_exporter import rewrite_invoices_atomic

    out_file = tmp_path / "invoices.jsonl"
    out_file.write_text("precious_original_content\n", encoding="utf-8")

    class CrashingInvoice:
        def to_jsonl_dict(self):
            raise RuntimeError("Boom mid-write")

    with pytest.raises(RuntimeError, match="Boom mid-write"):
        rewrite_invoices_atomic(out_file, [CrashingInvoice()])

    # Original content must be untouched
    assert out_file.read_text(encoding="utf-8") == "precious_original_content\n"

    # No leftover temporary files
    assert list(tmp_path.glob("*.tmp")) == []


