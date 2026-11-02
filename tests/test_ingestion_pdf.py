"""Unit tests for core/ingestion_pdf.py (PLAN 1.3-1.4).

Tests PDF dual-routing per page:
- Clean text extraction with Word(conf=1.0, source='pdf_text')
- Scanned image detection and 300 DPI rendering to numpy array
- Corrupted/noisy text-layer fallback to OCR
- Header/footer deduplication across multi-page documents
- Document assembly and SHA-256 calculation
- Page rotation bounding box transformation
- Huge page dimension capping (MAX_IMAGE_DIMENSION)

INVARIANTS:
1. No access to real invoice files.
2. All PDFs generated synthetically in memory / temp files.
"""

import hashlib
import io
from pathlib import Path
import numpy as np
import pymupdf as fitz
import pytest
from PIL import Image

from config import (
    PDF_RENDER_DPI,
    MIN_PRINTABLE_CHARS,
    MIN_VALID_CHAR_RATIO,
    MAX_IMAGE_AREA_RATIO,
    MAX_IMAGE_DIMENSION,
)
from core.ingestion_pdf import (
    is_valid_char,
    compute_valid_char_ratio,
    compute_background_image_ratio,
    render_page_to_image,
    inspect_pdf_page,
    deduplicate_headers_footers,
    load_pdf_document,
)
from core.types import Word, Page, Document


def _create_synthetic_clean_page(doc: fitz.Document, text: str, width: float = 595.0, height: float = 842.0) -> fitz.Page:
    """Helper: create clean text page."""
    page = doc.new_page(width=width, height=height)
    page.insert_text(fitz.Point(50, 50), text)
    return page


def _create_synthetic_image_page(doc: fitz.Document, width: float = 595.0, height: float = 842.0, area_ratio: float = 0.90) -> fitz.Page:
    """Helper: create page with background image covering area_ratio of the page."""
    page = doc.new_page(width=width, height=height)
    img_w, img_h = 300, 400
    img = Image.new("RGB", (img_w, img_h), color=(180, 180, 180))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    # Compute bbox to cover area_ratio
    margin_x = (width * (1.0 - (area_ratio ** 0.5))) / 2.0
    margin_y = (height * (1.0 - (area_ratio ** 0.5))) / 2.0
    rect = fitz.Rect(margin_x, margin_y, width - margin_x, height - margin_y)
    page.insert_image(rect, stream=buf.getvalue())
    return page


# =====================================================================
# Unit tests for character and ratio helpers
# =====================================================================

def test_is_valid_char():
    # Valid characters
    assert is_valid_char("a")
    assert is_valid_char("Z")
    assert is_valid_char("0")
    assert is_valid_char("9")
    assert is_valid_char("đ")
    assert is_valid_char("ế")
    assert is_valid_char("$")
    assert is_valid_char("€")
    assert is_valid_char("₫")
    assert is_valid_char(".")
    assert is_valid_char(",")
    assert is_valid_char("-")
    assert is_valid_char("–")
    assert is_valid_char("—")
    assert is_valid_char("%")

    # Invalid characters: unmapped glyphs, replacement, control codes
    assert not is_valid_char("\ufffd")
    assert not is_valid_char("\x00")
    assert not is_valid_char("\x01")
    assert not is_valid_char("\x1f")
    assert not is_valid_char(chr(0xE000))  # Private Use Area


def test_compute_valid_char_ratio():
    clean_text = "INVOICE # 12345 Date: 2026-08-01 Total: $1,250.00"
    assert compute_valid_char_ratio(clean_text) == 1.0

    # Empty string or whitespace only
    assert compute_valid_char_ratio("") == 0.0
    assert compute_valid_char_ratio("   \n\t  ") == 0.0

    # Garbage text with replacement characters
    noisy_text = "INV " + "\ufffd" * 90
    ratio = compute_valid_char_ratio(noisy_text)
    assert ratio < 0.10


# =====================================================================
# Unit tests for inspect_pdf_page
# =====================================================================

