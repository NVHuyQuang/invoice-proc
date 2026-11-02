"""Tests for deduplication module (PLAN 6.3).

Covers:
- Exact SHA-256 match.
- Compound key match: (normalized vendor, invoice_no, grand_total).
- Fuzzy vendor matching with rapidfuzz (e.g. Chefs Warehouse vs The Chefs Warehouse).
- Edge cases: None fields, different totals/numbers/vendors, case/whitespace/hash variations.
- Status updates: is_duplicate=True, status=DUPLICATE, duplicate_of=first_invoice.source_file.
"""

from decimal import Decimal
from typing import Optional
import pytest

from config import DEDUP_SIMILARITY_THRESHOLD
from core.dedup import (
    deduplicate_invoices,
    is_vendor_similar,
    normalize_invoice_no,
    normalize_vendor_name,
)
from models.schema import CanonicalInvoice, InvoiceStatus


def _make_invoice(
    source_file: str,
    source_sha256: Optional[str] = None,
    vendor_name: str = "Test Vendor",
    invoice_no: str = "INV-001",
    grand_total: Decimal = Decimal("100.00"),
    status: InvoiceStatus = InvoiceStatus.VERIFIED,
) -> CanonicalInvoice:
    """Helper to create CanonicalInvoice for testing."""
    if source_sha256 is None:
        source_sha256 = f"sha256_of_{source_file}"
    return CanonicalInvoice(
        source_file=source_file,
        source_sha256=source_sha256,
        vendor_name=vendor_name,
        invoice_no=invoice_no,
        grand_total=grand_total,
        status=status,
    )


# ---------------------------------------------------------------------------
# 1. Exact SHA-256 duplicate tests
# ---------------------------------------------------------------------------

def test_exact_sha256_duplicate():
    """Identical source_sha256 should mark subsequent invoice as DUPLICATE."""
    inv1 = _make_invoice("file1.pdf", source_sha256="abc123sha")
    inv2 = _make_invoice("file2.pdf", source_sha256="abc123sha")

    invoices, duplicates = deduplicate_invoices([inv1, inv2])

    assert len(invoices) == 2
    assert inv1.is_duplicate is False
    assert inv1.status == InvoiceStatus.VERIFIED
    assert inv1.duplicate_of is None

    assert inv2.is_duplicate is True
    assert inv2.status == InvoiceStatus.DUPLICATE
    assert inv2.duplicate_of == "file1.pdf"

    assert len(duplicates) == 1
    assert duplicates[0] == ("file2.pdf", "file1.pdf", "exact_sha256")


def test_exact_sha256_multiple_duplicates():
    """Multiple duplicates of the same original should all point to the first."""
    inv1 = _make_invoice("file1.pdf", source_sha256="same_sha")
    inv2 = _make_invoice("file2.pdf", source_sha256="same_sha")
    inv3 = _make_invoice("file3.pdf", source_sha256="same_sha")

    invoices, duplicates = deduplicate_invoices([inv1, inv2, inv3])

    assert inv1.is_duplicate is False
    assert inv2.is_duplicate is True
    assert inv2.duplicate_of == "file1.pdf"
    assert inv3.is_duplicate is True
    assert inv3.duplicate_of == "file1.pdf"

    assert len(duplicates) == 2
    assert duplicates == [
        ("file2.pdf", "file1.pdf", "exact_sha256"),
        ("file3.pdf", "file1.pdf", "exact_sha256"),
    ]


# ---------------------------------------------------------------------------
# 2. Compound key duplicate tests (exact vendor)
# ---------------------------------------------------------------------------

def test_compound_key_exact_match():
    """Different sha256 but exact (vendor, invoice_no, grand_total) matches."""
    inv1 = _make_invoice(
        "scan1.pdf",
        source_sha256="hash_1",
        vendor_name="Sysco",
        invoice_no="INV-999",
        grand_total=Decimal("450.75"),
    )
    inv2 = _make_invoice(
        "scan2.pdf",
        source_sha256="hash_2",
        vendor_name="Sysco",
        invoice_no="INV-999",
        grand_total=Decimal("450.75"),
    )

    invoices, duplicates = deduplicate_invoices([inv1, inv2])

    assert inv1.is_duplicate is False
    assert inv2.is_duplicate is True
    assert inv2.status == InvoiceStatus.DUPLICATE
    assert inv2.duplicate_of == "scan1.pdf"

    assert len(duplicates) == 1
    assert duplicates[0] == ("scan2.pdf", "scan1.pdf", "compound_key")


# ---------------------------------------------------------------------------
# 3. Fuzzy vendor matching (Chefs Warehouse vs The Chefs Warehouse)
# ---------------------------------------------------------------------------

