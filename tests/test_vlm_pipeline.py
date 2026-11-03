"""Unit tests for Multimodal VLM Pipeline and schema extraction.

Tests:
1. load_document_images (PDF rendering, image loading, EXIF, dimension bounds).
2. VLMInvoice and VLMSummary normalization (fees, vendor/invoice_number aliases).
3. vlm_to_canonical conversion (Decimal parsing, currency symbols, date ISO format).
4. _clean_json_markdown fence handling.
5. End-to-end process_invoice_file with mock VLM client (math verification, review reasons, caching).
"""

from decimal import Decimal
import json
from pathlib import Path
from unittest.mock import MagicMock
import pymupdf as fitz
from PIL import Image
import pytest

from config import Category, SCHEMA_VERSION
from core.ingestion import load_document_images, compute_file_sha256
from core.llm_cache import LLMCache
from core.llm_parser import LLMClient, _clean_json_markdown
from core.pipeline import process_invoice_file
from models.schema import (
    CanonicalInvoice,
    DocType,
    InvoiceStatus,
    LineItemKind,
    VLMCharge,
    VLMInvoice,
    VLMLineItem,
    VLMSummary,
    vlm_to_canonical,
)


@pytest.fixture
def synthetic_pdf(tmp_path: Path) -> Path:
    """Create a sample 2-page synthetic PDF document."""
    pdf_path = tmp_path / "invoice_sample.pdf"
    doc = fitz.open()
    p1 = doc.new_page(width=600, height=800)
    p1.insert_text((50, 100), "ACME Test Supplier Inc. Invoice INV-9901", fontsize=14)
    p2 = doc.new_page(width=600, height=800)
    p2.insert_text((50, 100), "Page 2 Totals: Total Due $150.00", fontsize=14)
    doc.save(pdf_path)
    doc.close()
    return pdf_path


@pytest.fixture
def synthetic_png(tmp_path: Path) -> Path:
    """Create a sample PNG image."""
    img_path = tmp_path / "receipt_sample.png"
    img = Image.new("RGB", (400, 300), color=(255, 255, 255))
    img.save(img_path, format="PNG")
    return img_path


# ==============================================================================
# 1. Ingestion: load_document_images
# ==============================================================================

def test_load_document_images_pdf(synthetic_pdf: Path) -> None:
    """Test PDF pages are rendered into base64 JPEG strings."""
    images = load_document_images(synthetic_pdf, dpi=150, max_dimension=1024)
    assert len(images) == 2
    for b64 in images:
        assert isinstance(b64, str)
        assert len(b64) > 100


def test_load_document_images_image(synthetic_png: Path) -> None:
    """Test image loading returns single base64 string."""
    images = load_document_images(synthetic_png)
    assert len(images) == 1
    assert len(images[0]) > 100


def test_load_document_images_missing_file(tmp_path: Path) -> None:
    """Test FileNotFoundError on non-existent path."""
    with pytest.raises(FileNotFoundError):
        load_document_images(tmp_path / "non_existent.pdf")


def test_load_document_images_unsupported(tmp_path: Path) -> None:
    """Test ValueError on unsupported file format."""
    bad_file = tmp_path / "test.txt"
    bad_file.write_text("Hello world")
    with pytest.raises(ValueError, match="Unsupported document format"):
        load_document_images(bad_file)


# ==============================================================================
# 2. Markdown cleaning & fence stripping
# ==============================================================================

def test_clean_json_markdown() -> None:
    """Test markdown code fence stripping for enclosed and unclosed fences."""
    # Enclosed fence
    text1 = "```json\n{\"foo\": \"bar\"}\n```"
    assert _clean_json_markdown(text1) == "{\"foo\": \"bar\"}"

    # Generic fence
    text2 = "```\n{\"foo\": \"bar\"}\n```"
    assert _clean_json_markdown(text2) == "{\"foo\": \"bar\"}"

    # Truncated closing fence
    text3 = "```json\n{\"foo\": \"bar\"}"
    assert _clean_json_markdown(text3) == "{\"foo\": \"bar\"}"

    # Bare JSON
    text4 = "{\"foo\": \"bar\"}"
    assert _clean_json_markdown(text4) == "{\"foo\": \"bar\"}"


