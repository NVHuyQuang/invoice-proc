"""Synthetic scan invoice fixture generator for test suite.

Generates deterministic synthetic scanned invoice PDFs and corresponding .truth.json files:
1. Pure scanned PDF (raster image embedded in PDF, no text layer).
2. PDF with garbage text layer (corrupted font mapping, <85% valid characters) to test routing to OCR.
3. Mixed PDF (Page 1 clean vector text layer, Page 2 raster scanned image).

STRICT INVARIANTS:
- All data is 100% synthetic. No real invoice data.
- Fixed seed (42) for deterministic, reproducible generation.
- Generates tests/fixtures/scan/*.pdf, *.truth.json, and truth.json.
"""

from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import random
import sys
from typing import Dict, Any, Tuple

from PIL import Image, ImageDraw, ImageFont
import pymupdf

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Category, SCHEMA_VERSION
from models.schema import (
    CanonicalInvoice,
    CanonicalLineItem,
    DocType,
    InvoiceStatus,
    LineItemKind,
)

FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "scan"


def get_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """Retrieve font deterministically across operating systems."""
    font_names = ["arialbd.ttf", "helveticab.ttf"] if bold else ["arial.ttf", "helvetica.ttf"]
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue
    return ImageFont.load_default(size=size)


def draw_text_right(
    draw: ImageDraw.ImageDraw,
    text: str,
    x_right: float,
    y: float,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int] = (20, 20, 20),
) -> None:
    """Draw right-aligned text."""
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    draw.text((x_right - width, y), text, font=font, fill=fill)


def draw_text_center(
    draw: ImageDraw.ImageDraw,
    text: str,
    x_center: float,
    y: float,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int] = (20, 20, 20),
) -> None:
    """Draw centered text."""
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    draw.text((x_center - width / 2, y), text, font=font, fill=fill)


# ---------------------------------------------------------------------------
# 1. Pure Scanned PDF Generator
# ---------------------------------------------------------------------------

