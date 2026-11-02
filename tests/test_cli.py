"""Unit tests for main.py (Invoice Processor CLI).

PLAN 6.4:
- Test argument parsing and help.
- Test --dry-run (prints masked payload to stdout, DO NOT call LLM).
- Test --only (runs only 1 specific file for debugging).
- Test full batch run creates invoices.jsonl, failures.jsonl, Summary_<month>.xlsx.
- Test --no-cache (disables LLMCache).
- Test deduplication handling in batch.
- Test worker exception isolation and error reporting.

INVARIANTS:
1. ZERO real invoice data. All test data is synthetic.
2. ZERO real network calls. Fully mocked LLM and OCR.
3. Vault contents, raw OCR text, and LLM payloads are never leaked.
"""

from decimal import Decimal
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import openpyxl
import pymupdf
import pytest

from config import Category, SCHEMA_VERSION
from core.llm_cache import LLMCache
from core.llm_parser import LLMClient
from core.types import Provenance
from main import find_files, main, parse_args
from models.schema import (
    CanonicalInvoice,
    CanonicalLineItem,
    DocType,
    InvoiceStatus,
    LineItemKind,
    LLMInvoice,
    LLMLineItem,
    LLMSummary,
)


def _create_synthetic_pdf(
    file_path: Path,
    inv_no: str = "INV-2026-001",
    grand_total: str = "55.00",
) -> Path:
    """Create a synthetic PDF invoice with a clean text layer."""
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    text = (
        f"ACME WHOLESALE SUPPLIES INC\n"
        f"Invoice Number: {inv_no}\n"
        f"Invoice Date: 2026-08-15\n"
        f"Payment Due Date: 2026-08-30\n"
        f"Description | Quantity | Unit Price | Total Amount\n"
        f"Widget Alpha Premium Model | 2 | 10.00 | 20.00\n"
        f"Widget Beta Standard Model | 3 | 10.00 | 30.00\n"
        f"Subtotal: 50.00\n"
        f"Tax Amount: 5.00\n"
        f"Grand Total: {grand_total}\n"
        f"Amount Due: {grand_total}\n"
    )
    page.insert_text((50, 80), text, fontsize=11)
    doc.save(file_path)
    doc.close()
    return file_path


def _create_sample_canonical_invoice(
    source_file: str,
    status: InvoiceStatus = InvoiceStatus.VERIFIED,
    invoice_no: str = "INV-2026-001",
    grand_total: str = "55.00",
    sha256: str = "deadbeef1234567890abcdef1234567890abcdef1234567890abcdef12345678",
) -> CanonicalInvoice:
    """Helper creating a synthetic CanonicalInvoice for CLI tests."""
    return CanonicalInvoice(
        source_file=source_file,
        source_sha256=sha256,
        status=status,
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="ACME WHOLESALE SUPPLIES INC",
        invoice_no=invoice_no,
        invoice_date="2026-08-15",
        currency="$",
        category=Category.OTHER,
        line_items=[
            CanonicalLineItem(
                item_name="Widget Alpha Premium Model",
                qty=Decimal("2"),
                unit_price=Decimal("10.00"),
                line_total=Decimal("20.00"),
                unit="EA",
                kind=LineItemKind.GOODS,
                checkable=True,
            )
        ],
        subtotal=Decimal("50.00"),
        tax=Decimal("5.00"),
        grand_total=Decimal(grand_total),
        amount_due=Decimal(grand_total),
        review_reasons=[] if status == InvoiceStatus.VERIFIED else ["synthetic_failure"],
        schema_version=SCHEMA_VERSION,
    )


# =============================================================================
# 1. Test argument parsing and help
# =============================================================================

def test_parse_args_defaults() -> None:
    """Test default CLI options."""
    args = parse_args(["some/invoices/dir"])
    assert args.path == "some/invoices/dir"
    assert args.month == "2026-08"
    assert args.out == "output"
    assert args.only is None
    assert args.workers == 2
    assert args.no_cache is False
    assert args.dry_run is False


def test_parse_args_custom() -> None:
    """Test custom CLI options."""
    argv = [
        "input_folder",
        "--month", "2026-09",
        "--out", "custom_output",
        "--only", "invoice_42.pdf",
        "--workers", "4",
        "--no-cache",
        "--dry-run",
    ]
    args = parse_args(argv)
    assert args.path == "input_folder"
    assert args.month == "2026-09"
    assert args.out == "custom_output"
    assert args.only == "invoice_42.pdf"
    assert args.workers == 4
    assert args.no_cache is True
    assert args.dry_run is True


def test_cli_help(capsys: pytest.CaptureFixture) -> None:
    """Test -h / --help prints usage and exits cleanly."""
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out or "main.py" in captured.out
    assert "--dry-run" in captured.out
    assert "--no-cache" in captured.out