def test_compound_key_fuzzy_vendor_chefs_warehouse():
    """Fuzzy vendor: 'Chefs Warehouse' vs 'The Chefs Warehouse' should match."""
    inv1 = _make_invoice(
        "inv_chefs1.pdf",
        source_sha256="sha_cw_1",
        vendor_name="Chefs Warehouse",
        invoice_no="CW-100234",
        grand_total=Decimal("1234.50"),
    )
    inv2 = _make_invoice(
        "inv_chefs2.pdf",
        source_sha256="sha_cw_2",
        vendor_name="The Chefs Warehouse",
        invoice_no="CW-100234",
        grand_total=Decimal("1234.50"),
    )

    invoices, duplicates = deduplicate_invoices([inv1, inv2])

    assert inv1.is_duplicate is False
    assert inv2.is_duplicate is True
    assert inv2.status == InvoiceStatus.DUPLICATE
    assert inv2.duplicate_of == "inv_chefs1.pdf"

    assert len(duplicates) == 1
    assert duplicates[0] == ("inv_chefs2.pdf", "inv_chefs1.pdf", "compound_key")


def test_compound_key_fuzzy_vendor_with_punctuation():
    """Fuzzy vendor with apostrophe and punctuation."""
    inv1 = _make_invoice(
        "docA.pdf",
        source_sha256="sha_a",
        vendor_name="The Chefs' Warehouse, Inc.",
        invoice_no="INV-88",
        grand_total=Decimal("50.00"),
    )
    inv2 = _make_invoice(
        "docB.pdf",
        source_sha256="sha_b",
        vendor_name="Chefs Warehouse",
        invoice_no="INV-88",
        grand_total=Decimal("50.00"),
    )

    _, duplicates = deduplicate_invoices([inv1, inv2])
    assert len(duplicates) == 1
    assert duplicates[0] == ("docB.pdf", "docA.pdf", "compound_key")


# ---------------------------------------------------------------------------
# 4. Normalization tolerance (invoice_no casing, whitespace, '#')
# ---------------------------------------------------------------------------

def test_invoice_no_normalization_variants():
    """invoice_no variants like '#12345', ' 12345 ', 'inv-12345' vs 'INV-12345'."""
    inv1 = _make_invoice(
        "f1.pdf",
        source_sha256="h1",
        vendor_name="Baldor",
        invoice_no="#INV-500",
        grand_total=Decimal("80.00"),
    )
    inv2 = _make_invoice(
        "f2.pdf",
        source_sha256="h2",
        vendor_name="Baldor",
        invoice_no=" inv-500 ",
        grand_total=Decimal("80.00"),
    )

    _, duplicates = deduplicate_invoices([inv1, inv2])
    assert len(duplicates) == 1
    assert duplicates[0] == ("f2.pdf", "f1.pdf", "compound_key")


# ---------------------------------------------------------------------------
# 5. Non-duplicate cases (should NOT trigger dedup)
# ---------------------------------------------------------------------------

def test_different_invoice_no_not_duplicate():
    """Same vendor and total, but different invoice_no -> not duplicate."""
    inv1 = _make_invoice("f1.pdf", source_sha256="h1", vendor_name="Sysco", invoice_no="INV-1", grand_total=Decimal("100"))
    inv2 = _make_invoice("f2.pdf", source_sha256="h2", vendor_name="Sysco", invoice_no="INV-2", grand_total=Decimal("100"))

    invoices, duplicates = deduplicate_invoices([inv1, inv2])
    assert len(duplicates) == 0
    assert not any(i.is_duplicate for i in invoices)


def test_different_grand_total_not_duplicate():
    """Same vendor and invoice_no, but different grand_total -> not duplicate."""
    inv1 = _make_invoice("f1.pdf", source_sha256="h1", vendor_name="Sysco", invoice_no="INV-1", grand_total=Decimal("100.00"))
    inv2 = _make_invoice("f2.pdf", source_sha256="h2", vendor_name="Sysco", invoice_no="INV-1", grand_total=Decimal("100.01"))

    invoices, duplicates = deduplicate_invoices([inv1, inv2])
    assert len(duplicates) == 0
    assert not any(i.is_duplicate for i in invoices)


def test_different_vendor_not_duplicate():
    """Different vendors with same invoice_no and total -> not duplicate."""
    inv1 = _make_invoice("f1.pdf", source_sha256="h1", vendor_name="Sysco", invoice_no="INV-1", grand_total=Decimal("100.00"))
    inv2 = _make_invoice("f2.pdf", source_sha256="h2", vendor_name="Baldor", invoice_no="INV-1", grand_total=Decimal("100.00"))

    invoices, duplicates = deduplicate_invoices([inv1, inv2])
    assert len(duplicates) == 0
    assert not any(i.is_duplicate for i in invoices)


def test_missing_fields_do_not_match_compound_key():
    """Invoices with None for invoice_no, grand_total, or vendor_name should not match compound key."""
    inv1 = CanonicalInvoice(
        source_file="f1.pdf",
        source_sha256="h1",
        vendor_name="Sysco",
        invoice_no=None,
        grand_total=Decimal("100.00"),
    )
    inv2 = CanonicalInvoice(
        source_file="f2.pdf",
        source_sha256="h2",
        vendor_name="Sysco",
        invoice_no=None,
        grand_total=Decimal("100.00"),
    )

    invoices, duplicates = deduplicate_invoices([inv1, inv2])
    assert len(duplicates) == 0
    assert not any(i.is_duplicate for i in invoices)