def create_scan_image_pure() -> Image.Image:
    """Render a realistic scanned invoice image for Vortex Industrial Supply."""
    random.seed(42)
    width, height = 1240, 1754
    # Slight scanner warm paper tone
    img = Image.new("RGB", (width, height), (252, 252, 250))
    draw = ImageDraw.Draw(img)

    f_title = get_font(32, bold=True)
    f_sub = get_font(18, bold=False)
    f_h2 = get_font(24, bold=True)
    f_tbl_hdr = get_font(18, bold=True)
    f_body = get_font(18, bold=False)
    f_bold = get_font(19, bold=True)

    # Subtle paper border / margin guide
    draw.rectangle([40, 40, width - 40, height - 40], outline=(235, 235, 230), width=1)

    # Vendor Header
    draw.text((70, 70), "VORTEX INDUSTRIAL SUPPLY CO.", font=f_title, fill=(25, 30, 45))
    draw.text((70, 115), "1420 Market Street, Suite 400", font=f_sub, fill=(80, 85, 95))
    draw.text((70, 140), "Philadelphia, PA 19102 | Tel: (215) 555-0194", font=f_sub, fill=(80, 85, 95))
    draw.text((70, 165), "billing@vortexsupply.example.com", font=f_sub, fill=(80, 85, 95))

    # Invoice Header Box (Top Right)
    draw_text_right(draw, "INVOICE", width - 70, 65, f_h2, fill=(25, 30, 45))
    draw_text_right(draw, "Invoice #: INV-SCAN-7801", width - 70, 110, f_bold, fill=(30, 30, 30))
    draw_text_right(draw, "Date: 2026-08-12", width - 70, 140, f_body, fill=(60, 60, 60))
    draw_text_right(draw, "Due Date: 2026-09-11", width - 70, 165, f_body, fill=(60, 60, 60))

    # Divider
    draw.line([(70, 210), (width - 70, 210)], fill=(200, 205, 215), width=2)

    # Bill To / Ship To
    draw.text((70, 235), "BILL TO:", font=f_tbl_hdr, fill=(50, 55, 70))
    draw.text((70, 265), "Metro Manufacturing LLC", font=f_bold, fill=(30, 30, 30))
    draw.text((70, 295), "500 Industrial Parkway", font=f_body, fill=(60, 60, 60))
    draw.text((70, 320), "Allentown, PA 18109", font=f_body, fill=(60, 60, 60))

    draw.text((650, 235), "SHIP TO:", font=f_tbl_hdr, fill=(50, 55, 70))
    draw.text((650, 265), "Metro Manufacturing - Dock 4", font=f_body, fill=(60, 60, 60))
    draw.text((650, 295), "500 Industrial Parkway", font=f_body, fill=(60, 60, 60))
    draw.text((650, 320), "Allentown, PA 18109", font=f_body, fill=(60, 60, 60))

    # Table Header
    y_tbl = 390
    draw.rectangle([70, y_tbl, width - 70, y_tbl + 40], fill=(238, 240, 244))
    draw.text((85, y_tbl + 10), "Item Description", font=f_tbl_hdr, fill=(40, 45, 60))
    draw_text_right(draw, "Qty", 690, y_tbl + 10, f_tbl_hdr, fill=(40, 45, 60))
    draw_text_center(draw, "Unit", 770, y_tbl + 10, f_tbl_hdr, fill=(40, 45, 60))
    draw_text_right(draw, "Unit Price", 930, y_tbl + 10, f_tbl_hdr, fill=(40, 45, 60))
    draw_text_right(draw, "Line Total", width - 85, y_tbl + 10, f_tbl_hdr, fill=(40, 45, 60))

    items = [
        ("Heavy Duty Nitrile Gloves (Box of 100)", "5", "BOX", "14.50", "72.50"),
        ("Industrial Degreaser Cleaner 1 Gal", "2", "GAL", "28.00", "56.00"),
        ("Microfiber Shop Towels (Pack of 12)", "4", "PK", "12.25", "49.00"),
    ]

    y = y_tbl + 50
    for desc, qty, unit, price, total in items:
        draw.text((85, y + 8), desc, font=f_body, fill=(25, 25, 25))
        draw_text_right(draw, qty, 690, y + 8, f_body, fill=(25, 25, 25))
        draw_text_center(draw, unit, 770, y + 8, f_body, fill=(25, 25, 25))
        draw_text_right(draw, f"${price}", 930, y + 8, f_body, fill=(25, 25, 25))
        draw_text_right(draw, f"${total}", width - 85, y + 8, f_body, fill=(25, 25, 25))
        draw.line([(70, y + 42), (width - 70, y + 42)], fill=(230, 232, 238), width=1)
        y += 48

    # Summary Section (Right Side)
    y_sum = y + 40
    summary_lines = [
        ("Subtotal:", "$177.50", False),
        ("Sales Tax (8.0%):", "$14.20", False),
        ("Shipping & Handling:", "$15.00", False),
        ("Grand Total:", "$206.70", True),
        ("Amount Due:", "$206.70", True),
    ]

    for label, val, is_bld in summary_lines:
        font_to_use = f_bold if is_bld else f_body
        color_to_use = (20, 20, 20) if is_bld else (70, 75, 85)
        if is_bld and label == "Grand Total:":
            draw.line([(680, y_sum - 5), (width - 70, y_sum - 5)], fill=(180, 185, 195), width=2)
        draw.text((700, y_sum), label, font=font_to_use, fill=color_to_use)
        draw_text_right(draw, val, width - 85, y_sum, font_to_use, fill=(20, 20, 20))
        y_sum += 36

    # Footer Notes
    draw.line([(70, height - 180), (width - 70, height - 180)], fill=(220, 222, 228), width=1)
    draw.text((70, height - 150), "Payment Terms: Net 30 Days.", font=f_bold, fill=(60, 65, 75))
    draw.text((70, height - 120), "Thank you for your business. Remit electronic ACH payments to Vortex Industrial Supply Co.", font=f_sub, fill=(90, 95, 105))

    return img


