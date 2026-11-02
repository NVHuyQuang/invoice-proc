"""Unit tests for core/pipeline.py (Wave 2 pipeline).

Tests cover:
- End-to-end success on clean PDF (pdf_text layer) and image (mock OCR)
- dry_run execution (halts after Leak Guard, prints masked payload, never calls LLM)
- LLMCache hit and miss behavior (resume support)
- Error isolation: corrupted file, missing file, unsupported type -> FAILED
- Error isolation: OCR engine failure -> FAILED with ocr_error
- Error isolation: LLM client failure -> FAILED with llm_error
- Leak Guard rejection -> REVIEW_NEEDED with ['leak_guard_violation']
- Invariant: vault.clear() is guaranteed to be called in all scenarios
- Target month validation behavior

INVARIANTS:
1. ZERO real invoice data. All files are synthetically created.
2. ZERO real network calls. Fully mocked LLM and OCR.
3. Vault contents, raw OCR text, and LLM payloads are never leaked.
"""

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import pymupdf
from PIL import Image

from config import Category
import core.ocr_preprocess
from core.llm_cache import LLMCache
from core.llm_parser import LLMClient
from core.ocr_engine import OCREngine
from core.pipeline import process_invoice_file
from core.types import Vault, Word
from models.schema import (
    CanonicalInvoice,
    DocType,
    InvoiceStatus,
    LineItemKind,
    LLMInvoice,
    LLMLineItem,
    LLMSummary,
)


@pytest.fixture
def synthetic_clean_pdf(tmp_path: Path) -> Path:
    """Create a clean PDF invoice with text layer (>= 50 chars, valid layout)."""
    pdf_path = tmp_path / "clean_invoice.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)

    # Standard clean invoice text with header, line items, totals
    text = (
        "ACME WHOLESALE SUPPLIES INC\n"
        "Invoice Number: INV-2026-001\n"
        "Invoice Date: 2026-08-15\n"
        "Payment Due Date: 2026-08-30\n"
        "Description | Quantity | Unit Price | Total Amount\n"
        "Widget Alpha Premium Model | 2 | 10.00 | 20.00\n"
        "Widget Beta Standard Model | 3 | 10.00 | 30.00\n"
        "Subtotal: 50.00\n"
        "Tax Amount: 5.00\n"
        "Grand Total: 55.00\n"
        "Amount Due: 55.00\n"
    )
    page.insert_text((50, 80), text, fontsize=11)
    doc.save(pdf_path)
    doc.close()
    return pdf_path


@pytest.fixture
def synthetic_image_file(tmp_path: Path) -> Path:
    """Create a synthetic PNG image for OCR testing."""
    img_path = tmp_path / "synth_receipt.png"
    img = Image.new("RGB", (300, 200), color=(255, 255, 255))
    img.save(img_path, format="PNG")
    return img_path


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """Mock LLMClient returning a mathematically sound LLMInvoice for synthetic_clean_pdf."""
    client = MagicMock(spec=LLMClient)

    def _parse(prompt: str, masked_payload: str) -> LLMInvoice:
        # Construct valid token references corresponding to the synthetic clean invoice
        return LLMInvoice(
            doc_type=DocType.GOODS_INVOICE,
            vendor_name="ACME WHOLESALE SUPPLIES INC",
            invoice_no_ref="<ID_1>",
            invoice_date_ref="<D_1>",
            due_date_ref="<D_2>",
            currency="$",
            category=Category.OTHER,
            line_items=[
                LLMLineItem(
                    item_name="Widget Alpha Premium Model",
                    qty_ref="<N_2>",
                    unit_price_ref="<N_3>",
                    line_total_ref="<N_4>",
                    kind=LineItemKind.GOODS,
                ),
                LLMLineItem(
                    item_name="Widget Beta Standard Model",
                    qty_ref="<N_5>",
                    unit_price_ref="<N_6>",
                    line_total_ref="<N_7>",
                    kind=LineItemKind.GOODS,
                ),
            ],
            summary=LLMSummary(
                subtotal_ref="<N_8>",
                tax_ref="<N_9>",
                grand_total_ref="<N_10>",
                amount_due_ref="<N_11>",
            ),
            unassigned=[],
        )

    client.parse_invoice.side_effect = _parse
    return client


# ==============================================================================
# 1. Success Scenarios
# ==============================================================================