def test_cli_nonexistent_path(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Test main returns 1 when the specified target path does not exist."""
    missing = tmp_path / "does_not_exist"
    ret = main([str(missing)])
    assert ret == 1


def test_cli_only_not_found(tmp_path: Path) -> None:
    """Test main returns 1 when --only points to a non-existent file."""
    valid_folder = tmp_path / "invoices"
    valid_folder.mkdir()
    _create_synthetic_pdf(valid_folder / "inv1.pdf")

    ret = main([str(valid_folder), "--only", "not_there.pdf"])
    assert ret == 1


# =============================================================================
# 2. Test --dry-run (prints masked payload, DO NOT call LLM)
# =============================================================================

def test_dry_run_prints_payload_and_does_not_call_llm(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Test --dry-run prints masked payload to stdout, and halts without LLM calls."""
    invoice_dir = tmp_path / "invoices"
    invoice_dir.mkdir()
    pdf_path = _create_synthetic_pdf(invoice_dir / "sample_dry.pdf")

    mock_llm_client = MagicMock(spec=LLMClient)

    with patch("main.LLMClient", return_value=mock_llm_client):
        ret = main([str(invoice_dir), "--dry-run"])

    assert ret == 0
    # LLM must NEVER be called in dry-run
    mock_llm_client.parse_invoice.assert_not_called()

    captured = capsys.readouterr()
    # Masked tokens should appear in stdout
    assert "<ID_" in captured.out or "<D_" in captured.out or "<N_" in captured.out
    # Raw financial numbers from the PDF (e.g. 50.00, 55.00) must be masked
    assert " 50.00" not in captured.out
    assert " 55.00" not in captured.out

    # Dry-run must NOT create output artifacts
    assert not (tmp_path / "output").exists()


# =============================================================================
# 3. Test --only runs exactly 1 file
# =============================================================================

def test_only_runs_single_file(tmp_path: Path) -> None:
    """Test --only filters execution to only the designated file."""
    invoices_dir = tmp_path / "invoices"
    invoices_dir.mkdir()
    f1 = _create_synthetic_pdf(invoices_dir / "file1.pdf", inv_no="INV-1")
    f2 = _create_synthetic_pdf(invoices_dir / "file2.pdf", inv_no="INV-2")
    f3 = _create_synthetic_pdf(invoices_dir / "file3.pdf", inv_no="INV-3")

    out_dir = tmp_path / "out"

    inv_mock = _create_sample_canonical_invoice(str(f2), invoice_no="INV-2")

    with patch("main.process_invoice_file", return_value=inv_mock) as mock_process:
        ret = main([
            str(invoices_dir),
            "--only", "file2.pdf",
            "--out", str(out_dir),
            "--month", "2026-08",
        ])

    assert ret == 0
    assert mock_process.call_count == 1
    call_kwargs = mock_process.call_args.kwargs
    assert call_kwargs["file_path"].name == "file2.pdf"

    # Verify JSONL contains exactly 1 invoice
    lines = (out_dir / "invoices.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["invoice_no"] == "INV-2"


# =============================================================================
# 4. Test full batch run creates invoices.jsonl, failures.jsonl, Summary_<month>.xlsx
# =============================================================================

def test_batch_full_run_creates_expected_artifacts(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Test batch processing generates invoices.jsonl, failures.jsonl, and Summary_<month>.xlsx."""
    invoices_dir = tmp_path / "invoices"
    invoices_dir.mkdir()
    f1 = _create_synthetic_pdf(invoices_dir / "doc1.pdf", inv_no="INV-001")
    f2 = _create_synthetic_pdf(invoices_dir / "doc2.pdf", inv_no="INV-002")
    f3 = _create_synthetic_pdf(invoices_dir / "corrupted.pdf", inv_no="INV-FAIL")

    out_dir = tmp_path / "output_test"

    inv1 = _create_sample_canonical_invoice(str(f1), status=InvoiceStatus.VERIFIED, invoice_no="INV-001", sha256="sha1")
    inv2 = _create_sample_canonical_invoice(str(f2), status=InvoiceStatus.REVIEW_NEEDED, invoice_no="INV-002", sha256="sha2")
    inv3 = _create_sample_canonical_invoice(str(f3), status=InvoiceStatus.FAILED, invoice_no="INV-FAIL", sha256="sha3")

    def _mock_process_invoice_file(file_path, *args, **kwargs):
        fp_str = str(file_path)
        if "doc1" in fp_str:
            return inv1
        elif "doc2" in fp_str:
            return inv2
        else:
            return inv3

    with patch("main.process_invoice_file", side_effect=_mock_process_invoice_file):
        ret = main([
            str(invoices_dir),
            "--out", str(out_dir),
            "--month", "2026-08",
            "--workers", "2",
        ])

    assert ret == 0

    # 1. invoices.jsonl
    invoices_jsonl = out_dir / "invoices.jsonl"
    assert invoices_jsonl.is_file()
    lines = invoices_jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3

    # 2. failures.jsonl
    failures_jsonl = out_dir / "failures.jsonl"
    assert failures_jsonl.is_file()
    fail_lines = failures_jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(fail_lines) == 1
    fail_data = json.loads(fail_lines[0])
    assert "corrupted.pdf" in fail_data["file_path"]

    # 3. Excel Summary
    excel_path = out_dir / "Summary_2026-08.xlsx"
    assert excel_path.is_file()
    wb = openpyxl.load_workbook(excel_path)
    sheet_names = wb.sheetnames
    assert "Invoice Overview" in sheet_names
    assert "Line Items Detail" in sheet_names
    assert "Discrepancy Alerts" in sheet_names
    assert "Duplicates" in sheet_names
    wb.close()

    # 4. Summary table in stdout
    captured = capsys.readouterr()
    assert "BẢNG TỔNG KẾT XỬ LÝ HÓA ĐƠN" in captured.out
    assert "Tổng số file:       3" in captured.out
    assert "Số VERIFIED:        1" in captured.out
    assert "Số REVIEW_NEEDED:   1" in captured.out
    assert "Số FAILED:          1" in captured.out
    assert "Số DUPLICATE:       0" in captured.out
    assert "Thời gian chạy:" in captured.out


# =============================================================================
# 5. Test --no-cache
# =============================================================================

def test_no_cache_flag_disabled(tmp_path: Path) -> None:
    """Test --no-cache passes cache=None to process_invoice_file."""
    invoices_dir = tmp_path / "invoices"
    invoices_dir.mkdir()
    f1 = _create_synthetic_pdf(invoices_dir / "inv.pdf")

    inv = _create_sample_canonical_invoice(str(f1))

    with patch("main.process_invoice_file", return_value=inv) as mock_proc:
        ret = main([str(invoices_dir), "--out", str(tmp_path / "out"), "--no-cache"])

    assert ret == 0
    call_kwargs = mock_proc.call_args.kwargs
    assert call_kwargs["cache"] is None


def test_cache_enabled_by_default(tmp_path: Path) -> None:
    """Test without --no-cache, an LLMCache instance is passed."""
    invoices_dir = tmp_path / "invoices"
    invoices_dir.mkdir()
    f1 = _create_synthetic_pdf(invoices_dir / "inv.pdf")

    inv = _create_sample_canonical_invoice(str(f1))

    with patch("main.process_invoice_file", return_value=inv) as mock_proc:
        ret = main([str(invoices_dir), "--out", str(tmp_path / "out")])

    assert ret == 0
    call_kwargs = mock_proc.call_args.kwargs
    assert isinstance(call_kwargs["cache"], LLMCache)


# =============================================================================
# 6. Test deduplication handling in batch
# =============================================================================

def test_batch_deduplication(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Test duplicate invoices in batch are detected and counted in summary."""
    invoices_dir = tmp_path / "invoices"
    invoices_dir.mkdir()
    f1 = _create_synthetic_pdf(invoices_dir / "inv1.pdf")
    f2 = _create_synthetic_pdf(invoices_dir / "inv2.pdf")

    # Identical SHA256 indicates duplicate
    inv1 = _create_sample_canonical_invoice(str(f1), sha256="same_sha_value", invoice_no="INV-100")
    inv2 = _create_sample_canonical_invoice(str(f2), sha256="same_sha_value", invoice_no="INV-100")

    def _mock_proc(file_path, *args, **kwargs):
        return inv1 if "inv1" in str(file_path) else inv2

    out_dir = tmp_path / "out_dedup"
    with patch("main.process_invoice_file", side_effect=_mock_proc):
        ret = main([str(invoices_dir), "--out", str(out_dir), "--month", "2026-08"])

    assert ret == 0

    captured = capsys.readouterr()
    assert "Số VERIFIED:        1" in captured.out
    assert "Số DUPLICATE:       1" in captured.out

    # Excel should have duplicate recorded in Sheet 4
    wb = openpyxl.load_workbook(out_dir / "Summary_2026-08.xlsx")
    ws_dup = wb["Duplicates"]
    assert ws_dup.max_row >= 2
    wb.close()


# =============================================================================
# 7. Test worker exception handling
# =============================================================================

def test_worker_exception_isolated(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Test unexpected worker exception is captured as FAILED without crashing batch."""
    invoices_dir = tmp_path / "invoices"
    invoices_dir.mkdir()
    f1 = _create_synthetic_pdf(invoices_dir / "inv1.pdf")

    out_dir = tmp_path / "out_crash"

    with patch("main.process_invoice_file", side_effect=RuntimeError("Worker crash!")):
        ret = main([str(invoices_dir), "--out", str(out_dir)])

    assert ret == 0
    captured = capsys.readouterr()
    assert "Số FAILED:          1" in captured.out

    # invoices.jsonl should record worker_error
    lines = (out_dir / "invoices.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["status"] == "FAILED"
    assert "worker_error" in data["review_reasons"]


# =============================================================================
# 8. Test empty folder handling
# =============================================================================

def test_empty_folder_handling(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Test passing an empty folder finishes with 0 files processed."""
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()

    ret = main([str(empty_dir)])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Tổng số file:       0" in captured.out