def build_pure_scan_fixture() -> Tuple[bytes, CanonicalInvoice]:
    """Build pure scanned PDF with zero text layer and return bytes + truth."""
    img = create_scan_image_pure()
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_bytes = img_byte_arr.getvalue()

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    # Insert image covering 100% of the page
    page.insert_image(page.rect, stream=img_bytes)

    doc.set_metadata({
        "creationDate": "D:20260812000000Z",
        "modDate": "D:20260812000000Z",
        "producer": "PyMuPDF Synthetic Generator",
        "title": "Invoice INV-SCAN-7801",
    })

    pdf_bytes = doc.tobytes(deflate=True, reproducible=True, no_new_id=1)
    doc.close()

    source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    truth = CanonicalInvoice(
        source_file="scan_pure.pdf",
        source_sha256=source_sha256,
        status=InvoiceStatus.VERIFIED,
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="VORTEX INDUSTRIAL SUPPLY CO.",
        invoice_no="INV-SCAN-7801",
        invoice_date="2026-08-12",
        due_date="2026-09-11",
        currency="USD",
        category=Category.OTHER,
        line_items=[
            CanonicalLineItem(
                item_name="Heavy Duty Nitrile Gloves (Box of 100)",
                qty=Decimal("5"),
                unit_price=Decimal("14.50"),
                line_total=Decimal("72.50"),
                unit="BOX",
                kind=LineItemKind.GOODS,
            ),
            CanonicalLineItem(
                item_name="Industrial Degreaser Cleaner 1 Gal",
                qty=Decimal("2"),
                unit_price=Decimal("28.00"),
                line_total=Decimal("56.00"),
                unit="GAL",
                kind=LineItemKind.GOODS,
            ),
            CanonicalLineItem(
                item_name="Microfiber Shop Towels (Pack of 12)",
                qty=Decimal("4"),
                unit_price=Decimal("12.25"),
                line_total=Decimal("49.00"),
                unit="PK",
                kind=LineItemKind.GOODS,
            ),
        ],
        subtotal=Decimal("177.50"),
        tax=Decimal("14.20"),
        shipping=Decimal("15.00"),
        grand_total=Decimal("206.70"),
        amount_due=Decimal("206.70"),
        schema_version=SCHEMA_VERSION,
    )
    return pdf_bytes, truth


# ---------------------------------------------------------------------------
# 2. Garbage Text Layer PDF Generator (<85% valid characters)
# ---------------------------------------------------------------------------

def create_scan_image_garbage_text() -> Image.Image:
    """Render scanned invoice image for Blue Ridge Kitchenware Supply."""
    random.seed(42)
    width, height = 1240, 1754
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    f_title = get_font(32, bold=True)
    f_sub = get_font(18, bold=False)
    f_h2 = get_font(24, bold=True)
    f_tbl_hdr = get_font(18, bold=True)
    f_body = get_font(18, bold=False)
    f_bold = get_font(19, bold=True)

    draw.rectangle([30, 30, width - 30, height - 30], outline=(230, 230, 230), width=1)

    # Vendor Header
    draw.text((70, 70), "BLUE RIDGE KITCHENWARE SUPPLY", font=f_title, fill=(20, 35, 60))
    draw.text((70, 115), "880 Warehouse Blvd, Atlanta, GA 30318", font=f_sub, fill=(80, 80, 80))
    draw.text((70, 140), "Phone: (404) 555-0147 | contact@blueridgekitchen.example.com", font=f_sub, fill=(80, 80, 80))

    # Invoice Header Box
    draw_text_right(draw, "INVOICE", width - 70, 65, f_h2, fill=(20, 35, 60))
    draw_text_right(draw, "Invoice #: INV-SCAN-8820", width - 70, 110, f_bold, fill=(30, 30, 30))
    draw_text_right(draw, "Date: 2026-08-18", width - 70, 140, f_body, fill=(60, 60, 60))
    draw_text_right(draw, "Due Date: 2026-09-17", width - 70, 165, f_body, fill=(60, 60, 60))

    draw.line([(70, 210), (width - 70, 210)], fill=(190, 195, 205), width=2)

    # Bill To
    draw.text((70, 235), "CUSTOMER BILL TO:", font=f_tbl_hdr, fill=(50, 55, 70))
    draw.text((70, 265), "Southern Bistro & Bar", font=f_bold, fill=(30, 30, 30))
    draw.text((70, 295), "120 Piedmont Ave NE", font=f_body, fill=(60, 60, 60))
    draw.text((70, 320), "Atlanta, GA 30303", font=f_body, fill=(60, 60, 60))

    # Table Header
    y_tbl = 380
    draw.rectangle([70, y_tbl, width - 70, y_tbl + 40], fill=(235, 240, 248))
    draw.text((85, y_tbl + 10), "Item Description", font=f_tbl_hdr, fill=(30, 40, 60))
    draw_text_right(draw, "Qty", 690, y_tbl + 10, f_tbl_hdr, fill=(30, 40, 60))
    draw_text_center(draw, "Unit", 770, y_tbl + 10, f_tbl_hdr, fill=(30, 40, 60))
    draw_text_right(draw, "Unit Price", 930, y_tbl + 10, f_tbl_hdr, fill=(30, 40, 60))
    draw_text_right(draw, "Line Total", width - 85, y_tbl + 10, f_tbl_hdr, fill=(30, 40, 60))

    items = [
        ("Stainless Steel Food Pans 1/2 Size", "6", "EA", "18.50", "111.00"),
        ("Silicone Baking Mats 16x24", "10", "PK", "9.20", "92.00"),
        ("Commercial Cutting Boards White", "3", "EA", "25.00", "75.00"),
    ]

    y = y_tbl + 50
    for desc, qty, unit, price, total in items:
        draw.text((85, y + 8), desc, font=f_body, fill=(25, 25, 25))
        draw_text_right(draw, qty, 690, y + 8, f_body, fill=(25, 25, 25))
        draw_text_center(draw, unit, 770, y + 8, f_body, fill=(25, 25, 25))
        draw_text_right(draw, f"${price}", 930, y + 8, f_body, fill=(25, 25, 25))
        draw_text_right(draw, f"${total}", width - 85, y + 8, f_body, fill=(25, 25, 25))
        draw.line([(70, y + 42), (width - 70, y + 42)], fill=(230, 232, 238), width=1)
        y += 48

    # Summary
    y_sum = y + 40
    summary_lines = [
        ("Subtotal:", "$278.00", False),
        ("Sales Tax (8.0%):", "$22.24", False),
        ("Volume Discount:", "-$10.00", False),
        ("Grand Total:", "$290.24", True),
        ("Amount Due:", "$290.24", True),
    ]

    for label, val, is_bld in summary_lines:
        font_to_use = f_bold if is_bld else f_body
        color_to_use = (20, 20, 20) if is_bld else (70, 75, 85)
        if is_bld and label == "Grand Total:":
            draw.line([(680, y_sum - 5), (width - 70, y_sum - 5)], fill=(180, 185, 195), width=2)
        draw.text((700, y_sum), label, font=font_to_use, fill=color_to_use)
        draw_text_right(draw, val, width - 85, y_sum, font_to_use, fill=(20, 20, 20))
        y_sum += 36

    # Footer
    draw.line([(70, height - 160), (width - 70, height - 160)], fill=(220, 222, 228), width=1)
    draw.text((70, height - 130), "Thank you for partnering with Blue Ridge Kitchenware Supply.", font=f_sub, fill=(90, 95, 105))

    return img