class TestPipelineSuccess:
    """Test successful end-to-end invoice processing."""

    def test_pdf_invoice_success_verified(
        self, synthetic_clean_pdf: Path, mock_llm_client: MagicMock
    ):
        """Clean PDF should process through all stages and result in VERIFIED status."""
        invoice = process_invoice_file(
            file_path=synthetic_clean_pdf,
            llm_client=mock_llm_client,
            target_month="2026-08",
        )

        assert isinstance(invoice, CanonicalInvoice)
        assert invoice.status == InvoiceStatus.VERIFIED
        assert invoice.review_reasons == []
        assert invoice.vendor_name == "ACME WHOLESALE SUPPLIES INC"
        assert invoice.invoice_no == "INV-2026-001"
        assert invoice.invoice_date == "2026-08-15"
        assert invoice.grand_total == Decimal("55.00")
        assert invoice.subtotal == Decimal("50.00")
        assert invoice.tax == Decimal("5.00")
        assert len(invoice.line_items) == 2
        assert invoice.source_file == str(synthetic_clean_pdf)
        assert len(invoice.source_sha256) == 64
        assert mock_llm_client.parse_invoice.called

    def test_image_invoice_success_verified(
        self, synthetic_image_file: Path, mock_llm_client: MagicMock
    ):
        """Image file processed via mock OCR engine should succeed and verify."""
        mock_ocr = MagicMock(spec=OCREngine)
        # Mock OCR output tokens matching the synthetic layout
        mock_ocr.predict.return_value = [
            Word(text="ACME", bbox=(50, 50, 90, 65), conf=0.98, page=1, source="ocr"),
            Word(text="SUPPLIES", bbox=(95, 50, 150, 65), conf=0.98, page=1, source="ocr"),
            Word(text="INV-2026-001", bbox=(50, 70, 140, 85), conf=0.98, page=1, source="ocr"),
            Word(text="2026-08-15", bbox=(50, 90, 120, 105), conf=0.98, page=1, source="ocr"),
            Word(text="2026-08-30", bbox=(50, 110, 120, 125), conf=0.98, page=1, source="ocr"),
            Word(text="Widget", bbox=(50, 140, 90, 155), conf=0.98, page=1, source="ocr"),
            Word(text="Alpha", bbox=(95, 140, 130, 155), conf=0.98, page=1, source="ocr"),
            Word(text="2", bbox=(200, 140, 210, 155), conf=0.98, page=1, source="ocr"),
            Word(text="10.00", bbox=(250, 140, 280, 155), conf=0.98, page=1, source="ocr"),
            Word(text="20.00", bbox=(320, 140, 350, 155), conf=0.98, page=1, source="ocr"),
            Word(text="Widget", bbox=(50, 160, 90, 175), conf=0.98, page=1, source="ocr"),
            Word(text="Beta", bbox=(95, 160, 125, 175), conf=0.98, page=1, source="ocr"),
            Word(text="3", bbox=(200, 160, 210, 175), conf=0.98, page=1, source="ocr"),
            Word(text="10.00", bbox=(250, 160, 280, 175), conf=0.98, page=1, source="ocr"),
            Word(text="30.00", bbox=(320, 160, 350, 175), conf=0.98, page=1, source="ocr"),
            Word(text="Subtotal", bbox=(50, 190, 100, 205), conf=0.98, page=1, source="ocr"),
            Word(text="50.00", bbox=(320, 190, 350, 205), conf=0.98, page=1, source="ocr"),
            Word(text="Tax", bbox=(50, 210, 80, 225), conf=0.98, page=1, source="ocr"),
            Word(text="5.00", bbox=(320, 210, 350, 225), conf=0.98, page=1, source="ocr"),
            Word(text="Total", bbox=(50, 230, 90, 245), conf=0.98, page=1, source="ocr"),
            Word(text="55.00", bbox=(320, 230, 350, 245), conf=0.98, page=1, source="ocr"),
            Word(text="Due", bbox=(50, 250, 80, 265), conf=0.98, page=1, source="ocr"),
            Word(text="55.00", bbox=(320, 250, 350, 265), conf=0.98, page=1, source="ocr"),
        ]

        invoice = process_invoice_file(
            file_path=synthetic_image_file,
            llm_client=mock_llm_client,
            ocr_engine=mock_ocr,
            target_month="2026-08",
        )

        assert invoice.status == InvoiceStatus.VERIFIED
        assert mock_ocr.predict.called
        assert invoice.grand_total == Decimal("55.00")