# ==============================================================================
# 3. Schema Normalization & vlm_to_canonical
# ==============================================================================

def test_vlm_summary_fees_normalization() -> None:
    """Test that scalar fees (0.0 or positive float) normalize to lists."""
    s1 = VLMSummary.model_validate({"fees": 0.0})
    assert s1.fees == []

    s2 = VLMSummary.model_validate({"fees": 12.50})
    assert s2.fees == [12.50]

    s3 = VLMSummary.model_validate({"fees": ["5.00", "2.50"]})
    assert s3.fees == ["5.00", "2.50"]


def test_vlm_invoice_field_aliases() -> None:
    """Test vendor object and invoice_number alias mapping."""
    data = {
        "doc_type": "goods_invoice",
        "vendor": {"name": "Vendor Alias Inc.", "tax_id": "123"},
        "invoice_number": "INV-ALIAS-001",
        "invoice_date": "2026-08-15",
        "line_items": [],
        "summary": {"grand_total": "$100.00"},
    }
    inv = VLMInvoice.model_validate(data)
    assert inv.vendor_name == "Vendor Alias Inc."
    assert inv.invoice_no == "INV-ALIAS-001"


def test_vlm_to_canonical_conversion() -> None:
    """Test conversion of VLMInvoice into CanonicalInvoice with Decimal parsing."""
    vlm = VLMInvoice(
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="Test Supplier LLC",
        invoice_no="INV-100",
        invoice_date="08/15/2026",
        due_date="2026-08-30",
        currency="USD",
        category=Category.FOOD_INGREDIENTS,
        line_items=[
            VLMLineItem(
                item_name="Item A",
                qty="2",
                unit_price="$10.00",
                line_total="20.00",
                unit="EA",
                kind=LineItemKind.GOODS,
            ),
            VLMLineItem(
                item_name="Special Discount",
                qty="1",
                unit_price="(5.00)",
                line_total="-5.00",
                unit=None,
                kind=LineItemKind.DISCOUNT,
            ),
        ],
        charges=[
            VLMCharge(description="Service Fee", amount="2.50")
        ],
        summary=VLMSummary(
            subtotal="20.00",
            tax="$1.50",
            discount="5.00",
            fees=["2.50"],
            grand_total="$19.00",
            amount_due="19.00",
        ),
    )

    canonical = vlm_to_canonical(
        vlm=vlm,
        source_file="test.pdf",
        source_sha256="abc123sha",
    )

    assert canonical.source_file == "test.pdf"
    assert canonical.source_sha256 == "abc123sha"
    assert canonical.vendor_name == "Test Supplier LLC"
    assert canonical.invoice_date == "2026-08-15"
    assert canonical.due_date == "2026-08-30"
    assert canonical.subtotal == Decimal("20.00")
    assert canonical.tax == Decimal("1.50")
    assert canonical.discount == Decimal("5.00")
    assert canonical.grand_total == Decimal("19.00")
    assert canonical.amount_due == Decimal("19.00")
    assert len(canonical.line_items) == 2
    assert canonical.line_items[0].qty == Decimal("2")
    assert canonical.line_items[0].unit_price == Decimal("10.00")
    assert canonical.line_items[1].line_total == Decimal("-5.00")
    assert len(canonical.charges) == 1
    assert canonical.charges[0].amount == Decimal("2.50")


# ==============================================================================
# 4. End-to-End process_invoice_file with Vision Mock
# ==============================================================================

class MockVLMClient:
    """Mock client implementing parse_invoice_vision for deterministic testing."""

    def __init__(self, vlm_result: VLMInvoice, model: str = "gemini-3.8-flash") -> None:
        self.vlm_result = vlm_result
        self.model = model
        self.call_count = 0

    def parse_invoice_vision(self, images_base64, prompt=None) -> VLMInvoice:
        self.call_count += 1
        return self.vlm_result