def build_garbage_text_fixture() -> Tuple[bytes, CanonicalInvoice]:
    """Build PDF with corrupt text layer (<85% valid characters) to trigger OCR routing."""
    img = create_scan_image_garbage_text()
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_bytes = img_byte_arr.getvalue()

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)

    # Insert background image covering ~76% of page area (<= 80% threshold in PLAN 1.3 condition 3)
    # Page area = 595 * 842 = 500,990.
    # Image rect: (40, 50, 555, 792) -> width 515, height 742 -> area 382,130 (76.27%)
    # This guarantees condition 3 PASSES so condition 2 (valid char ratio < 0.85) is the sole trigger!
    image_rect = pymupdf.Rect(40, 50, 555, 792)
    page.insert_image(image_rect, stream=img_bytes)

    # Insert corrupted text layer via render_mode=3 (invisible text layer)
    # Condition 1 requires printable char count >= 50
    # Condition 2 requires valid char ratio < 0.85
    # Valid characters: 18 chars ("INV-8820 TOTAL 290")
    # Invalid characters: 130 non-alphanumeric / unmapped symbols (middle dots '\u00b7')
    # Total printable: 148 >= 50. Valid ratio: 18 / 148 = 12.16% << 85%.
    valid_part_1 = "INV-8820 "
    corrupt_block_1 = "\u00b7" * 70
    valid_part_2 = " TOTAL 290 "
    corrupt_block_2 = "\u00b7" * 60

    garbage_text = f"{valid_part_1}{corrupt_block_1}{valid_part_2}{corrupt_block_2}"
    page.insert_text((50, 80), garbage_text, render_mode=3)

    doc.set_metadata({
        "creationDate": "D:20260818000000Z",
        "modDate": "D:20260818000000Z",
        "producer": "PyMuPDF Synthetic Generator",
        "title": "Invoice INV-SCAN-8820",
    })

    pdf_bytes = doc.tobytes(deflate=True, reproducible=True, no_new_id=1)
    doc.close()

    source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    truth = CanonicalInvoice(
        source_file="scan_garbage_text.pdf",
        source_sha256=source_sha256,
        status=InvoiceStatus.VERIFIED,
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="BLUE RIDGE KITCHENWARE SUPPLY",
        invoice_no="INV-SCAN-8820",
        invoice_date="2026-08-18",
        due_date="2026-09-17",
        currency="USD",
        category=Category.PACKAGING,
        line_items=[
            CanonicalLineItem(
                item_name="Stainless Steel Food Pans 1/2 Size",
                qty=Decimal("6"),
                unit_price=Decimal("18.50"),
                line_total=Decimal("111.00"),
                unit="EA",
                kind=LineItemKind.GOODS,
            ),
            CanonicalLineItem(
                item_name="Silicone Baking Mats 16x24",
                qty=Decimal("10"),
                unit_price=Decimal("9.20"),
                line_total=Decimal("92.00"),
                unit="PK",
                kind=LineItemKind.GOODS,
            ),
            CanonicalLineItem(
                item_name="Commercial Cutting Boards White",
                qty=Decimal("3"),
                unit_price=Decimal("25.00"),
                line_total=Decimal("75.00"),
                unit="EA",
                kind=LineItemKind.GOODS,
            ),
        ],
        subtotal=Decimal("278.00"),
        tax=Decimal("22.24"),
        discount=Decimal("10.00"),
        grand_total=Decimal("290.24"),
        amount_due=Decimal("290.24"),
        schema_version=SCHEMA_VERSION,
    )
    return pdf_bytes, truth