# ==============================================================================
# 2. Dry Run
# ==============================================================================


class TestPipelineDryRun:
    """Test dry_run functionality."""

    def test_dry_run_prints_masked_payload_and_halts_before_llm(
        self, synthetic_clean_pdf: Path, mock_llm_client: MagicMock, capsys
    ):
        """When dry_run=True, prints masked payload and returns without calling LLM."""
        invoice = process_invoice_file(
            file_path=synthetic_clean_pdf,
            llm_client=mock_llm_client,
            dry_run=True,
        )

        # 1. LLM client must NOT have been called
        assert not mock_llm_client.parse_invoice.called

        # 2. Status should be REVIEW_NEEDED with 'dry_run' reason
        assert invoice.status == InvoiceStatus.REVIEW_NEEDED
        assert "dry_run" in invoice.review_reasons

        # 3. Masked payload should be printed to stdout
        captured = capsys.readouterr()
        assert "<N_" in captured.out
        assert "<ID_" in captured.out or "<D_" in captured.out


# ==============================================================================
# 3. LLMCache (Hit and Miss)
# ==============================================================================


class TestPipelineCache:
    """Test resume and caching mechanism."""

    def test_cache_miss_calls_llm_and_populates_cache(
        self, synthetic_clean_pdf: Path, mock_llm_client: MagicMock, tmp_path: Path
    ):
        """First execution should populate cache."""
        cache = LLMCache(cache_dir=tmp_path / "test_cache")

        invoice1 = process_invoice_file(
            file_path=synthetic_clean_pdf,
            llm_client=mock_llm_client,
            cache=cache,
            target_month="2026-08",
        )

        assert invoice1.status == InvoiceStatus.VERIFIED
        assert mock_llm_client.parse_invoice.call_count == 1

        # Second execution on same file should hit cache and NOT call LLM again
        invoice2 = process_invoice_file(
            file_path=synthetic_clean_pdf,
            llm_client=mock_llm_client,
            cache=cache,
            target_month="2026-08",
        )

        assert invoice2.status == InvoiceStatus.VERIFIED
        assert mock_llm_client.parse_invoice.call_count == 1
        assert invoice1.grand_total == invoice2.grand_total


# ==============================================================================
# 4. Error Isolation (File, OCR, LLM failures -> FAILED)
# ==============================================================================


class TestPipelineErrorIsolation:
    """Test per-file error isolation without crashing."""

    def test_missing_file_returns_failed(self, mock_llm_client: MagicMock, tmp_path: Path):
        """Non-existent file returns FAILED with file_unreadable."""
        missing = tmp_path / "does_not_exist.pdf"
        invoice = process_invoice_file(file_path=missing, llm_client=mock_llm_client)

        assert invoice.status == InvoiceStatus.FAILED
        assert any(r.startswith("file_unreadable") for r in invoice.review_reasons)
        assert not mock_llm_client.parse_invoice.called

    def test_corrupted_pdf_file_returns_failed(
        self, mock_llm_client: MagicMock, tmp_path: Path
    ):
        """Corrupted PDF binary returns FAILED with file_unreadable."""
        corrupt = tmp_path / "broken.pdf"
        corrupt.write_bytes(b"%PDF-1.4\nCorrupted content without xref or EOF")

        invoice = process_invoice_file(file_path=corrupt, llm_client=mock_llm_client)

        assert invoice.status == InvoiceStatus.FAILED
        assert any(r.startswith("file_unreadable") for r in invoice.review_reasons)
        assert not mock_llm_client.parse_invoice.called

    def test_corrupted_image_file_returns_failed(
        self, mock_llm_client: MagicMock, tmp_path: Path
    ):
        """Corrupted image file returns FAILED with file_unreadable."""
        corrupt_img = tmp_path / "broken.png"
        corrupt_img.write_bytes(b"\x89PNG\r\n\x1a\nNot a real PNG content")

        invoice = process_invoice_file(file_path=corrupt_img, llm_client=mock_llm_client)

        assert invoice.status == InvoiceStatus.FAILED
        assert any(r.startswith("file_unreadable") for r in invoice.review_reasons)
        assert not mock_llm_client.parse_invoice.called

    def test_unsupported_file_type_returns_failed(
        self, mock_llm_client: MagicMock, tmp_path: Path
    ):
        """File with unsupported magic bytes returns FAILED."""
        bad_file = tmp_path / "sample.txt"
        bad_file.write_text("Hello plain text invoice", encoding="utf-8")

        invoice = process_invoice_file(file_path=bad_file, llm_client=mock_llm_client)

        assert invoice.status == InvoiceStatus.FAILED
        assert any(r.startswith("file_unreadable") for r in invoice.review_reasons)

    def test_ocr_failure_returns_failed(
        self, synthetic_image_file: Path, mock_llm_client: MagicMock
    ):
        """OCR engine exception returns FAILED with ocr_error without crashing."""
        mock_ocr = MagicMock(spec=OCREngine)
        mock_ocr.predict.side_effect = RuntimeError("PaddleOCR inference crashed")

        invoice = process_invoice_file(
            file_path=synthetic_image_file,
            llm_client=mock_llm_client,
            ocr_engine=mock_ocr,
        )

        assert invoice.status == InvoiceStatus.FAILED
        assert "ocr_error" in invoice.review_reasons
        assert not mock_llm_client.parse_invoice.called

    def test_llm_failure_returns_failed(
        self, synthetic_clean_pdf: Path
    ):
        """LLM API error returns FAILED with llm_error without crashing."""
        failing_client = MagicMock(spec=LLMClient)
        failing_client.parse_invoice.side_effect = ConnectionError("Proxy 127.0.0.1:8045 unreachable")

        invoice = process_invoice_file(
            file_path=synthetic_clean_pdf,
            llm_client=failing_client,
        )

        assert invoice.status == InvoiceStatus.FAILED
        assert "llm_error" in invoice.review_reasons


