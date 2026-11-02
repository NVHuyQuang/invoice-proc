"""Synthetic PDF text fixtures generator and test suite.

Creates deterministic synthetic invoices in tests/fixtures/pdf/ with matching .truth.json:
1. Multi-page goods invoice (ACME Test Foods Inc.)
2. Utility bill (Fake Power & Gas Utility Co.)
3. Credit memo with negative values (Fake Returns Inc.)
4. Weighed produce with fractional quantities (Fake Produce Market Co.)
5. Discounted invoice with negative discount line (Fake Tech Supplies Ltd.)
6. Multi-tax invoice with state & city tax lines (Fake NYC Restaurant Depot)

INVARIANTS:
1. No real invoice data; synthetic fake vendors only.
2. Deterministic: fixed seed, normalized PDF trailer IDs.
3. Clean text layer: valid char ratio >= 0.85, printable char count >= 50.
4. Exact mathematical consistency across line items, subtotals, and totals.
"""

import io
import json
import os
import re
import sys
import hashlib
from decimal import Decimal
from pathlib import Path
from typing import List, Dict, Any, Optional

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pymupdf

from config import Category, SCHEMA_VERSION
from models.schema import (
    CanonicalInvoice,
    CanonicalLineItem,
    CanonicalCharge,
    DocType,
    LineItemKind,
    InvoiceStatus,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "pdf"


def _normalize_pdf_bytes(pdf_bytes: bytes) -> bytes:
    """Normalize PDF binary to ensure deterministic sha256 across runs.

    Replaces random PDF trailer ID tokens with fixed zero hashes.
    """
    pattern = rb"/ID\s*\[\s*<[0-9a-zA-Z]+>\s*<[0-9a-zA-Z]+>\s*\]"
    replacement = b"/ID [<00000000000000000000000000000000> <00000000000000000000000000000000>]"
    return re.sub(pattern, replacement, pdf_bytes)


def _draw_page_header(
    page: pymupdf.Page,
    vendor_name: str,
    vendor_lines: List[str],
    doc_title: str,
    meta_pairs: List[tuple],
    bill_to_lines: List[str],
):
    """Draw header banner, vendor info, document title, and invoice metadata."""
    # Top rule
    page.draw_rect(pymupdf.Rect(40, 40, 572, 44), color=(0.15, 0.25, 0.45), fill=(0.15, 0.25, 0.45))

    # Vendor Name
    page.insert_text(pymupdf.Point(40, 68), vendor_name, fontsize=15, fontname="helv", fontfile=None)
    y_v = 82
    for vl in vendor_lines:
        page.insert_text(pymupdf.Point(40, y_v), vl, fontsize=8.5, fontname="helv")
        y_v += 12

    # Doc Title
    page.insert_text(pymupdf.Point(410, 68), doc_title, fontsize=16, fontname="helv")

    # Meta box (right side)
    y_m = 84
    for label, val in meta_pairs:
        page.insert_text(pymupdf.Point(380, y_m), f"{label}:", fontsize=9, fontname="helv")
        page.insert_text(pymupdf.Point(470, y_m), str(val), fontsize=9, fontname="helv")
        y_m += 13

    # Bill To Box
    y_b = max(y_v, y_m) + 8
    page.draw_rect(pymupdf.Rect(40, y_b, 300, y_b + 54), color=(0.85, 0.85, 0.85), fill=(0.96, 0.96, 0.97))
    page.insert_text(pymupdf.Point(48, y_b + 14), "BILL TO / RECIPIENT:", fontsize=8, fontname="helv")
    y_b_text = y_b + 26
    for btl in bill_to_lines:
        page.insert_text(pymupdf.Point(48, y_b_text), btl, fontsize=8.5, fontname="helv")
        y_b_text += 11

    return y_b + 62


def _draw_table_header(page: pymupdf.Page, y: float, columns: List[tuple]):
    """Draw table header row with column titles."""
    h_rect = pymupdf.Rect(40, y, 572, y + 18)
    page.draw_rect(h_rect, color=(0.2, 0.3, 0.5), fill=(0.2, 0.3, 0.5))
    for title, x, _ in columns:
        page.insert_text(pymupdf.Point(x, y + 13), title, fontsize=8.5, fontname="helv", color=(1, 1, 1))
    return y + 22


def _draw_footer(page: pymupdf.Page, current_page: int, total_pages: int, note: str):
    """Draw page footer with separator rule, note, and page numbering."""
    page.draw_line(pymupdf.Point(40, 750), pymupdf.Point(572, 750), color=(0.8, 0.8, 0.8), width=0.5)
    page.insert_text(pymupdf.Point(40, 762), note, fontsize=8, fontname="helv", color=(0.4, 0.4, 0.4))
    page.insert_text(
        pymupdf.Point(490, 762),
        f"Page {current_page} of {total_pages}",
        fontsize=8,
        fontname="helv",
        color=(0.4, 0.4, 0.4),
    )


def build_multipage_goods_invoice() -> tuple[bytes, CanonicalInvoice]:
    """Scenario 1: Multi-page goods invoice (ACME Test Foods Inc.)."""
    items_raw = [
        ("Extra Virgin Olive Oil 5L", "4", "EA", "42.50", "170.00"),
        ("All Purpose Flour 50LB", "10", "BAG", "22.00", "220.00"),
        ("Granulated Sugar 25LB", "5", "BAG", "18.50", "92.50"),
        ("Unsalted Butter 36LB Case", "2", "CS", "115.00", "230.00"),
        ("Whole Milk 1GAL", "12", "GAL", "4.25", "51.00"),
        ("Heavy Whipping Cream 1QT", "8", "QT", "5.50", "44.00"),
        ("Mozzarella Cheese Shredded 5LB", "6", "BAG", "19.80", "118.80"),
        ("San Marzano Whole Tomatoes 6x#10", "3", "CS", "48.00", "144.00"),
        ("Dried Spaghetti Pasta 20LB", "4", "CS", "26.50", "106.00"),
        ("Fresh Baker Yeast 1LB", "5", "PK", "3.20", "16.00"),
        ("Fine Sea Salt 25LB", "2", "BAG", "14.50", "29.00"),
        ("Whole Black Peppercorns 5LB", "1", "TUB", "38.00", "38.00"),
        ("Fresh Peeled Garlic 5LB", "3", "JAR", "16.50", "49.50"),
        ("Yellow Cooking Onions 50LB", "4", "BAG", "21.00", "84.00"),
        ("Idaho Russet Potatoes 50LB", "3", "BAG", "24.00", "72.00"),
        ("Crushed Tomato Paste 6x#10", "2", "CS", "45.00", "90.00"),
        ("Pure Madagascar Vanilla 32OZ", "1", "BTL", "65.00", "65.00"),
        ("Dark Dutch Cocoa Powder 10LB", "2", "BOX", "48.00", "96.00"),
        # Page 2 items
        ("Dry Active Yeast 2LB", "3", "PK", "12.00", "36.00"),
        ("Pure Cornstarch 50LB", "1", "BAG", "32.50", "32.50"),
        ("Clear Canola Frying Oil 35LB", "4", "JUG", "36.00", "144.00"),
        ("Dark Brown Sugar 25LB", "2", "BAG", "21.50", "43.00"),
        ("Grade A Large White Eggs 15DOZ", "3", "CS", "52.00", "156.00"),
        ("Mild Cheddar Cheese Block 10LB", "2", "BLOCK", "46.00", "92.00"),
        ("Grated Parmesan Cheese 5LB", "2", "TUB", "34.50", "69.00"),
        ("Distilled White Vinegar 4x1GAL", "2", "CS", "18.00", "36.00"),
        ("Double Acting Baking Powder 10LB", "1", "TUB", "28.00", "28.00"),
        ("Organic Rolled Oats 50LB", "2", "BAG", "31.00", "62.00"),
        ("Pure Clover Honey 5GAL Pail", "1", "PAIL", "125.00", "125.00"),
        ("Raw Walnut Halves 25LB", "1", "BOX", "88.00", "88.00"),
    ]

    doc = pymupdf.open()
    cols = [
        ("Description / Item", 45, "left"),
        ("Qty", 320, "right"),
        ("Unit", 365, "left"),
        ("Unit Price", 435, "right"),
        ("Amount", 515, "right"),
    ]

    # Page 1
    p1 = doc.new_page(width=612, height=792)
    y1 = _draw_page_header(
        p1,
        vendor_name="ACME Test Foods Inc.",
        vendor_lines=[
            "100 Food Distribution Way",
            "Warehouse District, IL 62701",
            "Phone: (555) 019-4821 | tax-id: 36-9871234",
        ],
        doc_title="COMMERCIAL INVOICE",
        meta_pairs=[
            ("Invoice No", "INV-ACME-2026-0801"),
            ("Invoice Date", "2026-08-10"),
            ("Payment Terms", "Net 20 Days"),
            ("Due Date", "2026-08-30"),
        ],
        bill_to_lines=[
            "Sample Kitchen Test Branch 1",
            "888 Gourmet Boulevard, Suite 100",
            "Springfield, IL 62704",
        ],
    )
    y1 = _draw_table_header(p1, y1 + 6, cols)

    page1_items = items_raw[:18]
    for idx, (name, qty, unit, price, total) in enumerate(page1_items):
        bg_col = (0.97, 0.97, 0.98) if idx % 2 == 1 else (1.0, 1.0, 1.0)
        p1.draw_rect(pymupdf.Rect(40, y1, 572, y1 + 17), color=bg_col, fill=bg_col)
        p1.insert_text(pymupdf.Point(45, y1 + 12), name, fontsize=8.5, fontname="helv")
        p1.insert_text(pymupdf.Point(325, y1 + 12), qty, fontsize=8.5, fontname="helv")
        p1.insert_text(pymupdf.Point(365, y1 + 12), unit, fontsize=8.5, fontname="helv")
        p1.insert_text(pymupdf.Point(435, y1 + 12), f"${price}", fontsize=8.5, fontname="helv")
        p1.insert_text(pymupdf.Point(515, y1 + 12), f"${total}", fontsize=8.5, fontname="helv")
        y1 += 17

    p1.insert_text(
        pymupdf.Point(40, y1 + 16),
        "-- Continued on next page --",
        fontsize=8.5,
        fontname="helv",
        color=(0.4, 0.4, 0.4),
    )
    _draw_footer(p1, 1, 2, "ACME Test Foods Inc. - Synthetic Multi-page Invoice Fixture")

    # Page 2
    p2 = doc.new_page(width=612, height=792)
    p2.draw_rect(pymupdf.Rect(40, 40, 572, 44), color=(0.15, 0.25, 0.45), fill=(0.15, 0.25, 0.45))
    p2.insert_text(
        pymupdf.Point(40, 68),
        "ACME Test Foods Inc. (Continued)",
        fontsize=13,
        fontname="helv",
    )
    p2.insert_text(
        pymupdf.Point(410, 68),
        "INV-ACME-2026-0801",
        fontsize=12,
        fontname="helv",
    )
    y2 = _draw_table_header(p2, 90, cols)

    page2_items = items_raw[18:]
    for idx, (name, qty, unit, price, total) in enumerate(page2_items):
        bg_col = (0.97, 0.97, 0.98) if idx % 2 == 1 else (1.0, 1.0, 1.0)
        p2.draw_rect(pymupdf.Rect(40, y2, 572, y2 + 17), color=bg_col, fill=bg_col)
        p2.insert_text(pymupdf.Point(45, y2 + 12), name, fontsize=8.5, fontname="helv")
        p2.insert_text(pymupdf.Point(325, y2 + 12), qty, fontsize=8.5, fontname="helv")
        p2.insert_text(pymupdf.Point(365, y2 + 12), unit, fontsize=8.5, fontname="helv")
        p2.insert_text(pymupdf.Point(435, y2 + 12), f"${price}", fontsize=8.5, fontname="helv")
        p2.insert_text(pymupdf.Point(515, y2 + 12), f"${total}", fontsize=8.5, fontname="helv")
        y2 += 17

    # Summary box
    y_sum = y2 + 15
    p2.draw_rect(
        pymupdf.Rect(350, y_sum, 572, y_sum + 95),
        color=(0.85, 0.85, 0.85),
        fill=(0.96, 0.96, 0.97),
    )
    summary_lines = [
        ("Subtotal", "$2627.30"),
        ("Sales Tax (8.25%)", "$216.75"),
        ("Freight / Shipping", "$35.00"),
        ("Grand Total", "$2879.05"),
        ("Amount Due", "$2879.05"),
    ]
    cur_ys = y_sum + 16
    for lbl, val in summary_lines:
        font_sz = 10 if "Total" in lbl or "Due" in lbl else 9
        p2.insert_text(pymupdf.Point(365, cur_ys), f"{lbl}:", fontsize=font_sz, fontname="helv")
        p2.insert_text(pymupdf.Point(495, cur_ys), val, fontsize=font_sz, fontname="helv")
        cur_ys += 16

    _draw_footer(p2, 2, 2, "ACME Test Foods Inc. - Thank you for your business!")

    bio = io.BytesIO()
    doc.save(bio, deflate=True)
    norm_bytes = _normalize_pdf_bytes(bio.getvalue())
    sha256_hash = hashlib.sha256(norm_bytes).hexdigest()

    line_items = [
        CanonicalLineItem(
            item_name=item[0],
            qty=Decimal(item[1]),
            unit_price=Decimal(item[3]),
            line_total=Decimal(item[4]),
            unit=item[2],
            kind=LineItemKind.GOODS,
            checkable=True,
        )
        for item in items_raw
    ]

    canonical = CanonicalInvoice(
        source_file="01_multipage_goods.pdf",
        source_sha256=sha256_hash,
        status=InvoiceStatus.VERIFIED,
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="ACME Test Foods Inc.",
        invoice_no="INV-ACME-2026-0801",
        invoice_date="2026-08-10",
        due_date="2026-08-30",
        currency="USD",
        category=Category.FOOD_INGREDIENTS,
        line_items=line_items,
        charges=[],
        subtotal=Decimal("2627.30"),
        tax=Decimal("216.75"),
        discount=None,
        shipping=Decimal("35.00"),
        tip=None,
        fees=[],
        grand_total=Decimal("2879.05"),
        amount_due=Decimal("2879.05"),
        review_reasons=[],
        schema_version=SCHEMA_VERSION,
        is_duplicate=False,
    )
    return norm_bytes, canonical


def build_utility_invoice() -> tuple[bytes, CanonicalInvoice]:
    """Scenario 2: Utility bill (Fake Power & Gas Utility Co.)."""
    charges_raw = [
        ("Previous Account Balance", "150.00"),
        ("Payment Received - Thank You", "-150.00"),
        ("Electric Facility Base Charge", "25.00"),
        ("Electric Energy Usage (1450 kWh)", "145.00"),
        ("Natural Gas Customer Basic Charge", "18.50"),
        ("Natural Gas Commodity Usage (65 Therms)", "58.50"),
        ("City Franchise Fee & Environmental Surcharge", "8.00"),
    ]

    doc = pymupdf.open()
    p = doc.new_page(width=612, height=792)

    y = _draw_page_header(
        p,
        vendor_name="Fake Power & Gas Utility Co.",
        vendor_lines=[
            "200 Energy Plaza, Station 4",
            "Chicago, IL 60601",
            "Emergency 24/7: (555) 018-9900",
        ],
        doc_title="UTILITY STATEMENT",
        meta_pairs=[
            ("Account No", "UTIL-2026-987654"),
            ("Billing Date", "2026-08-15"),
            ("Billing Period", "07/15/26 - 08/14/26"),
            ("Payment Due Date", "2026-09-05"),
        ],
        bill_to_lines=[
            "Test Commercial Customer",
            "Facility: Kitchen Unit #4",
            "456 Industrial Blvd, Chicago, IL 60607",
        ],
    )

    cols = [
        ("Description of Service / Utility Charge", 45, "left"),
        ("Amount ($)", 490, "right"),
    ]
    y = _draw_table_header(p, y + 10, cols)

    for idx, (desc, amt) in enumerate(charges_raw):
        bg_col = (0.97, 0.97, 0.98) if idx % 2 == 1 else (1.0, 1.0, 1.0)
        p.draw_rect(pymupdf.Rect(40, y, 572, y + 20), color=bg_col, fill=bg_col)
        p.insert_text(pymupdf.Point(45, y + 14), desc, fontsize=9, fontname="helv")
        val_str = f"-${amt.replace('-', '')}" if amt.startswith("-") else f"${amt}"
        p.insert_text(pymupdf.Point(490, y + 14), val_str, fontsize=9, fontname="helv")
        y += 20

    # Summary box
    y_sum = y + 20
    p.draw_rect(
        pymupdf.Rect(320, y_sum, 572, y_sum + 65),
        color=(0.15, 0.25, 0.45),
        fill=(0.94, 0.96, 0.98),
        width=1.0,
    )
    p.insert_text(pymupdf.Point(335, y_sum + 24), "Total Current Utility Charges:", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(490, y_sum + 24), "$255.00", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(335, y_sum + 48), "Total Amount Due:", fontsize=11, fontname="helv")
    p.insert_text(pymupdf.Point(490, y_sum + 48), "$255.00", fontsize=11, fontname="helv")

    p.insert_text(
        pymupdf.Point(40, y_sum + 85),
        "Note: Utility charges do not specify itemized qty * price multiplication.",
        fontsize=8.5,
        fontname="helv",
        color=(0.4, 0.4, 0.4),
    )
    _draw_footer(p, 1, 1, "Fake Power & Gas Utility Co. - Synthetic Utility Bill Fixture")

    bio = io.BytesIO()
    doc.save(bio, deflate=True)
    norm_bytes = _normalize_pdf_bytes(bio.getvalue())
    sha256_hash = hashlib.sha256(norm_bytes).hexdigest()

    charges = [
        CanonicalCharge(description=desc, amount=Decimal(amt))
        for desc, amt in charges_raw
    ]

    canonical = CanonicalInvoice(
        source_file="02_utility_fakepower.pdf",
        source_sha256=sha256_hash,
        status=InvoiceStatus.VERIFIED,
        doc_type=DocType.UTILITY_BILL,
        vendor_name="Fake Power & Gas Utility Co.",
        invoice_no="UTIL-2026-987654",
        invoice_date="2026-08-15",
        due_date="2026-09-05",
        currency="USD",
        category=Category.UTILITIES,
        line_items=[],
        charges=charges,
        subtotal=None,
        tax=None,
        discount=None,
        shipping=None,
        tip=None,
        fees=[],
        grand_total=Decimal("255.00"),
        amount_due=Decimal("255.00"),
        review_reasons=[],
        schema_version=SCHEMA_VERSION,
        is_duplicate=False,
    )
    return norm_bytes, canonical


def build_credit_memo_invoice() -> tuple[bytes, CanonicalInvoice]:
    """Scenario 3: Credit memo with negative line items and negative grand total (Fake Returns Inc.)."""
    items_raw = [
        ("Damaged Organic Olive Oil 5L (Return)", "-2", "EA", "45.00", "-90.00"),
        ("Defective Truffle Sauce 500g (Return)", "-3", "JAR", "28.50", "-85.50"),
        ("Credit for Restocking Allowance", "-1", "EA", "10.00", "-10.00"),
    ]

    doc = pymupdf.open()
    p = doc.new_page(width=612, height=792)

    y = _draw_page_header(
        p,
        vendor_name="Fake Returns Inc.",
        vendor_lines=[
            "777 Reverse Logistics Way",
            "Returns Center, NV 89101",
            "Support: (555) 016-3322",
        ],
        doc_title="CREDIT MEMORANDUM",
        meta_pairs=[
            ("Credit Memo No", "CR-MEMO-5544"),
            ("Date Issued", "2026-08-12"),
            ("Original Reference", "INV-2026-0715"),
            ("Credit Effective", "2026-08-12"),
        ],
        bill_to_lines=[
            "Test Kitchen Wholesale Customer",
            "Store Branch #12",
            "990 Market Street, Reno, NV 89501",
        ],
    )

    cols = [
        ("Returned Item / Credit Reason", 45, "left"),
        ("Credit Qty", 310, "right"),
        ("Unit", 365, "left"),
        ("Unit Price", 435, "right"),
        ("Credit Total", 510, "right"),
    ]
    y = _draw_table_header(p, y + 10, cols)

    for idx, (name, qty, unit, price, total) in enumerate(items_raw):
        bg_col = (0.97, 0.97, 0.98) if idx % 2 == 1 else (1.0, 1.0, 1.0)
        p.draw_rect(pymupdf.Rect(40, y, 572, y + 20), color=bg_col, fill=bg_col)
        p.insert_text(pymupdf.Point(45, y + 14), name, fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(315, y + 14), qty, fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(365, y + 14), unit, fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(435, y + 14), f"${price}", fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(510, y + 14), f"-${total.replace('-', '')}", fontsize=8.5, fontname="helv")
        y += 20

    # Summary box
    y_sum = y + 20
    p.draw_rect(
        pymupdf.Rect(350, y_sum, 572, y_sum + 80),
        color=(0.85, 0.85, 0.85),
        fill=(0.96, 0.96, 0.97),
    )
    p.insert_text(pymupdf.Point(365, y_sum + 18), "Net Credit Subtotal:", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(490, y_sum + 18), "-$185.50", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(365, y_sum + 36), "Sales Tax Adjustment (8%):", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(490, y_sum + 36), "-$14.84", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(365, y_sum + 56), "Total Credit Amount:", fontsize=10, fontname="helv")
    p.insert_text(pymupdf.Point(490, y_sum + 56), "-$200.34", fontsize=10, fontname="helv")

    p.insert_text(
        pymupdf.Point(40, y_sum + 95),
        "Total credit balance applied to customer account. Negative values indicate credit/refund.",
        fontsize=8.5,
        fontname="helv",
        color=(0.4, 0.4, 0.4),
    )
    _draw_footer(p, 1, 1, "Fake Returns Inc. - Synthetic Credit Memo Fixture")

    bio = io.BytesIO()
    doc.save(bio, deflate=True)
    norm_bytes = _normalize_pdf_bytes(bio.getvalue())
    sha256_hash = hashlib.sha256(norm_bytes).hexdigest()

    line_items = [
        CanonicalLineItem(
            item_name=item[0],
            qty=Decimal(item[1]),
            unit_price=Decimal(item[3]),
            line_total=Decimal(item[4]),
            unit=item[2],
            kind=LineItemKind.GOODS,
            checkable=True,
        )
        for item in items_raw
    ]

    canonical = CanonicalInvoice(
        source_file="03_credit_memo_returns.pdf",
        source_sha256=sha256_hash,
        status=InvoiceStatus.VERIFIED,
        doc_type=DocType.CREDIT_MEMO,
        vendor_name="Fake Returns Inc.",
        invoice_no="CR-MEMO-5544",
        invoice_date="2026-08-12",
        due_date="2026-08-12",
        currency="USD",
        category=Category.OTHER,
        line_items=line_items,
        charges=[],
        subtotal=Decimal("-185.50"),
        tax=Decimal("-14.84"),
        discount=None,
        shipping=None,
        tip=None,
        fees=[],
        grand_total=Decimal("-200.34"),
        amount_due=Decimal("-200.34"),
        review_reasons=[],
        schema_version=SCHEMA_VERSION,
        is_duplicate=False,
    )
    return norm_bytes, canonical


def build_produce_by_weight_invoice() -> tuple[bytes, CanonicalInvoice]:
    """Scenario 4: Weighed goods with fractional quantities (Fake Produce Market Co.)."""
    items_raw = [
        ("Organic Roma Tomatoes", "1.25", "LB", "3.60", "4.50"),
        ("Fresh Hass Avocados", "3.45", "KG", "6.80", "23.46"),
        ("Sweet Vidalia Onions", "5.75", "LB", "1.40", "8.05"),
        ("Baby Spinach Hydroponic", "2.50", "KG", "7.20", "18.00"),
    ]

    doc = pymupdf.open()
    p = doc.new_page(width=612, height=792)

    y = _draw_page_header(
        p,
        vendor_name="Fake Produce Market Co.",
        vendor_lines=[
            "500 Fresh Orchard Road",
            "Central Valley, CA 95201",
            "Wholesale Orders: (555) 012-7890",
        ],
        doc_title="PRODUCE INVOICE",
        meta_pairs=[
            ("Invoice No", "FPM-88219"),
            ("Invoice Date", "2026-08-18"),
            ("Terms", "Net 10 Days"),
            ("Due Date", "2026-08-28"),
        ],
        bill_to_lines=[
            "Farm-to-Table Kitchen #3",
            "742 Evergreen Terrace",
            "Sacramento, CA 95814",
        ],
    )

    cols = [
        ("Weighed Item Description", 45, "left"),
        ("Weight / Qty", 310, "right"),
        ("Unit", 365, "left"),
        ("Price / Unit", 435, "right"),
        ("Total Amount", 510, "right"),
    ]
    y = _draw_table_header(p, y + 10, cols)

    for idx, (name, qty, unit, price, total) in enumerate(items_raw):
        bg_col = (0.97, 0.97, 0.98) if idx % 2 == 1 else (1.0, 1.0, 1.0)
        p.draw_rect(pymupdf.Rect(40, y, 572, y + 20), color=bg_col, fill=bg_col)
        p.insert_text(pymupdf.Point(45, y + 14), name, fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(315, y + 14), qty, fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(365, y + 14), unit, fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(435, y + 14), f"${price}", fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(510, y + 14), f"${total}", fontsize=8.5, fontname="helv")
        y += 20

    # Summary box
    y_sum = y + 20
    p.draw_rect(
        pymupdf.Rect(350, y_sum, 572, y_sum + 80),
        color=(0.85, 0.85, 0.85),
        fill=(0.96, 0.96, 0.97),
    )
    p.insert_text(pymupdf.Point(365, y_sum + 18), "Subtotal:", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(495, y_sum + 18), "$54.01", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(365, y_sum + 36), "Produce Tax (5.00%):", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(495, y_sum + 36), "$2.70", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(365, y_sum + 56), "Total Balance Due:", fontsize=10, fontname="helv")
    p.insert_text(pymupdf.Point(495, y_sum + 56), "$56.71", fontsize=10, fontname="helv")

    _draw_footer(p, 1, 1, "Fake Produce Market Co. - Synthetic Weighed Goods Fixture")

    bio = io.BytesIO()
    doc.save(bio, deflate=True)
    norm_bytes = _normalize_pdf_bytes(bio.getvalue())
    sha256_hash = hashlib.sha256(norm_bytes).hexdigest()

    line_items = [
        CanonicalLineItem(
            item_name=item[0],
            qty=Decimal(item[1]),
            unit_price=Decimal(item[3]),
            line_total=Decimal(item[4]),
            unit=item[2],
            kind=LineItemKind.GOODS,
            checkable=True,
        )
        for item in items_raw
    ]

    canonical = CanonicalInvoice(
        source_file="04_produce_by_weight.pdf",
        source_sha256=sha256_hash,
        status=InvoiceStatus.VERIFIED,
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="Fake Produce Market Co.",
        invoice_no="FPM-88219",
        invoice_date="2026-08-18",
        due_date="2026-08-28",
        currency="USD",
        category=Category.FOOD_INGREDIENTS,
        line_items=line_items,
        charges=[],
        subtotal=Decimal("54.01"),
        tax=Decimal("2.70"),
        discount=None,
        shipping=None,
        tip=None,
        fees=[],
        grand_total=Decimal("56.71"),
        amount_due=Decimal("56.71"),
        review_reasons=[],
        schema_version=SCHEMA_VERSION,
        is_duplicate=False,
    )
    return norm_bytes, canonical


def build_discount_invoice() -> tuple[bytes, CanonicalInvoice]:
    """Scenario 5: Invoice with discount line item (Fake Tech Supplies Ltd.)."""
    items_raw = [
        ("Thermal POS Receipt Paper Rolls 80mm (50 PK)", "4", "PK", "35.00", "140.00", LineItemKind.GOODS),
        ("Omnidirectional Barcode Scanner USB", "2", "EA", "65.00", "130.00", LineItemKind.GOODS),
        ("Special Promotional Volume Discount", "1", "EA", "-27.00", "-27.00", LineItemKind.DISCOUNT),
    ]

    doc = pymupdf.open()
    p = doc.new_page(width=612, height=792)

    y = _draw_page_header(
        p,
        vendor_name="Fake Tech Supplies Ltd.",
        vendor_lines=[
            "1200 Technology Parkway, Suite 500",
            "Austin, TX 78759",
            "Sales: (555) 014-9988 | tax-id: 74-8833912",
        ],
        doc_title="TAX INVOICE",
        meta_pairs=[
            ("Invoice No", "FTECH-2026-771"),
            ("Invoice Date", "2026-08-20"),
            ("Terms", "Net 21 Days"),
            ("Due Date", "2026-09-10"),
        ],
        bill_to_lines=[
            "Automated Restaurant Systems",
            "100 Innovation Drive",
            "Austin, TX 78701",
        ],
    )

    cols = [
        ("Product Description / Line Discount", 45, "left"),
        ("Qty", 320, "right"),
        ("Unit", 365, "left"),
        ("Unit Price", 435, "right"),
        ("Extended Total", 510, "right"),
    ]
    y = _draw_table_header(p, y + 10, cols)

    for idx, (name, qty, unit, price, total, kind) in enumerate(items_raw):
        bg_col = (0.97, 0.97, 0.98) if idx % 2 == 1 else (1.0, 1.0, 1.0)
        p.draw_rect(pymupdf.Rect(40, y, 572, y + 20), color=bg_col, fill=bg_col)
        p.insert_text(pymupdf.Point(45, y + 14), name, fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(325, y + 14), qty, fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(365, y + 14), unit, fontsize=8.5, fontname="helv")
        price_str = f"-${price.replace('-', '')}" if price.startswith("-") else f"${price}"
        total_str = f"-${total.replace('-', '')}" if total.startswith("-") else f"${total}"
        p.insert_text(pymupdf.Point(435, y + 14), price_str, fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(510, y + 14), total_str, fontsize=8.5, fontname="helv")
        y += 20

    # Summary box
    y_sum = y + 20
    p.draw_rect(
        pymupdf.Rect(350, y_sum, 572, y_sum + 80),
        color=(0.85, 0.85, 0.85),
        fill=(0.96, 0.96, 0.97),
    )
    p.insert_text(pymupdf.Point(365, y_sum + 18), "Net Subtotal:", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(495, y_sum + 18), "$243.00", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(365, y_sum + 36), "Sales Tax (8.00%):", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(495, y_sum + 36), "$19.44", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(365, y_sum + 56), "Total Amount Due:", fontsize=10, fontname="helv")
    p.insert_text(pymupdf.Point(495, y_sum + 56), "$262.44", fontsize=10, fontname="helv")

    _draw_footer(p, 1, 1, "Fake Tech Supplies Ltd. - Synthetic Discount Fixture")

    bio = io.BytesIO()
    doc.save(bio, deflate=True)
    norm_bytes = _normalize_pdf_bytes(bio.getvalue())
    sha256_hash = hashlib.sha256(norm_bytes).hexdigest()

    line_items = [
        CanonicalLineItem(
            item_name=item[0],
            qty=Decimal(item[1]),
            unit_price=Decimal(item[3]),
            line_total=Decimal(item[4]),
            unit=item[2],
            kind=item[5],
            checkable=True,
        )
        for item in items_raw
    ]

    canonical = CanonicalInvoice(
        source_file="05_discount_faketech.pdf",
        source_sha256=sha256_hash,
        status=InvoiceStatus.VERIFIED,
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="Fake Tech Supplies Ltd.",
        invoice_no="FTECH-2026-771",
        invoice_date="2026-08-20",
        due_date="2026-09-10",
        currency="USD",
        category=Category.PACKAGING,
        line_items=line_items,
        charges=[],
        subtotal=Decimal("243.00"),
        tax=Decimal("19.44"),
        discount=None,
        shipping=None,
        tip=None,
        fees=[],
        grand_total=Decimal("262.44"),
        amount_due=Decimal("262.44"),
        review_reasons=[],
        schema_version=SCHEMA_VERSION,
        is_duplicate=False,
    )
    return norm_bytes, canonical


def build_multi_tax_invoice() -> tuple[bytes, CanonicalInvoice]:
    """Scenario 6: Multi-tax invoice (Fake NYC Restaurant Depot with NY State + NYC tax)."""
    items_raw = [
        ("Heavy Duty Aluminum Foil 18in x 1000ft", "2", "ROLL", "48.00", "96.00"),
        ("Commercial Polycarbonate Pan 12QT", "6", "EA", "16.50", "99.00"),
        ("Bulk Canola Frying Oil 35LB", "3", "JUG", "75.00", "225.00"),
        ("Cotton Kitchen Bar Mop Towels 50PK", "2", "PK", "40.00", "80.00"),
    ]

    doc = pymupdf.open()
    p = doc.new_page(width=612, height=792)

    y = _draw_page_header(
        p,
        vendor_name="Fake NYC Restaurant Depot",
        vendor_lines=[
            "400 Maspeth Avenue",
            "Brooklyn, NY 11211",
            "Customer Service: (555) 019-7733 | NY ID: 11-8293741",
        ],
        doc_title="WHOLESALE INVOICE",
        meta_pairs=[
            ("Invoice No", "DEPOT-NYC-9012"),
            ("Invoice Date", "2026-08-22"),
            ("Payment Terms", "Net 10 Days"),
            ("Due Date", "2026-09-01"),
        ],
        bill_to_lines=[
            "Little Italy Pizzeria Test",
            "124 Mulberry Street",
            "New York, NY 10013",
        ],
    )

    cols = [
        ("Description / SKU", 45, "left"),
        ("Qty", 320, "right"),
        ("Unit", 365, "left"),
        ("Unit Price", 435, "right"),
        ("Line Total", 510, "right"),
    ]
    y = _draw_table_header(p, y + 10, cols)

    for idx, (name, qty, unit, price, total) in enumerate(items_raw):
        bg_col = (0.97, 0.97, 0.98) if idx % 2 == 1 else (1.0, 1.0, 1.0)
        p.draw_rect(pymupdf.Rect(40, y, 572, y + 20), color=bg_col, fill=bg_col)
        p.insert_text(pymupdf.Point(45, y + 14), name, fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(325, y + 14), qty, fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(365, y + 14), unit, fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(435, y + 14), f"${price}", fontsize=8.5, fontname="helv")
        p.insert_text(pymupdf.Point(510, y + 14), f"${total}", fontsize=8.5, fontname="helv")
        y += 20

    # Summary box with multi-tier taxes
    y_sum = y + 20
    p.draw_rect(
        pymupdf.Rect(330, y_sum, 572, y_sum + 105),
        color=(0.85, 0.85, 0.85),
        fill=(0.96, 0.96, 0.97),
    )
    p.insert_text(pymupdf.Point(345, y_sum + 18), "Goods Subtotal:", fontsize=9, fontname="helv")
    p.insert_text(pymupdf.Point(495, y_sum + 18), "$500.00", fontsize=9, fontname="helv")

    p.insert_text(pymupdf.Point(345, y_sum + 36), "NY State Sales Tax (4.000%):", fontsize=8.5, fontname="helv")
    p.insert_text(pymupdf.Point(495, y_sum + 36), "$20.00", fontsize=8.5, fontname="helv")

    p.insert_text(pymupdf.Point(345, y_sum + 54), "NYC Local Sales Tax (4.875%):", fontsize=8.5, fontname="helv")
    p.insert_text(pymupdf.Point(495, y_sum + 54), "$24.38", fontsize=8.5, fontname="helv")

    p.insert_text(pymupdf.Point(345, y_sum + 72), "Total Combined Taxes:", fontsize=8.5, fontname="helv")
    p.insert_text(pymupdf.Point(495, y_sum + 72), "$44.38", fontsize=8.5, fontname="helv")

    p.insert_text(pymupdf.Point(345, y_sum + 94), "Invoice Total Amount Due:", fontsize=10, fontname="helv")
    p.insert_text(pymupdf.Point(495, y_sum + 94), "$544.38", fontsize=10, fontname="helv")

    _draw_footer(p, 1, 1, "Fake NYC Restaurant Depot - Synthetic Multi-Tax Fixture")

    bio = io.BytesIO()
    doc.save(bio, deflate=True)
    norm_bytes = _normalize_pdf_bytes(bio.getvalue())
    sha256_hash = hashlib.sha256(norm_bytes).hexdigest()

    line_items = [
        CanonicalLineItem(
            item_name=item[0],
            qty=Decimal(item[1]),
            unit_price=Decimal(item[3]),
            line_total=Decimal(item[4]),
            unit=item[2],
            kind=LineItemKind.GOODS,
            checkable=True,
        )
        for item in items_raw
    ]

    canonical = CanonicalInvoice(
        source_file="06_multi_tax_depot.pdf",
        source_sha256=sha256_hash,
        status=InvoiceStatus.VERIFIED,
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="Fake NYC Restaurant Depot",
        invoice_no="DEPOT-NYC-9012",
        invoice_date="2026-08-22",
        due_date="2026-09-01",
        currency="USD",
        category=Category.FOOD_INGREDIENTS,
        line_items=line_items,
        charges=[],
        subtotal=Decimal("500.00"),
        tax=Decimal("44.38"),
        discount=None,
        shipping=None,
        tip=None,
        fees=[],
        grand_total=Decimal("544.38"),
        amount_due=Decimal("544.38"),
        review_reasons=[],
        schema_version=SCHEMA_VERSION,
        is_duplicate=False,
    )
    return norm_bytes, canonical


GENERATORS = [
    ("01_multipage_goods", build_multipage_goods_invoice),
    ("02_utility_fakepower", build_utility_invoice),
    ("03_credit_memo_returns", build_credit_memo_invoice),
    ("04_produce_by_weight", build_produce_by_weight_invoice),
    ("05_discount_faketech", build_discount_invoice),
    ("06_multi_tax_depot", build_multi_tax_invoice),
]


def generate_all_fixtures(output_dir: Path = FIXTURES_DIR) -> Dict[str, Dict[str, Any]]:
    """Generate all synthetic PDF invoices and matching truth.json files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    for stem, gen_fn in GENERATORS:
        pdf_bytes, canonical = gen_fn()
        pdf_path = output_dir / f"{stem}.pdf"
        truth_path = output_dir / f"{stem}.truth.json"

        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)

        truth_dict = canonical.to_jsonl_dict()
        with open(truth_path, "w", encoding="utf-8") as f:
            json.dump(truth_dict, f, indent=2, ensure_ascii=False)

        results[stem] = {
            "pdf_path": str(pdf_path),
            "truth_path": str(truth_path),
            "sha256": canonical.source_sha256,
            "doc_type": canonical.doc_type.value,
            "grand_total": str(canonical.grand_total),
        }

    return results


def verify_fixtures_integrity(output_dir: Path = FIXTURES_DIR):
    """Validate structural, textual, and mathematical integrity of generated fixtures."""
    assert output_dir.exists(), f"Fixtures directory does not exist: {output_dir}"

    for stem, _ in GENERATORS:
        pdf_path = output_dir / f"{stem}.pdf"
        truth_path = output_dir / f"{stem}.truth.json"

        assert pdf_path.exists(), f"Missing PDF fixture: {pdf_path}"
        assert truth_path.exists(), f"Missing truth fixture: {truth_path}"

        # 1. SHA256 integrity
        with open(pdf_path, "rb") as f:
            data = f.read()
        calculated_sha = hashlib.sha256(data).hexdigest()

        with open(truth_path, "r", encoding="utf-8") as f:
            truth_dict = json.load(f)

        assert truth_dict["source_sha256"] == calculated_sha, (
            f"SHA256 mismatch for {stem}: {truth_dict['source_sha256']} != {calculated_sha}"
        )

        # 2. CanonicalInvoice schema roundtrip
        inv = CanonicalInvoice(**truth_dict)
        assert inv.status == InvoiceStatus.VERIFIED

        # 3. PDF text layer verification
        doc = pymupdf.open(pdf_path)
        assert len(doc) >= 1

        total_words = 0
        total_chars = 0
        for page_idx, page in enumerate(doc):
            words = page.get_text("words")
            text = page.get_text()
            printable_count = sum(1 for c in text if c.isprintable())
            valid_ratio = printable_count / max(len(text), 1)

            assert len(words) > 10, f"Page {page_idx+1} in {stem} has insufficient words: {len(words)}"
            assert printable_count >= 50, f"Page {page_idx+1} in {stem} has < 50 printable chars: {printable_count}"
            assert valid_ratio >= 0.85, f"Page {page_idx+1} in {stem} valid char ratio < 0.85: {valid_ratio}"

            total_words += len(words)
            total_chars += printable_count

        # 4. Arithmetic checks
        if inv.doc_type == DocType.GOODS_INVOICE:
            # Tier 1 checks
            for li in inv.line_items:
                if li.qty is not None and li.unit_price is not None:
                    calc_total = round(li.qty * li.unit_price, 2)
                    assert abs(calc_total - li.line_total) <= Decimal("0.02"), (
                        f"Tier 1 mismatch on {li.item_name}: {li.qty} * {li.unit_price} = {calc_total} vs {li.line_total}"
                    )

            # Tier 2 check
            sum_lines = sum(li.line_total for li in inv.line_items)
            assert abs(sum_lines - inv.subtotal) <= Decimal("0.02"), (
                f"Tier 2 mismatch in {stem}: sum(lines)={sum_lines} vs subtotal={inv.subtotal}"
            )

            # Tier 3 check
            shipping = inv.shipping or Decimal("0.00")
            tax = inv.tax or Decimal("0.00")
            discount = inv.discount or Decimal("0.00")
            expected_grand = inv.subtotal + tax + shipping - discount
            assert abs(expected_grand - inv.grand_total) <= Decimal("0.02"), (
                f"Tier 3 mismatch in {stem}: expected {expected_grand} vs grand_total {inv.grand_total}"
            )

        elif inv.doc_type == DocType.UTILITY_BILL:
            # Tier 4 check
            sum_charges = sum(c.amount for c in inv.charges)
            assert abs(sum_charges - inv.amount_due) <= Decimal("0.02"), (
                f"Tier 4 mismatch in {stem}: sum(charges)={sum_charges} vs amount_due={inv.amount_due}"
            )

        elif inv.doc_type == DocType.CREDIT_MEMO:
            # Credit memo checks
            assert inv.grand_total < Decimal("0.00"), f"Credit memo {stem} grand_total must be negative: {inv.grand_total}"
            for li in inv.line_items:
                assert li.line_total < Decimal("0.00"), f"Credit memo {stem} line must be negative: {li.line_total}"
            sum_lines = sum(li.line_total for li in inv.line_items)
            assert abs(sum_lines - inv.subtotal) <= Decimal("0.02")
            expected_grand = inv.subtotal + (inv.tax or Decimal("0.00"))
            assert abs(expected_grand - inv.grand_total) <= Decimal("0.02")


# ---------------------------------------------------------------------------
# Pytest Integration Test Functions
# ---------------------------------------------------------------------------

def test_make_fixtures_pdf_generation():
    """Test generation and verification of all 6 PDF fixtures."""
    results = generate_all_fixtures()
    assert len(results) == 6
    verify_fixtures_integrity()


def test_fixture_01_multipage_properties():
    """Validate specific properties of fixture 1: multi-page goods."""
    pdf_path = FIXTURES_DIR / "01_multipage_goods.pdf"
    truth_path = FIXTURES_DIR / "01_multipage_goods.truth.json"
    doc = pymupdf.open(pdf_path)
    assert len(doc) == 2, f"Expected 2 pages, got {len(doc)}"

    with open(truth_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["line_items"]) == 30
    assert data["vendor_name"] == "ACME Test Foods Inc."
    assert data["grand_total"] == "2879.05"


def test_fixture_02_utility_properties():
    """Validate specific properties of fixture 2: utility bill without qty*price."""
    truth_path = FIXTURES_DIR / "02_utility_fakepower.truth.json"
    with open(truth_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["doc_type"] == "utility_bill"
    assert len(data["charges"]) == 7
    assert len(data["line_items"]) == 0
    assert data["grand_total"] == "255.00"


def test_fixture_03_credit_memo_properties():
    """Validate specific properties of fixture 3: credit memo with negative totals."""
    truth_path = FIXTURES_DIR / "03_credit_memo_returns.truth.json"
    with open(truth_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["doc_type"] == "credit_memo"
    assert Decimal(data["grand_total"]) < Decimal("0.00")
    for li in data["line_items"]:
        assert Decimal(li["line_total"]) < Decimal("0.00")


def test_fixture_04_weighed_produce_properties():
    """Validate specific properties of fixture 4: fractional quantities."""
    truth_path = FIXTURES_DIR / "04_produce_by_weight.truth.json"
    with open(truth_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["doc_type"] == "goods_invoice"
    qtys = [li["qty"] for li in data["line_items"]]
    assert "1.25" in qtys
    assert "3.45" in qtys


def test_fixture_05_discount_properties():
    """Validate specific properties of fixture 5: negative discount line."""
    truth_path = FIXTURES_DIR / "05_discount_faketech.truth.json"
    with open(truth_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    kinds = [li["kind"] for li in data["line_items"]]
    assert "discount" in kinds
    discount_line = [li for li in data["line_items"] if li["kind"] == "discount"][0]
    assert Decimal(discount_line["line_total"]) < Decimal("0.00")


def test_fixture_06_multi_tax_properties():
    """Validate specific properties of fixture 6: multi tax lines."""
    pdf_path = FIXTURES_DIR / "06_multi_tax_depot.pdf"
    truth_path = FIXTURES_DIR / "06_multi_tax_depot.truth.json"
    doc = pymupdf.open(pdf_path)
    text = doc[0].get_text()
    assert "NY State Sales Tax" in text
    assert "NYC Local Sales Tax" in text

    with open(truth_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["tax"] == "44.38"
    assert data["grand_total"] == "544.38"


if __name__ == "__main__":
    print(f"Generating synthetic PDF fixtures in {FIXTURES_DIR}...")
    res = generate_all_fixtures()
    print(f"Generated {len(res)} fixtures:")
    for k, v in res.items():
        print(f"  - {k}: sha256={v['sha256'][:12]}... doc_type={v['doc_type']} total={v['grand_total']}")

    print("\nVerifying integrity...")
    verify_fixtures_integrity()
    print("All fixtures verified successfully!")