# ---------------------------------------------------------------------------
# 3. Mixed Multi-Page PDF Generator (Page 1 clean text layer, Page 2 scanned image)
# ---------------------------------------------------------------------------

def create_scan_image_mixed_page2() -> Image.Image:
    """Render scanned image for Page 2 of Greenfield Produce (Items 4-5 + Summary + Signature)."""
    random.seed(42)
    width, height = 1240, 1754
    # Scanned paper background with slight warm tone
    img = Image.new("RGB", (width, height), (250, 250, 248))
    draw = ImageDraw.Draw(img)

    f_title = get_font(28, bold=True)
    f_sub = get_font(18, bold=False)
    f_tbl_hdr = get_font(18, bold=True)
    f_body = get_font(18, bold=False)
    f_bold = get_font(19, bold=True)

    draw.rectangle([40, 40, width - 40, height - 40], outline=(230, 230, 225), width=1)

    # Header continuing from Page 1
    draw.text((70, 70), "GREENFIELD PRODUCE & FARM DIRECT", font=f_title, fill=(25, 55, 30))
    draw.text((70, 115), "INVOICE CONTINUATION & SIGNED BILL OF LADING", font=f_sub, fill=(70, 75, 70))
    draw_text_right(draw, "Invoice #: INV-SCAN-9045 (Page 2 of 2)", width - 70, 70, f_bold, fill=(30, 30, 30))
    draw_text_right(draw, "Delivery Date: 2026-08-22", width - 70, 105, f_body, fill=(60, 60, 60))

    draw.line([(70, 160), (width - 70, 160)], fill=(190, 200, 190), width=2)

    # Sub-heading
    draw.text((70, 190), "DELIVERED ITEMS - BATCH B (Roots & Staples):", font=f_tbl_hdr, fill=(40, 60, 40))

    # Table Header
    y_tbl = 240
    draw.rectangle([70, y_tbl, width - 70, y_tbl + 40], fill=(235, 242, 235))
    draw.text((85, y_tbl + 10), "Item Description", font=f_tbl_hdr, fill=(30, 50, 30))
    draw_text_right(draw, "Qty", 690, y_tbl + 10, f_tbl_hdr, fill=(30, 50, 30))
    draw_text_center(draw, "Unit", 770, y_tbl + 10, f_tbl_hdr, fill=(30, 50, 30))
    draw_text_right(draw, "Unit Price", 930, y_tbl + 10, f_tbl_hdr, fill=(30, 50, 30))
    draw_text_right(draw, "Line Total", width - 85, y_tbl + 10, f_tbl_hdr, fill=(30, 50, 30))

    items = [
        ("Yellow Onions (50 lb bag)", "3", "BAG", "21.00", "63.00"),
        ("Russet Potatoes (50 lb bag)", "4", "BAG", "24.50", "98.00"),
    ]

    y = y_tbl + 50
    for desc, qty, unit, price, total in items:
        draw.text((85, y + 8), desc, font=f_body, fill=(25, 25, 25))
        draw_text_right(draw, qty, 690, y + 8, f_body, fill=(25, 25, 25))
        draw_text_center(draw, unit, 770, y + 8, f_body, fill=(25, 25, 25))
        draw_text_right(draw, f"${price}", 930, y + 8, f_body, fill=(25, 25, 25))
        draw_text_right(draw, f"${total}", width - 85, y + 8, f_body, fill=(25, 25, 25))
        draw.line([(70, y + 42), (width - 70, y + 42)], fill=(230, 235, 230), width=1)
        y += 48

    # Summary Section (Combined Page 1 + Page 2)
    y_sum = y + 50
    draw.rectangle([650, y_sum - 15, width - 70, y_sum + 200], outline=(200, 210, 200), width=1, fill=(248, 250, 248))

    summary_lines = [
        ("Subtotal (All Items):", "$563.00", False),
        ("Sales Tax (Raw Produce Exempt):", "$0.00", False),
        ("Refrigerated Freight Delivery:", "$25.00", False),
        ("Grand Total:", "$588.00", True),
        ("Amount Due:", "$588.00", True),
    ]

    curr_y = y_sum
    for label, val, is_bld in summary_lines:
        font_to_use = f_bold if is_bld else f_body
        color_to_use = (20, 20, 20) if is_bld else (70, 75, 70)
        if is_bld and label == "Grand Total:":
            draw.line([(670, curr_y - 5), (width - 85, curr_y - 5)], fill=(160, 180, 160), width=2)
        draw.text((670, curr_y), label, font=font_to_use, fill=color_to_use)
        draw_text_right(draw, val, width - 85, curr_y, font_to_use, fill=(20, 20, 20))
        curr_y += 36

    # Receiving & Signature Stamp (Authentic scanned appearance)
    y_sig = y_sum + 260
    draw.rectangle([70, y_sig, 550, y_sig + 150], outline=(50, 80, 140), width=2)
    draw.text((85, y_sig + 15), "DELIVERY RECEIPT & INSPECTION ACCEPTANCE", font=get_font(15, bold=True), fill=(40, 70, 130))
    draw.text((85, y_sig + 45), "Received 5 of 5 lines in good condition.", font=f_body, fill=(30, 30, 30))
    draw.text((85, y_sig + 80), "Inspector: Marcus Vance (Culinary Logistics)", font=f_bold, fill=(20, 20, 20))
    draw.text((85, y_sig + 110), "Signature Date: 2026-08-22 07:45 AM", font=f_sub, fill=(80, 80, 80))

    return img