# ==============================================================================
# 5. Leak Guard Gate
# ==============================================================================


class TestPipelineLeakGuard:
    """Test Leak Guard egress protection gate."""

    def test_leak_guard_rejection_returns_review_needed(
        self, synthetic_clean_pdf: Path, mock_llm_client: MagicMock
    ):
        """When Leak Guard detects violation, halts immediately with REVIEW_NEEDED."""
        with patch("core.pipeline.verify_payload") as mock_verify:
            mock_verify.return_value = (False, ["Rule 'raw_money' failed at line 3"])

            invoice = process_invoice_file(
                file_path=synthetic_clean_pdf,
                llm_client=mock_llm_client,
            )

            assert invoice.status == InvoiceStatus.REVIEW_NEEDED
            assert "leak_guard_violation" in invoice.review_reasons
            # Critical: LLM must NEVER receive a leaking payload
            assert not mock_llm_client.parse_invoice.called


# ==============================================================================
# 6. Vault Lifecycle & Memory Clearance
# ==============================================================================


class TestPipelineVaultClearance:
    """Test invariant: vault.clear() must be executed in finally block."""

    def test_vault_cleared_on_success(
        self, synthetic_clean_pdf: Path, mock_llm_client: MagicMock
    ):
        """Vault must be wiped from memory on successful run."""
        with patch.object(Vault, "clear", autospec=True) as mock_clear:
            invoice = process_invoice_file(
                file_path=synthetic_clean_pdf,
                llm_client=mock_llm_client,
                target_month="2026-08",
            )
            assert invoice.status == InvoiceStatus.VERIFIED
            assert mock_clear.called

    def test_vault_cleared_on_dry_run(
        self, synthetic_clean_pdf: Path, mock_llm_client: MagicMock
    ):
        """Vault must be wiped from memory even on dry_run."""
        with patch.object(Vault, "clear", autospec=True) as mock_clear:
            invoice = process_invoice_file(
                file_path=synthetic_clean_pdf,
                llm_client=mock_llm_client,
                dry_run=True,
            )
            assert invoice.status == InvoiceStatus.REVIEW_NEEDED
            assert mock_clear.called

    def test_vault_cleared_on_leak_guard_violation(
        self, synthetic_clean_pdf: Path, mock_llm_client: MagicMock
    ):
        """Vault must be wiped from memory if Leak Guard rejects payload."""
        with patch("core.pipeline.verify_payload", return_value=(False, ["violation"])):
            with patch.object(Vault, "clear", autospec=True) as mock_clear:
                invoice = process_invoice_file(
                    file_path=synthetic_clean_pdf,
                    llm_client=mock_llm_client,
                )
                assert invoice.status == InvoiceStatus.REVIEW_NEEDED
                assert mock_clear.called

    def test_vault_cleared_on_llm_exception(
        self, synthetic_clean_pdf: Path
    ):
        """Vault must be wiped from memory even when LLM raises fatal error."""
        failing_client = MagicMock(spec=LLMClient)
        failing_client.parse_invoice.side_effect = RuntimeError("Fatal LLM crash")

        with patch.object(Vault, "clear", autospec=True) as mock_clear:
            invoice = process_invoice_file(
                file_path=synthetic_clean_pdf,
                llm_client=failing_client,
            )
            assert invoice.status == InvoiceStatus.FAILED
            assert mock_clear.called