def test_inspect_pdf_page_clean_text():
    doc = fitz.open()
    invoice_text = (
        "ACME CORPORATION - INVOICE\n"
        "Invoice Number: INV-2026-9901\n"
        "Invoice Date: 2026-08-01\n"
        "Customer: Global Logistics Inc.\n"
        "Item 1: Storage Containers 100 EA @ $12.50 = $1,250.00\n"
        "Item 2: Packaging Pallets 20 EA @ $15.00 = $300.00\n"
        "Subtotal: $1,550.00\n"
        "Tax (10%): $155.00\n"
        "Total Amount Due: $1,705.00\n"
        "Payment Terms: Net 30 days. Thank you for your business!"
    )
    page = _create_synthetic_clean_page(doc, invoice_text)

    is_clean, result = inspect_pdf_page(page)
    assert is_clean is True
    assert isinstance(result, list)
    assert len(result) > 10

    for word in result:
        assert isinstance(word, Word)
        assert word.conf == 1.0
        assert word.source == "pdf_text"
        assert word.page == 1
        assert len(word.bbox) == 4
        assert word.bbox[0] <= word.bbox[2]
        assert word.bbox[1] <= word.bbox[3]


def test_inspect_pdf_page_insufficient_printable_chars():
    doc = fitz.open()
    # Less than MIN_PRINTABLE_CHARS (50)
    page = _create_synthetic_clean_page(doc, "Invoice #101 Page 1")

    is_clean, result = inspect_pdf_page(page)
    assert is_clean is False
    assert isinstance(result, np.ndarray)
    assert result.dtype == np.uint8
    assert len(result.shape) == 3
    assert result.shape[2] == 3  # RGB


def test_inspect_pdf_page_corrupted_text_layer():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # More than 50 characters, but 90% control characters
    corrupted_text = "INV " + "".join(chr(i) for i in range(1, 32)) * 3
    page.insert_text(fitz.Point(50, 50), corrupted_text)

    is_clean, result = inspect_pdf_page(page)
    assert is_clean is False
    assert isinstance(result, np.ndarray)


def test_inspect_pdf_page_scanned_background_image():
    doc = fitz.open()
    # Page with 90% background image and no text
    page = _create_synthetic_image_page(doc, area_ratio=0.90)

    is_clean, result = inspect_pdf_page(page)
    assert is_clean is False
    assert isinstance(result, np.ndarray)
    assert result.dtype == np.uint8
    assert result.shape[2] == 3


def test_inspect_pdf_page_text_with_large_background_image():
    doc = fitz.open()
    # Page with clean text BUT has 95% background image (e.g. scanned background with OCR stamp)
    page = _create_synthetic_image_page(doc, area_ratio=0.95)
    invoice_text = (
        "ACME CORPORATION INVOICE INV-2026-001 Date 2026-08-01 "
        "Total Amount Due $1,234.56 Item Description Line Item 1 Line Item 2 "
        "Customer Name Acme Supplies Payment Terms Net 30 Days."
    )
    page.insert_text(fitz.Point(50, 50), invoice_text)

    is_clean, result = inspect_pdf_page(page)
    # Must route to OCR because background image exceeds MAX_IMAGE_AREA_RATIO (0.80)
    assert is_clean is False
    assert isinstance(result, np.ndarray)