def build_mixed_pages_fixture() -> Tuple[bytes, CanonicalInvoice]:
    """Build multi-page PDF: Page 1 clean text layer, Page 2 raster scanned image."""
    doc = pymupdf.open()

    # ------------------ PAGE 1: Clean Vector Text Layer ------------------
    page1 = doc.new_page(width=595, height=842)
    # No background image on page 1 (image area ratio = 0.0 <= 0.80)

    # Insert vector text directly
    page1.insert_text((50, 60), "GREENFIELD PRODUCE & FARM DIRECT", fontsize=15, fontname="helv", color=(0.1, 0.25, 0.1))
    page1.insert_text((50, 80), "504 Harvest Lane, Salinas, CA 93901 | Phone: (831) 555-0182", fontsize=9, fontname="helv", color=(0.3, 0.3, 0.3))
    page1.insert_text((50, 95), "sales@greenfieldproduce.example.com", fontsize=9, fontname="helv", color=(0.3, 0.3, 0.3))

    page1.insert_text((420, 60), "INVOICE", fontsize=15, fontname="helv", color=(0.1, 0.25, 0.1))
    page1.insert_text((420, 80), "Invoice #: INV-SCAN-9045", fontsize=9, fontname="helv", color=(0.1, 0.1, 0.1))
    page1.insert_text((420, 95), "Date: 2026-08-22", fontsize=9, fontname="helv", color=(0.2, 0.2, 0.2))
    page1.insert_text((420, 110), "Due Date: 2026-09-21", fontsize=9, fontname="helv", color=(0.2, 0.2, 0.2))
    page1.insert_text((420, 125), "Page: 1 of 2", fontsize=9, fontname="helv", color=(0.4, 0.4, 0.4))

    page1.draw_line(pymupdf.Point(50, 140), pymupdf.Point(545, 140), color=(0.7, 0.75, 0.7), width=1.5)

    page1.insert_text((50, 165), "BILL TO:", fontsize=10, fontname="helv", color=(0.2, 0.3, 0.2))
    page1.insert_text((50, 182), "Golden Gate Culinary Services", fontsize=10, fontname="helv", color=(0.1, 0.1, 0.1))
    page1.insert_text((50, 198), "789 Folsom St, San Francisco, CA 94107", fontsize=9, fontname="helv", color=(0.3, 0.3, 0.3))

    page1.insert_text((50, 235), "DELIVERED ITEMS - BATCH A (Produce):", fontsize=10, fontname="helv", color=(0.15, 0.3, 0.15))

    # Table Header
    page1.draw_rect(pymupdf.Rect(50, 250, 545, 272), color=(0.85, 0.9, 0.85), fill=(0.92, 0.95, 0.92))
    page1.insert_text((58, 265), "Item Description", fontsize=9, fontname="helv", color=(0.15, 0.25, 0.15))
    page1.insert_text((330, 265), "Qty", fontsize=9, fontname="helv", color=(0.15, 0.25, 0.15))
    page1.insert_text((375, 265), "Unit", fontsize=9, fontname="helv", color=(0.15, 0.25, 0.15))
    page1.insert_text((425, 265), "Unit Price", fontsize=9, fontname="helv", color=(0.15, 0.25, 0.15))
    page1.insert_text((495, 265), "Line Total", fontsize=9, fontname="helv", color=(0.15, 0.25, 0.15))

    p1_items = [
        ("Organic Hass Avocados (Case of 48)", "4", "CS", "$42.00", "$168.00"),
        ("Fresh Roma Tomatoes (25 lb box)", "6", "BOX", "$26.50", "$159.00"),
        ("Organic Baby Spinach (4 lb tub)", "5", "TUB", "$15.00", "$75.00"),
    ]

    y_pos = 290
    for desc, qty, unit, price, total in p1_items:
        page1.insert_text((58, y_pos), desc, fontsize=9, fontname="helv", color=(0.1, 0.1, 0.1))
        page1.insert_text((335, y_pos), qty, fontsize=9, fontname="helv", color=(0.1, 0.1, 0.1))
        page1.insert_text((378, y_pos), unit, fontsize=9, fontname="helv", color=(0.1, 0.1, 0.1))
        page1.insert_text((430, y_pos), price, fontsize=9, fontname="helv", color=(0.1, 0.1, 0.1))
        page1.insert_text((495, y_pos), total, fontsize=9, fontname="helv", color=(0.1, 0.1, 0.1))
        page1.draw_line(pymupdf.Point(50, y_pos + 8), pymupdf.Point(545, y_pos + 8), color=(0.9, 0.9, 0.9), width=0.5)
        y_pos += 26

    page1.insert_text(
        (50, 420),
        "Batch B items and invoice totals continued on Page 2 (Signed Bill of Lading attached)...",
        fontsize=9,
        fontname="helv",
        color=(0.4, 0.4, 0.4),
    )

    # ------------------ PAGE 2: Scanned Raster Image ------------------
    page2 = doc.new_page(width=595, height=842)
    img_p2 = create_scan_image_mixed_page2()
    p2_byte_arr = io.BytesIO()
    img_p2.save(p2_byte_arr, format="PNG")
    page2.insert_image(page2.rect, stream=p2_byte_arr.getvalue())
    # No text layer added to page 2 (fails condition 1: 0 chars < 50; image area ratio = 1.0 > 0.80)

    doc.set_metadata({
        "creationDate": "D:20260822000000Z",
        "modDate": "D:20260822000000Z",
        "producer": "PyMuPDF Synthetic Generator",
        "title": "Invoice INV-SCAN-9045",
    })

    pdf_bytes = doc.tobytes(deflate=True, reproducible=True, no_new_id=1)
    doc.close()

    source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    truth = CanonicalInvoice(
        source_file="scan_mixed_pages.pdf",
        source_sha256=source_sha256,
        status=InvoiceStatus.VERIFIED,
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="GREENFIELD PRODUCE & FARM DIRECT",
        invoice_no="INV-SCAN-9045",
        invoice_date="2026-08-22",
        due_date="2026-09-21",
        currency="USD",
        category=Category.FOOD_INGREDIENTS,
        line_items=[
            CanonicalLineItem(
                item_name="Organic Hass Avocados (Case of 48)",
                qty=Decimal("4"),
                unit_price=Decimal("42.00"),
                line_total=Decimal("168.00"),
                unit="CS",
                kind=LineItemKind.GOODS,
            ),
            CanonicalLineItem(
                item_name="Fresh Roma Tomatoes (25 lb box)",
                qty=Decimal("6"),
                unit_price=Decimal("26.50"),
                line_total=Decimal("159.00"),
                unit="BOX",
                kind=LineItemKind.GOODS,
            ),
            CanonicalLineItem(
                item_name="Organic Baby Spinach (4 lb tub)",
                qty=Decimal("5"),
                unit_price=Decimal("15.00"),
                line_total=Decimal("75.00"),
                unit="TUB",
                kind=LineItemKind.GOODS,
            ),
            CanonicalLineItem(
                item_name="Yellow Onions (50 lb bag)",
                qty=Decimal("3"),
                unit_price=Decimal("21.00"),
                line_total=Decimal("63.00"),
                unit="BAG",
                kind=LineItemKind.GOODS,
            ),
            CanonicalLineItem(
                item_name="Russet Potatoes (50 lb bag)",
                qty=Decimal("4"),
                unit_price=Decimal("24.50"),
                line_total=Decimal("98.00"),
                unit="BAG",
                kind=LineItemKind.GOODS,
            ),
        ],
        subtotal=Decimal("563.00"),
        tax=Decimal("0.00"),
        shipping=Decimal("25.00"),
        grand_total=Decimal("588.00"),
        amount_due=Decimal("588.00"),
        schema_version=SCHEMA_VERSION,
    )
    return pdf_bytes, truth


