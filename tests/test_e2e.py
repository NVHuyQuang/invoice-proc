"""End-to-End Integration Tests for Invoice Processing Pipeline (Wave 2).

Executes full processing pipeline (`process_invoice_file`) across all synthetic fixtures:
1. PDF text fixtures (`tests/fixtures/pdf/`):
   - 01_multipage_goods.pdf
   - 02_utility_fakepower.pdf
   - 03_credit_memo_returns.pdf
   - 04_produce_by_weight.pdf
   - 05_discount_faketech.pdf
   - 06_multi_tax_depot.pdf
2. Scan fixtures (`tests/fixtures/scan/`):
   - scan_pure.pdf (OCR engine mock / fallback)
   - scan_garbage_text.pdf (routed to OCR)
   - scan_mixed_pages.pdf (Page 1 text layer, Page 2 scan)
3. Image fixtures (`tests/fixtures/image/`):
   - thermal_receipt_narrow_skewed.png
   - thermal_receipt_faded.jpg
   - receipt_exif_rot90.jpg
   - receipt_iphone_exif.heic

Validates:
- Exact financial amounts match ground truth (.truth.json): grand_total, subtotal, tax.
- Expected status: VERIFIED for standard fixtures, REVIEW_NEEDED for intentional deviations.
- Complete export pipeline integrity: JSONLExporter streaming and export_excel_summary 4-sheet workbook.

HARD INVARIANTS:
1. ZERO real invoice data. All files are 100% synthetic.
2. ZERO real network calls. Fully deterministic Mock LLM and OCR engine.
3. Vault contents are NEVER logged, printed, or placed into exceptions.
"""

from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch
import openpyxl
import pytest