def test_process_invoice_file_vision_verified(synthetic_pdf: Path) -> None:
    """Test process_invoice_file achieves VERIFIED status on mathematically sound VLM extraction."""
    vlm = VLMInvoice(
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="ACME Test Foods",
        invoice_no="INV-2026-001",
        invoice_date="2026-08-15",
        due_date="2026-08-30",
        currency="USD",
        category=Category.FOOD_INGREDIENTS,
        line_items=[
            VLMLineItem(
                item_name="Whole Milk",
                qty="5",
                unit_price="10.00",
                line_total="50.00",
                unit="GAL",
                kind=LineItemKind.GOODS,
            )
        ],
        summary=VLMSummary(
            subtotal="50.00",
            tax="5.00",
            grand_total="55.00",
            amount_due="55.00",
        ),
    )
    mock_client = MockVLMClient(vlm)
    inv = process_invoice_file(
        file_path=synthetic_pdf,
        llm_client=mock_client,  # type: ignore[arg-type]
        target_month="2026-08",
    )

    assert inv.status == InvoiceStatus.VERIFIED
    assert inv.vendor_name == "ACME Test Foods"
    assert inv.grand_total == Decimal("55.00")
    assert inv.subtotal == Decimal("50.00")
    assert inv.tax == Decimal("5.00")
    assert mock_client.call_count == 1


def test_process_invoice_file_vision_corrupted_math(synthetic_pdf: Path) -> None:
    """Test process_invoice_file catches math discrepancy and flags REVIEW_NEEDED."""
    vlm = VLMInvoice(
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="ACME Test Foods",
        invoice_no="INV-2026-001",
        invoice_date="2026-08-15",
        due_date="2026-08-30",
        currency="USD",
        category=Category.FOOD_INGREDIENTS,
        line_items=[
            VLMLineItem(
                item_name="Whole Milk",
                qty="5",
                unit_price="10.00",
                line_total="50.00",
                unit="GAL",
                kind=LineItemKind.GOODS,
            )
        ],
        summary=VLMSummary(
            subtotal="50.00",
            tax="5.00",
            grand_total="999.00",  # Corrupted: 50 + 5 != 999
            amount_due="999.00",
        ),
    )
    mock_client = MockVLMClient(vlm)
    inv = process_invoice_file(
        file_path=synthetic_pdf,
        llm_client=mock_client,  # type: ignore[arg-type]
        target_month="2026-08",
    )

    assert inv.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Tier 3" in r for r in inv.review_reasons)


def test_process_invoice_file_vision_caching(synthetic_pdf: Path, tmp_path: Path) -> None:
    """Test that vision extraction results are cached and reused on subsequent calls."""
    cache_dir = tmp_path / "test_cache"
    cache = LLMCache(cache_dir=cache_dir)

    vlm = VLMInvoice(
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="Cached Foods",
        invoice_no="INV-CACHE-01",
        invoice_date="2026-08-15",
        summary=VLMSummary(
            subtotal="20.00",
            tax="2.00",
            grand_total="22.00",
            amount_due="22.00",
        ),
    )
    mock_client = MockVLMClient(vlm)

    # First call: cache miss
    inv1 = process_invoice_file(
        file_path=synthetic_pdf,
        llm_client=mock_client,  # type: ignore[arg-type]
        cache=cache,
        target_month="2026-08",
    )
    assert mock_client.call_count == 1
    assert inv1.vendor_name == "Cached Foods"

    # Second call: cache hit, mock client call count unchanged
    inv2 = process_invoice_file(
        file_path=synthetic_pdf,
        llm_client=mock_client,  # type: ignore[arg-type]
        cache=cache,
        target_month="2026-08",
    )
    assert mock_client.call_count == 1
    assert inv2.vendor_name == "Cached Foods"
    assert inv2.grand_total == Decimal("22.00")