# ---------------------------------------------------------------------------
# Verification Helpers
# ---------------------------------------------------------------------------

def inspect_fixture_dual_routing(pdf_bytes: bytes, filename: str) -> None:
    """Simulate PLAN 1.3 dual routing conditions to verify fixture properties."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    print(f"\nVerifying {filename}: {len(doc)} page(s)")

    for page_idx, page in enumerate(doc):
        text = page.get_text()
        words = page.get_text("words")
        printable_chars = [c for c in text if c.isprintable() and not c.isspace()]
        valid_chars = [
            c for c in printable_chars
            if c.isalnum() or c in ".,:;/-$%#@!&()[]{}\"'*+=?|><"
        ]

        char_count = len(printable_chars)
        valid_ratio = len(valid_chars) / char_count if char_count > 0 else 0.0

        # Image area ratio
        page_area = page.rect.width * page.rect.height
        image_info = page.get_image_info(xrefs=True)
        img_area = 0.0
        for info in image_info:
            b = info["bbox"]
            img_area += (b[2] - b[0]) * (b[3] - b[1])
        img_area_ratio = img_area / page_area if page_area > 0 else 0.0

        cond1 = char_count >= 50
        cond2 = valid_ratio >= 0.85
        cond3 = img_area_ratio <= 0.80
        is_clean_text = cond1 and cond2 and cond3

        print(
            f"  Page {page_idx + 1}: chars={char_count} (>=50: {cond1}), "
            f"valid_ratio={valid_ratio:.2f} (>=0.85: {cond2}), "
            f"img_ratio={img_area_ratio:.2f} (<=0.80: {cond3}) -> "
            f"{'CLEAN_TEXT (extract words)' if is_clean_text else 'NEEDS_OCR (render 300 DPI)'}"
        )
    doc.close()


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

def generate_all_fixtures() -> Dict[str, Any]:
    """Generate all synthetic scan fixtures and truth files."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    fixtures = [
        ("scan_pure.pdf", build_pure_scan_fixture),
        ("scan_garbage_text.pdf", build_garbage_text_fixture),
        ("scan_mixed_pages.pdf", build_mixed_pages_fixture),
    ]

    all_truths: Dict[str, Any] = {}

    for filename, builder_fn in fixtures:
        pdf_bytes, truth_obj = builder_fn()

        pdf_path = FIXTURES_DIR / filename
        pdf_path.write_bytes(pdf_bytes)

        truth_dict = truth_obj.to_jsonl_dict()
        truth_path = FIXTURES_DIR / f"{Path(filename).stem}.truth.json"
        with open(truth_path, "w", encoding="utf-8") as f:
            json.dump(truth_dict, f, indent=2, ensure_ascii=False)

        all_truths[filename] = truth_dict
        inspect_fixture_dual_routing(pdf_bytes, filename)

    # Consolidated truth.json
    consolidated_path = FIXTURES_DIR / "truth.json"
    with open(consolidated_path, "w", encoding="utf-8") as f:
        json.dump(all_truths, f, indent=2, ensure_ascii=False)

    print(f"\nSuccessfully generated {len(fixtures)} fixtures in {FIXTURES_DIR}")
    print(f"Consolidated truth saved to: {consolidated_path}")
    return all_truths


if __name__ == "__main__":
    generate_all_fixtures()