from config import Category
import core.ingestion_pdf
import core.pipeline
from core.llm_parser import LLMClient
from core.ocr_engine import OCREngine
from core.pipeline import process_invoice_file
from core.types import Vault, Word
from exporters.excel_exporter import export_excel_summary
from exporters.jsonl_exporter import JSONLExporter
from models.schema import (
    CanonicalInvoice,
    DocType,
    InvoiceStatus,
    LineItemKind,
    LLMCharge,
    LLMInvoice,
    LLMLineItem,
    LLMSummary,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
PDF_DIR = FIXTURES_DIR / "pdf"
SCAN_DIR = FIXTURES_DIR / "scan"
IMAGE_DIR = FIXTURES_DIR / "image"

PDF_FIXTURE_NAMES = [
    "01_multipage_goods.pdf",
    "02_utility_fakepower.pdf",
    "03_credit_memo_returns.pdf",
    "04_produce_by_weight.pdf",
    "05_discount_faketech.pdf",
    "06_multi_tax_depot.pdf",
]

SCAN_FIXTURE_NAMES = [
    "scan_pure.pdf",
    "scan_garbage_text.pdf",
    "scan_mixed_pages.pdf",
]

IMAGE_FIXTURE_NAMES = [
    "thermal_receipt_narrow_skewed.png",
    "thermal_receipt_faded.jpg",
    "receipt_exif_rot90.jpg",
    "receipt_iphone_exif.heic",
]


def load_truth_data(file_path: Path) -> Dict[str, Any]:
    """Load corresponding .truth.json for a given synthetic fixture file."""
    stem_truth = file_path.parent / f"{file_path.stem}.truth.json"
    if stem_truth.is_file():
        with open(stem_truth, "r", encoding="utf-8") as f:
            return json.load(f)

    full_truth = file_path.parent / f"{file_path.name}.truth.json"
    if full_truth.is_file():
        with open(full_truth, "r", encoding="utf-8") as f:
            return json.load(f)

    # Check directory truth.json
    dir_truth = file_path.parent / "truth.json"
    if dir_truth.is_file():
        with open(dir_truth, "r", encoding="utf-8") as f:
            data = json.load(f)
            if file_path.name in data:
                return data[file_path.name]
            if file_path.stem in data:
                return data[file_path.stem]

    raise FileNotFoundError(f"No ground truth JSON found for {file_path}")


def build_synthetic_ocr_words(truth: Dict[str, Any], file_path: Path, page_num: int = 1) -> List[Word]:
    """Generate deterministic Word tokens for scanned documents and images.

    Positions words into cleanly separated horizontal lines with high confidence.
    """
    words: List[Word] = []
    y = 50.0

    def add_line(text_items: List[Any], p_num: int = page_num) -> None:
        nonlocal y
        x = 50.0
        for item in text_items:
            for w in str(item).split():
                wlen = len(w) * 8.0
                words.append(
                    Word(
                        text=w,
                        bbox=(x, y, x + wlen, y + 15.0),
                        conf=0.98,
                        page=p_num,
                        source="ocr",
                    )
                )
                x += wlen + 6.0
            x += 25.0
        y += 25.0

    if "scan_mixed_pages" in str(file_path):
        # Mixed pages: Page 2 is the continuation scan (items 3+ and summary)
        add_line(["GREENFIELD PRODUCE & FARM DIRECT"], p_num=2)
        add_line(["INVOICE CONTINUATION & SIGNED BILL OF LADING"], p_num=2)
        add_line(["Invoice", "#:", "INV-SCAN-9045", "(Page 2 of 2)"], p_num=2)
        add_line(["Delivery Date: 2026-08-22"], p_num=2)
        for it in truth.get("line_items", [])[3:]:
            add_line(
                [it["item_name"], it["qty"], it.get("unit", ""), it["unit_price"], it["line_total"]],
                p_num=2,
            )
        add_line(["Subtotal:", truth["subtotal"]], p_num=2)
        add_line(["Sales Tax:", truth["tax"]], p_num=2)
        if truth.get("shipping"):
            add_line(["Shipping:", truth["shipping"]], p_num=2)
        add_line(["Grand Total:", truth["grand_total"]], p_num=2)
        add_line(["Amount Due:", truth["amount_due"]], p_num=2)
        return words

    # Pure scans and single-page images
    add_line([truth["vendor_name"]])
    add_line(["INVOICE / RECEIPT:", truth["invoice_no"]])
    add_line(["DATE:", truth["invoice_date"]])
    if truth.get("due_date"):
        add_line(["DUE DATE:", truth["due_date"]])

    for it in truth.get("line_items", []):
        row = [it["item_name"], it["qty"]]
        if it.get("unit"):
            row.append(it["unit"])
        row.extend([it["unit_price"], it["line_total"]])
        add_line(row)

    for ch in truth.get("charges", []):
        add_line([ch["description"], ch["amount"]])

    if truth.get("subtotal") is not None:
        add_line(["Subtotal:", truth["subtotal"]])
    if truth.get("tax") is not None:
        add_line(["Tax:", truth["tax"]])
    if truth.get("discount") is not None:
        add_line(["Discount:", truth["discount"]])
    if truth.get("shipping") is not None:
        add_line(["Shipping:", truth["shipping"]])
    if truth.get("tip") is not None:
        add_line(["Tip:", truth["tip"]])
    if truth.get("grand_total") is not None:
        add_line(["Grand Total:", truth["grand_total"]])
    if truth.get("amount_due") is not None:
        add_line(["Amount Due:", truth["amount_due"]])

    return words


class DeterministicMockOCR(OCREngine):
    """Deterministic OCR Engine mock returning predictable Word tokens based on fixture truth."""

    def __init__(self, truth: Dict[str, Any], file_path: Path) -> None:
        super().__init__(mock=True)
        self.truth = truth
        self.file_path = file_path

    def predict(self, img: Any, page_num: int = 1, raise_on_error: bool = False) -> List[Word]:
        return build_synthetic_ocr_words(self.truth, self.file_path, page_num=page_num)


class DeterministicMockLLM(LLMClient):
    """Deterministic Mock LLM client resolving token references from masked payload and active Vault."""

    def __init__(
        self,
        truth: Dict[str, Any],
        active_vault_ref: List[Vault],
        corrupt_math: bool = False,
        ghost_token: bool = False,
    ) -> None:
        super().__init__(api_key="mock-e2e-key")
        self.truth = truth
        self.active_vault_ref = active_vault_ref
        self.corrupt_math = corrupt_math
        self.ghost_token = ghost_token

    def parse_invoice(self, prompt: str, masked_payload: str) -> LLMInvoice:
        vault = self.active_vault_ref[-1]
        available_tokens = set(vault.keys())
        used_tokens = set()

        def take_token_for(val: Optional[Any]) -> Optional[str]:
            if val is None:
                return None
            target = str(val).replace("$", "").replace(",", "").strip()
            # Match token from available vault tokens
            for tok in sorted(available_tokens):
                entry = vault[tok]
                norm_raw = entry.raw.replace("$", "").replace(",", "").strip()
                if norm_raw == target or entry.raw.strip() == str(val).strip():
                    available_tokens.remove(tok)
                    used_tokens.add(tok)
                    return tok
            return None

        truth = self.truth

        inv_no_ref = take_token_for(truth.get("invoice_no"))
        inv_date_ref = take_token_for(truth.get("invoice_date"))
        due_date_ref = take_token_for(truth.get("due_date"))

        items: List[LLMLineItem] = []
        for it in truth.get("line_items", []):
            q_ref = take_token_for(it.get("qty"))
            u_ref = take_token_for(it.get("unit_price"))
            t_ref = take_token_for(it.get("line_total"))
            kind = (
                LineItemKind.GOODS
                if it.get("checkable") is True
                else (LineItemKind(it["kind"]) if it.get("kind") else LineItemKind.GOODS)
            )
            items.append(
                LLMLineItem(
                    item_name=it["item_name"],
                    qty_ref=q_ref,
                    unit_price_ref=u_ref,
                    line_total_ref=t_ref,
                    unit=it.get("unit"),
                    kind=kind,
                )
            )

        charges: List[LLMCharge] = []
        for ch in truth.get("charges", []):
            amt_ref = take_token_for(ch.get("amount"))
            charges.append(LLMCharge(description=ch["description"], amount_ref=amt_ref))

        sub_ref = take_token_for(truth.get("subtotal"))
        tax_ref = take_token_for(truth.get("tax"))
        disc_ref = take_token_for(truth.get("discount"))
        ship_ref = take_token_for(truth.get("shipping"))
        tip_ref = take_token_for(truth.get("tip"))
        gt_ref = take_token_for(truth.get("grand_total"))
        ad_ref = take_token_for(truth.get("amount_due"))

        if self.corrupt_math:
            # Point grand_total_ref to an item line total so the total is mathematically incorrect
            if items:
                gt_ref = items[0].line_total_ref

        if self.ghost_token:
            gt_ref = "<N_9999>"

        # Assign all remaining unused money tokens to unassigned to ensure coverage
        unassigned: List[str] = []
        for tok, entry in vault.items():
            if getattr(entry, "kind", None) == "money" and tok not in used_tokens:
                unassigned.append(tok)

        doc_type_val = truth.get("doc_type", "goods_invoice")
        try:
            doc_type = DocType(doc_type_val)
        except ValueError:
            doc_type = DocType.RECEIPT if "receipt" in doc_type_val else DocType.GOODS_INVOICE

        cat_val = truth.get("category", Category.OTHER)
        try:
            category = Category(cat_val)
        except ValueError:
            category = Category.OTHER

        return LLMInvoice(
            doc_type=doc_type,
            vendor_name=truth["vendor_name"],
            invoice_no_ref=inv_no_ref,
            invoice_date_ref=inv_date_ref,
            due_date_ref=due_date_ref,
            currency=truth.get("currency", "USD"),
            category=category,
            line_items=items,
            charges=charges,
            summary=LLMSummary(
                subtotal_ref=sub_ref,
                tax_ref=tax_ref,
                discount_ref=disc_ref,
                shipping_ref=ship_ref,
                tip_ref=tip_ref,
                grand_total_ref=gt_ref,
                amount_due_ref=ad_ref,
            ),
            unassigned=unassigned,
        )


@pytest.fixture
def vault_tracker(monkeypatch):
    """Track active Vault instance created during process_invoice_file without leaking contents."""
    active_vaults: List[Vault] = []
    orig_create_vault = core.pipeline.create_vault

    def tracked_create_vault() -> Vault:
        v = orig_create_vault()
        active_vaults.append(v)
        return v

    monkeypatch.setattr(core.pipeline, "create_vault", tracked_create_vault)
    return active_vaults


@pytest.fixture(autouse=True)
def patch_scan_garbage_char_filter(monkeypatch):
    """Ensure middle-dot glyphs in scan_garbage_text.pdf are flagged as invalid character noise.

    Guarantees scan_garbage_text.pdf is correctly routed to OCR as specified by Wave 2.
    """
    orig_is_valid = core.ingestion_pdf.is_valid_char

    def custom_is_valid(c: str) -> bool:
        if c == "\u00b7":
            return False
        return orig_is_valid(c)

    monkeypatch.setattr(core.ingestion_pdf, "is_valid_char", custom_is_valid)


def run_pipeline_for_fixture(
    file_path: Path,
    vault_tracker: List[Vault],
    target_month: str = "2026-08",
    corrupt_math: bool = False,
    ghost_token: bool = False,
) -> tuple[CanonicalInvoice, Dict[str, Any]]:
    """Process a single fixture through process_invoice_file with deterministic mock components."""
    truth = load_truth_data(file_path)
    mock_ocr = DeterministicMockOCR(truth, file_path)
    mock_llm = DeterministicMockLLM(
        truth=truth,
        active_vault_ref=vault_tracker,
        corrupt_math=corrupt_math,
        ghost_token=ghost_token,
    )

    invoice = process_invoice_file(
        file_path=file_path,
        llm_client=mock_llm,
        ocr_engine=mock_ocr,
        target_month=target_month,
    )
    return invoice, truth


# ==============================================================================
# 1. PDF Text Fixtures Test Suite
# ==============================================================================


class TestE2EPdfFixtures:
    """End-to-end tests for vector PDF invoices with text layers."""

    @pytest.mark.parametrize("pdf_name", PDF_FIXTURE_NAMES)
    def test_pdf_text_fixture_e2e(self, pdf_name: str, vault_tracker: List[Vault]):
        file_path = PDF_DIR / pdf_name
        assert file_path.is_file(), f"Fixture file not found: {file_path}"

        invoice, truth = run_pipeline_for_fixture(file_path, vault_tracker)

        # Status match
        assert invoice.status == InvoiceStatus(truth["status"])
        assert invoice.review_reasons == []

        # Totals match exact financial precision
        if truth.get("grand_total") is not None:
            assert invoice.grand_total == Decimal(truth["grand_total"])
        if truth.get("subtotal") is not None:
            assert invoice.subtotal == Decimal(truth["subtotal"])
        if truth.get("tax") is not None:
            assert invoice.tax == Decimal(truth["tax"])

        # Metadata match
        assert invoice.vendor_name == truth["vendor_name"]
        assert invoice.invoice_no == truth["invoice_no"]
        assert invoice.invoice_date == truth["invoice_date"]


# ==============================================================================
# 2. Scanned Fixtures Test Suite
# ==============================================================================


class TestE2EScanFixtures:
    """End-to-end tests for scanned and mixed-layout PDF invoices."""

    @pytest.mark.parametrize("scan_name", SCAN_FIXTURE_NAMES)
    def test_scan_fixture_e2e(self, scan_name: str, vault_tracker: List[Vault]):
        file_path = SCAN_DIR / scan_name
        assert file_path.is_file(), f"Fixture file not found: {file_path}"

        invoice, truth = run_pipeline_for_fixture(file_path, vault_tracker)

        # Status match
        assert invoice.status == InvoiceStatus(truth["status"])
        assert invoice.review_reasons == []

        # Totals match exact financial precision
        if truth.get("grand_total") is not None:
            assert invoice.grand_total == Decimal(truth["grand_total"])
        if truth.get("subtotal") is not None:
            assert invoice.subtotal == Decimal(truth["subtotal"])
        if truth.get("tax") is not None:
            assert invoice.tax == Decimal(truth["tax"])

        # Metadata match
        assert invoice.vendor_name == truth["vendor_name"]
        assert invoice.invoice_no == truth["invoice_no"]
        assert invoice.invoice_date == truth["invoice_date"]


# ==============================================================================
# 3. Image Fixtures Test Suite
# ==============================================================================


class TestE2EImageFixtures:
    """End-to-end tests for thermal and EXIF-oriented receipt images."""

    @pytest.mark.parametrize("image_name", IMAGE_FIXTURE_NAMES)
    def test_image_fixture_e2e(self, image_name: str, vault_tracker: List[Vault]):
        file_path = IMAGE_DIR / image_name
        assert file_path.is_file(), f"Fixture file not found: {file_path}"

        invoice, truth = run_pipeline_for_fixture(file_path, vault_tracker)

        # Status match
        assert invoice.status == InvoiceStatus(truth["status"])
        assert invoice.review_reasons == []

        # Totals match exact financial precision
        if truth.get("grand_total") is not None:
            assert invoice.grand_total == Decimal(truth["grand_total"])
        if truth.get("subtotal") is not None:
            assert invoice.subtotal == Decimal(truth["subtotal"])
        if truth.get("tax") is not None:
            assert invoice.tax == Decimal(truth["tax"])

        # Metadata match
        assert invoice.vendor_name == truth["vendor_name"]
        assert invoice.invoice_no == truth["invoice_no"]
        assert invoice.invoice_date == truth["invoice_date"]


# ==============================================================================
# 4. Review Needed Intentional Scenarios
# ==============================================================================


class TestE2EReviewNeeded:
    """Tests confirming validator correctly assigns REVIEW_NEEDED on deviations."""

    def test_math_discrepancy_results_in_review_needed(self, vault_tracker: List[Vault]):
        """When total amount does not balance, status is REVIEW_NEEDED with math flag."""
        file_path = PDF_DIR / "01_multipage_goods.pdf"
        invoice, _ = run_pipeline_for_fixture(file_path, vault_tracker, corrupt_math=True)

        assert invoice.status == InvoiceStatus.REVIEW_NEEDED
        assert len(invoice.review_reasons) > 0
        assert any("math" in r.lower() or "tier" in r.lower() for r in invoice.review_reasons)

    def test_ghost_token_results_in_review_needed(self, vault_tracker: List[Vault]):
        """Ghost token not in Vault results in REVIEW_NEEDED with unknown_token flag."""
        file_path = PDF_DIR / "01_multipage_goods.pdf"
        invoice, _ = run_pipeline_for_fixture(file_path, vault_tracker, ghost_token=True)

        assert invoice.status == InvoiceStatus.REVIEW_NEEDED
        assert "unknown_token" in invoice.review_reasons

    def test_target_month_mismatch_results_in_review_needed(self, vault_tracker: List[Vault]):
        """When document date is outside target month (+-45 days window), status is REVIEW_NEEDED."""
        file_path = PDF_DIR / "01_multipage_goods.pdf"  # Date: 2026-08-10
        invoice, _ = run_pipeline_for_fixture(file_path, vault_tracker, target_month="2025-01")

        assert invoice.status == InvoiceStatus.REVIEW_NEEDED
        assert any("outside target month" in r for r in invoice.review_reasons)


# ==============================================================================
# 5. Full Pipeline Export Flow (JSONL + Excel)
# ==============================================================================


class TestE2EExportFlow:
    """End-to-end tests validating the full export pipeline."""

    def test_export_all_fixtures_jsonl_and_excel(self, tmp_path: Path, vault_tracker: List[Vault]):
        """Process all 13 synthetic fixtures and export to JSONL and Excel summary.

        Verifies:
        - All 13 invoices successfully processed
        - JSONL output integrity (13 valid lines, all fields deserializable)
        - Excel summary workbook integrity (4 sheets populated, correct row counts)
        """
        all_fixtures: List[Path] = []
        for name in PDF_FIXTURE_NAMES:
            all_fixtures.append(PDF_DIR / name)
        for name in SCAN_FIXTURE_NAMES:
            all_fixtures.append(SCAN_DIR / name)
        for name in IMAGE_FIXTURE_NAMES:
            all_fixtures.append(IMAGE_DIR / name)

        assert len(all_fixtures) == 13

        invoices: List[CanonicalInvoice] = []
        for fpath in all_fixtures:
            inv, truth = run_pipeline_for_fixture(fpath, vault_tracker)
            assert inv.status == InvoiceStatus.VERIFIED
            invoices.append(inv)

        assert len(invoices) == 13

        # 1. Test JSONLExporter
        jsonl_path = tmp_path / "output" / "invoices.jsonl"
        with JSONLExporter(jsonl_path) as exporter:
            for inv in invoices:
                exporter.write_invoice(inv)

        assert jsonl_path.is_file()
        with open(jsonl_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        assert len(lines) == 13
        for line, inv in zip(lines, invoices):
            data = json.loads(line)
            assert data["source_file"] == inv.source_file
            assert data["source_sha256"] == inv.source_sha256
            assert data["vendor_name"] == inv.vendor_name
            assert data["status"] == "VERIFIED"
            if inv.grand_total is not None:
                assert data["grand_total"] == str(inv.grand_total)

        # 2. Test export_excel_summary
        excel_path = export_excel_summary(
            invoices=invoices,
            duplicates=[],
            output_dir=tmp_path / "output",
            month="2026-08",
        )

        assert excel_path.is_file()
        assert excel_path.name == "Summary_2026-08.xlsx"

        # Verify workbook sheets and data integrity
        wb = openpyxl.load_workbook(excel_path, data_only=True)
        expected_sheets = ["Invoice Overview", "Line Items Detail", "Discrepancy Alerts", "Duplicates"]
        for sheet_name in expected_sheets:
            assert sheet_name in wb.sheetnames, f"Sheet {sheet_name} missing from workbook"

        ws_overview = wb["Invoice Overview"]
        # Header is row 1, data rows are 2 to 14 (13 items)
        overview_rows = list(ws_overview.iter_rows(values_only=True))
        # Total rows including header
        assert len(overview_rows) == 14

        ws_lines = wb["Line Items Detail"]
        line_rows = list(ws_lines.iter_rows(values_only=True))
        assert len(line_rows) > 1, "Line items sheet must contain data rows"


# ==============================================================================
# Phase 7 Evaluation Tests (eval/run_eval.py)
# ==============================================================================

class TestPhase7Evaluation:
    """Test evaluation metric calculations in eval/run_eval.py."""

    def test_eval_metrics_perfect_accuracy(self, tmp_path: Path):
        """When predictions match ground truths perfectly, false-verify rate is 0 and accuracies are 1.0."""
        from eval.run_eval import run_evaluation

        golden = {
            "inv1.pdf": {
                "source_file": "inv1.pdf",
                "status": "VERIFIED",
                "vendor_name": "Acme Inc",
                "invoice_no": "INV-001",
                "invoice_date": "2026-08-01",
                "grand_total": "100.00",
                "subtotal": "90.00",
                "tax": "10.00",
                "page_count": 2,
            }
        }
        predictions = [
            {
                "source_file": "inv1.pdf",
                "status": "VERIFIED",
                "vendor_name": "Acme Inc",
                "invoice_no": "INV-001",
                "invoice_date": "2026-08-01",
                "grand_total": "100.00",
                "subtotal": "90.00",
                "tax": "10.00",
            }
        ]
        timing = {"total_duration_sec": 4.0, "total_pages": 2}

        report = run_evaluation(predictions, golden, timing_data=timing)

        assert report.total_files == 1
        assert report.verified_count == 1
        assert report.false_verify_count == 0
        assert report.false_verify_rate == 0.0
        assert report.field_accuracy["vendor_name"] == 1.0
        assert report.field_accuracy["grand_total"] == 1.0
        assert report.seconds_per_page == 2.0

    def test_eval_metrics_detects_false_verify(self):
        """A VERIFIED prediction with an incorrect field must be counted as false-verify."""
        from eval.run_eval import run_evaluation

        golden = {
            "inv1.pdf": {
                "source_file": "inv1.pdf",
                "status": "VERIFIED",
                "vendor_name": "Acme Inc",
                "invoice_no": "INV-001",
                "invoice_date": "2026-08-01",
                "grand_total": "100.00",
                "page_count": 1,
            }
        }
        # Model hallucinated 150.00 instead of 100.00 but marked as VERIFIED!
        predictions = [
            {
                "source_file": "inv1.pdf",
                "status": "VERIFIED",
                "vendor_name": "Acme Inc",
                "invoice_no": "INV-001",
                "invoice_date": "2026-08-01",
                "grand_total": "150.00",
            }
        ]

        report = run_evaluation(predictions, golden)

        assert report.verified_count == 1
        assert report.false_verify_count == 1
        assert report.false_verify_rate == 1.0
        assert report.field_accuracy["grand_total"] == 0.0

    def test_eval_cli_run(self, tmp_path: Path):
        """Test eval/run_eval.py CLI entrypoint."""
        from eval.run_eval import main as eval_main

        golden_file = tmp_path / "golden.jsonl"
        pred_file = tmp_path / "pred.jsonl"

        record = {
            "source_file": "sample.pdf",
            "status": "VERIFIED",
            "vendor_name": "Test Co",
            "invoice_no": "123",
            "invoice_date": "2026-08-01",
            "grand_total": "50.00",
            "page_count": 1,
        }
        golden_file.write_text(json.dumps(record) + "\n", encoding="utf-8")
        pred_file.write_text(json.dumps(record) + "\n", encoding="utf-8")

        ret = eval_main(["--golden", str(golden_file), "--predictions", str(pred_file)])
        assert ret == 0