def test_inspect_pdf_page_small_logo_not_routing_to_ocr():
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Add small logo covering ~4% of page area
    img = Image.new("RGB", (60, 60), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    page.insert_image(fitz.Rect(50, 50, 150, 150), stream=buf.getvalue())

    invoice_text = (
        "ACME CORPORATION - INVOICE\n"
        "Invoice Number: INV-2026-9901\n"
        "Invoice Date: 2026-08-01\n"
        "Item 1: Premium Coffee Beans 10kg @ $25.00 = $250.00\n"
        "Item 2: Milk Cartons 50 PK @ $4.00 = $200.00\n"
        "Total Amount Due: $450.00\n"
    )
    page.insert_text(fitz.Point(50, 200), invoice_text)

    is_clean, result = inspect_pdf_page(page)
    assert is_clean is True
    assert isinstance(result, list)


def test_inspect_pdf_page_rotation():
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    page.set_rotation(90)
    invoice_text = (
        "ACME CORPORATION ROTATED INVOICE INV-2026-001\n"
        "Date: 2026-08-01 Total: $500.00 Terms: Net 30\n"
        "Description of goods supplied to customer headquarters"
    )
    page.insert_text(fitz.Point(50, 50), invoice_text)

    is_clean, result = inspect_pdf_page(page)
    assert is_clean is True
    assert isinstance(result, list)
    # Word bounding boxes should be inside page.rect (width=700, height=500 when rotated 90)
    for w in result:
        x0, y0, x1, y1 = w.bbox
        assert 0.0 <= x0 <= 700.0
        assert 0.0 <= y0 <= 500.0


def test_render_page_to_image_max_dimension():
    doc = fitz.open()
    # Large dimensions: 3000 x 3000 points
    page = doc.new_page(width=3000, height=3000)
    img = render_page_to_image(page, dpi=300, max_dimension=1000)
    assert max(img.shape[0], img.shape[1]) <= 1000


# =====================================================================
# Unit tests for deduplicate_headers_footers
# =====================================================================

def test_deduplicate_headers_footers_single_and_empty():
    assert deduplicate_headers_footers([]) == []

    p1 = Page(page_num=1, width=600, height=800, words=[
        Word("Acme", (50, 20, 100, 35), 1.0, 1, "pdf_text"),
    ])
    result = deduplicate_headers_footers([p1])
    assert len(result) == 1
    assert len(result[0].words) == 1


def test_deduplicate_headers_footers_multi_page():
    # Page 1: Header (y=20..35), Body (y=200..215), Footer (y=770..785)
    p1 = Page(page_num=1, width=600, height=800, words=[
        Word("Acme", (50, 20, 100, 35), 1.0, 1, "pdf_text"),
        Word("Corp", (110, 20, 160, 35), 1.0, 1, "pdf_text"),
        Word("Invoice", (170, 20, 240, 35), 1.0, 1, "pdf_text"),
        Word("Item1", (50, 200, 120, 215), 1.0, 1, "pdf_text"),
        Word("Page", (250, 770, 290, 785), 1.0, 1, "pdf_text"),
        Word("1", (295, 770, 305, 785), 1.0, 1, "pdf_text"),
        Word("of", (310, 770, 325, 785), 1.0, 1, "pdf_text"),
        Word("2", (330, 770, 340, 785), 1.0, 1, "pdf_text"),
    ])

    # Page 2: Repeated Header (y=20..35), Body (y=200..215), Repeated Footer (y=770..785)
    p2 = Page(page_num=2, width=600, height=800, words=[
        Word("Acme", (50, 20, 100, 35), 1.0, 2, "pdf_text"),
        Word("Corp", (110, 20, 160, 35), 1.0, 2, "pdf_text"),
        Word("Invoice", (170, 20, 240, 35), 1.0, 2, "pdf_text"),
        Word("Item2", (50, 200, 120, 215), 1.0, 2, "pdf_text"),
        Word("Page", (250, 770, 290, 785), 1.0, 2, "pdf_text"),
        Word("2", (295, 770, 305, 785), 1.0, 2, "pdf_text"),
        Word("of", (310, 770, 325, 785), 1.0, 2, "pdf_text"),
        Word("2", (330, 770, 340, 785), 1.0, 2, "pdf_text"),
    ])

    cleaned = deduplicate_headers_footers([p1, p2])
    assert len(cleaned) == 2

    # Page 1 keeps its header, body, and footer
    p1_texts = [w.text for w in cleaned[0].words]
    assert "Acme" in p1_texts
    assert "Corp" in p1_texts
    assert "Invoice" in p1_texts
    assert "Item1" in p1_texts
    assert "Page" in p1_texts

    # Page 2 has repeated header and repeated footer stripped
    p2_texts = [w.text for w in cleaned[1].words]
    assert "Acme" not in p2_texts
    assert "Corp" not in p2_texts
    assert "Invoice" not in p2_texts
    assert "Page" not in p2_texts
    assert "2" not in p2_texts
    # Body word Item2 MUST be retained
    assert p2_texts == ["Item2"]


def test_deduplicate_headers_footers_fuzzy_match():
    # Header on page 2 has slight punctuation difference "Acme Corp. Invoice"
    p1 = Page(page_num=1, width=600, height=800, words=[
        Word("Acme", (50, 20, 100, 35), 1.0, 1, "pdf_text"),
        Word("Corp", (110, 20, 160, 35), 1.0, 1, "pdf_text"),
        Word("Invoice", (170, 20, 240, 35), 1.0, 1, "pdf_text"),
        Word("Total", (50, 400, 100, 415), 1.0, 1, "pdf_text"),
    ])
    p2 = Page(page_num=2, width=600, height=800, words=[
        Word("Acme", (50, 20, 100, 35), 1.0, 2, "pdf_text"),
        Word("Corp.", (110, 20, 165, 35), 1.0, 2, "pdf_text"),
        Word("Invoice", (175, 20, 245, 35), 1.0, 2, "pdf_text"),
        Word("Subtotal", (50, 400, 120, 415), 1.0, 2, "pdf_text"),
    ])

    cleaned = deduplicate_headers_footers([p1, p2])
    p2_texts = [w.text for w in cleaned[1].words]
    assert "Subtotal" in p2_texts
    assert "Acme" not in p2_texts


# =====================================================================
# Unit tests for load_pdf_document (E2E ingestion)
# =====================================================================

def test_load_pdf_document_mixed(tmp_path: Path):
    """Test loading a synthetic PDF with clean text, scanned image, and corrupted text layer."""
    doc = fitz.open()

    # Page 1: Clean text page
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text(
        fitz.Point(50, 50),
        "VENDOR NAME: ACME FOOD SUPPLIES\n"
        "Invoice Number: INV-009182\n"
        "Date: 2026-08-01\n"
        "Item 1: Organic Olive Oil 500ML x 20 @ $12.00 = $240.00\n"
        "Item 2: Balsamic Vinegar 750ML x 10 @ $18.00 = $180.00\n"
        "Total: $420.00\n"
    )

    # Page 2: Scanned receipt (background image)
    p2 = doc.new_page(width=595, height=842)
    img = Image.new("RGB", (400, 600), color=(220, 220, 220))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    p2.insert_image(fitz.Rect(10, 10, 585, 832), stream=buf.getvalue())

    # Page 3: Corrupted text-layer page
    p3 = doc.new_page(width=595, height=842)
    p3.insert_text(fitz.Point(50, 50), "INV " + "".join(chr(i) for i in range(1, 32)) * 3)

    pdf_path = tmp_path / "mixed_invoice.pdf"
    doc.save(str(pdf_path))
    doc.close()

    expected_sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    parsed_doc, ocr_pages = load_pdf_document(pdf_path)

    # Document assertions
    assert isinstance(parsed_doc, Document)
    assert parsed_doc.file_path == str(pdf_path)
    assert parsed_doc.sha256 == expected_sha256
    assert len(parsed_doc.pages) == 3

    # Page 1 should have extracted words
    assert len(parsed_doc.pages[0].words) > 0
    assert all(w.source == "pdf_text" for w in parsed_doc.pages[0].words)
    assert all(w.conf == 1.0 for w in parsed_doc.pages[0].words)

    # Page 2 and 3 should have empty words awaiting OCR
    assert len(parsed_doc.pages[1].words) == 0
    assert len(parsed_doc.pages[2].words) == 0

    # OCR pages assertions
    assert len(ocr_pages) == 2
    page_num_1, img_1 = ocr_pages[0]
    page_num_2, img_2 = ocr_pages[1]

    assert page_num_1 == 2
    assert isinstance(img_1, np.ndarray)
    assert img_1.dtype == np.uint8
    assert img_1.shape[2] == 3

    assert page_num_2 == 3
    assert isinstance(img_2, np.ndarray)
    assert img_2.dtype == np.uint8
    assert img_2.shape[2] == 3


def test_load_pdf_document_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_pdf_document(Path("non_existent_invoice.pdf"))


def test_document_duck_typing(tmp_path: Path):
    doc = fitz.open()
    p1 = doc.new_page(width=500, height=700)
    p1.insert_text(fitz.Point(50, 50), "A" * 60)
    pdf_path = tmp_path / "single.pdf"
    doc.save(str(pdf_path))
    doc.close()

    parsed_doc, ocr_pages = load_pdf_document(pdf_path)
    # Test len, indexing, iteration
    assert len(parsed_doc) == 1  # type: ignore[arg-type]
    assert isinstance(parsed_doc[0], Page)  # type: ignore[index]
    assert len(list(parsed_doc)) == 1  # type: ignore[call-overload]
    assert len(parsed_doc.pages) == 1
    assert len(parsed_doc.all_words) > 0