# ---------------------------------------------------------------------------
# 6. Edge cases and helpers
# ---------------------------------------------------------------------------

def test_empty_invoices_list():
    """Empty invoice list returns empty outputs."""
    invoices, duplicates = deduplicate_invoices([])
    assert invoices == []
    assert duplicates == []


def test_single_invoice():
    """Single invoice is never a duplicate."""
    inv = _make_invoice("f1.pdf")
    invoices, duplicates = deduplicate_invoices([inv])
    assert len(invoices) == 1
    assert duplicates == []
    assert invoices[0].is_duplicate is False


def test_vendor_similarity_helper():
    """Unit test for is_vendor_similar logic."""
    assert is_vendor_similar("Chefs Warehouse", "The Chefs Warehouse") is True
    assert is_vendor_similar("The Chefs' Warehouse", "Chefs Warehouse") is True
    assert is_vendor_similar("Sysco Foods", "Sysco Food") is True
    assert is_vendor_similar("US Foods Inc.", "US Foods") is True
    assert is_vendor_similar("Sysco", "Baldor") is False
    assert is_vendor_similar(None, "Sysco") is False
    assert is_vendor_similar("Sysco", "") is False


def test_normalize_helpers():
    """Unit tests for string normalization helpers."""
    assert normalize_vendor_name("  The Chefs  Warehouse! ") == "the chefs  warehouse"
    assert normalize_vendor_name(None) == ""
    assert normalize_invoice_no(" #INV-909 ") == "INV-909"
    assert normalize_invoice_no(None) == ""


def test_preserves_original_status_on_non_duplicate():
    """Invoices that are not duplicates should retain their original status."""
    inv1 = _make_invoice("f1.pdf", status=InvoiceStatus.VERIFIED)
    inv2 = _make_invoice("f2.pdf", invoice_no="INV-002", status=InvoiceStatus.REVIEW_NEEDED)

    invoices, _ = deduplicate_invoices([inv1, inv2])
    assert invoices[0].status == InvoiceStatus.VERIFIED
    assert invoices[1].status == InvoiceStatus.REVIEW_NEEDED


def test_custom_similarity_threshold():
    """Custom similarity threshold allows stricter or looser matching."""
    # Stricter threshold (99) should reject minor differences
    inv1 = _make_invoice("f1.pdf", vendor_name="Sysco Foods", invoice_no="INV-1", grand_total=Decimal("10"))
    inv2 = _make_invoice("f2.pdf", vendor_name="Sysco Food", invoice_no="INV-1", grand_total=Decimal("10"))

    # At threshold 90, it matches (ratio is ~95%)
    _, dups_90 = deduplicate_invoices([inv1, inv2], similarity_threshold=90)
    assert len(dups_90) == 1

    # At threshold 99, it should not match
    inv1_b = _make_invoice("f1.pdf", vendor_name="Sysco Foods", invoice_no="INV-1", grand_total=Decimal("10"))
    inv2_b = _make_invoice("f2.pdf", vendor_name="Sysco Food", invoice_no="INV-1", grand_total=Decimal("10"))
    _, dups_99 = deduplicate_invoices([inv1_b, inv2_b], similarity_threshold=99)
    assert len(dups_99) == 0


def test_mixed_duplicates():
    """Mixed batch: some exact sha256, some compound key, some unique."""
    inv_orig1 = _make_invoice("orig1.pdf", source_sha256="hash_a", vendor_name="Vendor A", invoice_no="A-1", grand_total=Decimal("50"))
    inv_dup_sha = _make_invoice("dup_sha.pdf", source_sha256="hash_a", vendor_name="Different Name", invoice_no="X-99", grand_total=Decimal("999"))
    inv_orig2 = _make_invoice("orig2.pdf", source_sha256="hash_b", vendor_name="The Chefs Warehouse", invoice_no="CW-001", grand_total=Decimal("200"))
    inv_dup_key = _make_invoice("dup_key.pdf", source_sha256="hash_c", vendor_name="Chefs Warehouse", invoice_no="cw-001", grand_total=Decimal("200"))
    inv_unique = _make_invoice("unique.pdf", source_sha256="hash_d", vendor_name="Vendor D", invoice_no="D-1", grand_total=Decimal("15"))

    invoices, duplicates = deduplicate_invoices([inv_orig1, inv_dup_sha, inv_orig2, inv_dup_key, inv_unique])

    assert len(duplicates) == 2
    assert duplicates[0] == ("dup_sha.pdf", "orig1.pdf", "exact_sha256")
    assert duplicates[1] == ("dup_key.pdf", "orig2.pdf", "compound_key")

    assert inv_orig1.is_duplicate is False
    assert inv_dup_sha.is_duplicate is True
    assert inv_dup_sha.duplicate_of == "orig1.pdf"

    assert inv_orig2.is_duplicate is False
    assert inv_dup_key.is_duplicate is True
    assert inv_dup_key.duplicate_of == "orig2.pdf"

    assert inv_unique.is_duplicate is False