# ==============================================================================
# 7. Target Month Verification
# ==============================================================================


class TestPipelineTargetMonth:
    """Test date window / target_month validation."""

    def test_target_month_mismatch_flags_review_needed(
        self, synthetic_clean_pdf: Path, mock_llm_client: MagicMock
    ):
        """Invoice date 2026-08-15 processed with target_month='2025-01' triggers REVIEW_NEEDED."""
        invoice = process_invoice_file(
            file_path=synthetic_clean_pdf,
            llm_client=mock_llm_client,
            target_month="2025-01",  # Outside +- 45 days window!
        )

        assert invoice.status == InvoiceStatus.REVIEW_NEEDED
        assert any("target month" in r.lower() or "outside target" in r.lower() for r in invoice.review_reasons)


# ==============================================================================
# 8. Reliability, Thread Safety, Provenance & Preprocessing (Wave 3 Group E)
# ==============================================================================


class TestPipelineWave3GroupEReliability:
    """Tests for Wave 3 Group E improvements."""

    def test_ocr_engine_has_lock_and_thread_safe(self):
        """OCREngine must have threading.Lock protecting initialize() and predict()."""
        import threading
        import numpy as np

        engine = OCREngine(mock=True)
        assert hasattr(engine, "_lock")
        assert isinstance(engine._lock, (type(threading.Lock()), type(threading.RLock())))

        # Concurrent initialize calls
        threads = [threading.Thread(target=engine.initialize) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert engine._engine is not None

        # Concurrent predict calls
        dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
        results = []

        def worker():
            words = engine.predict(dummy_img, page_num=1)
            results.append(words)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 8

    def test_pipeline_cache_put_exception_does_not_fail_invoice(
        self, synthetic_clean_pdf: Path, mock_llm_client: MagicMock
    ):
        """cache.put failure must be swallowed so the invoice is not failed."""
        cache = LLMCache(cache_dir="cache")
        with patch.object(cache, "put", side_effect=RuntimeError("Disk full")):
            invoice = process_invoice_file(
                file_path=synthetic_clean_pdf,
                llm_client=mock_llm_client,
                cache=cache,
                target_month="2026-08",
            )
            # Should still be VERIFIED despite cache.put failure
            assert invoice.status == InvoiceStatus.VERIFIED
            assert invoice.grand_total == Decimal("55.00")

    def test_pipeline_preserves_word_provenance_coordinates(
        self, synthetic_clean_pdf: Path, mock_llm_client: MagicMock
    ):
        """Pipeline must link Word.bbox, page, conf to VaultEntry and Provenance."""
        invoice = process_invoice_file(
            file_path=synthetic_clean_pdf,
            llm_client=mock_llm_client,
            target_month="2026-08",
        )
        assert invoice.status == InvoiceStatus.VERIFIED
        # Coordinates must not be all 0.0
        assert invoice.grand_total_prov is not None
        assert invoice.grand_total_prov.page == 1
        x0, y0, x1, y1 = invoice.grand_total_prov.bbox
        assert not (x0 == 0.0 and y0 == 0.0 and x1 == 0.0 and y1 == 0.0)

    def test_pipeline_conditional_ocr_preprocessing_called(
        self, synthetic_image_file: Path, mock_llm_client: MagicMock
    ):
        """Preprocessing (deskew, CLAHE) must be conditionally executed before OCR."""
        with patch("core.pipeline.deskew_image", wraps=core.ocr_preprocess.deskew_image) as spy_deskew, \
             patch("core.pipeline.enhance_contrast_clahe", wraps=core.ocr_preprocess.enhance_contrast_clahe) as spy_clahe:
            mock_ocr = OCREngine(mock=True)
            invoice = process_invoice_file(
                file_path=synthetic_image_file,
                llm_client=mock_llm_client,
                ocr_engine=mock_ocr,
                target_month="2026-08",
            )
            assert spy_deskew.called
            assert spy_clahe.called

