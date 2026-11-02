"""Comprehensive test suite for core/validator.py.

PLAN 5.5: Tests status assignment for VERIFIED, REVIEW_NEEDED, and FAILED.
INVARIANTS:
1. Tests must NEVER access real invoice files.
2. Invariant: NEVER assign VERIFIED when mandatory checks are missing or failed.
3. No raw sensitive numbers exposed in review reasons.
"""

from decimal import Decimal
from unittest.mock import patch
import pytest

from config import MIN_CHECKABLE_LINE_RATIO, OCR_CONFIDENCE_THRESHOLD
from core.types import Provenance
from core.validator import (
    assign_invoice_status,
    check_low_confidence_numbers,
    is_auto_doc_type,
    is_fatal_flag,
    is_forbidden_flag,
)
from models.schema import (
    CanonicalCharge,
    CanonicalInvoice,
    CanonicalLineItem,
    DocType,
    InvoiceStatus,
    LineItemKind,
)


def make_prov(conf: float = 1.0, page: int = 1) -> Provenance:
    """Helper to create synthetic provenance."""
    return Provenance(
        page=page,
        bbox=(10.0, 10.0, 100.0, 20.0),
        ocr_conf=conf,
        source="ocr" if conf < 1.0 else "pdf_text",
    )


def make_line(
    name: str = "Item",
    qty: str = "2",
    unit_price: str = "5.00",
    line_total: str = "10.00",
    checkable: bool = True,
    conf: float = 1.0,
) -> CanonicalLineItem:
    """Helper to create a synthetic line item."""
    return CanonicalLineItem(
        item_name=name,
        qty=Decimal(qty) if qty is not None else None,
        qty_prov=make_prov(conf) if qty is not None else None,
        unit_price=Decimal(unit_price) if unit_price is not None else None,
        unit_price_prov=make_prov(conf) if unit_price is not None else None,
        line_total=Decimal(line_total) if line_total is not None else None,
        line_total_prov=make_prov(conf) if line_total is not None else None,
        checkable=checkable,
    )


def make_goods_invoice(
    subtotal: str = "20.00",
    grand_total: str = "20.00",
    tax: str = "0.00",
    conf: float = 1.0,
    line_count: int = 2,
) -> CanonicalInvoice:
    """Helper to create a synthetic valid goods invoice."""
    lines = [
        make_line(
            name=f"Item {i}",
            qty="1",
            unit_price="10.00",
            line_total="10.00",
            checkable=True,
            conf=conf,
        )
        for i in range(1, line_count + 1)
    ]
    return CanonicalInvoice(
        source_file="synthetic_goods_invoice.pdf",
        source_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        status=InvoiceStatus.REVIEW_NEEDED,
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="Acme Corp",
        invoice_no="INV-1001",
        invoice_date="2026-08-01",
        due_date="2026-08-15",
        currency="USD",
        line_items=lines,
        subtotal=Decimal(subtotal),
        subtotal_prov=make_prov(conf),
        tax=Decimal(tax) if tax is not None else None,
        tax_prov=make_prov(conf) if tax is not None else None,
        grand_total=Decimal(grand_total),
        grand_total_prov=make_prov(conf),
    )


def make_utility_invoice(
    amount_due: str = "150.00",
    conf: float = 1.0,
) -> CanonicalInvoice:
    """Helper to create a synthetic utility bill."""
    charges = [
        CanonicalCharge(
            description="Base delivery",
            amount=Decimal("50.00"),
            amount_prov=make_prov(conf),
        ),
        CanonicalCharge(
            description="Supply charge",
            amount=Decimal("100.00"),
            amount_prov=make_prov(conf),
        ),
    ]
    return CanonicalInvoice(
        source_file="synthetic_utility.pdf",
        source_sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        status=InvoiceStatus.REVIEW_NEEDED,
        doc_type=DocType.UTILITY_BILL,
        vendor_name="Power Grid Co",
        invoice_no="UTIL-999",
        invoice_date="2026-08-01",
        due_date="2026-08-20",
        currency="USD",
        charges=charges,
        amount_due=Decimal(amount_due),
        amount_due_prov=make_prov(conf),
    )


# =============================================================================
# Helper function unit tests
# =============================================================================

def test_is_auto_doc_type():
    assert is_auto_doc_type(DocType.GOODS_INVOICE) is True
    assert is_auto_doc_type(DocType.RECEIPT) is True
    assert is_auto_doc_type(DocType.UTILITY_BILL) is True
    assert is_auto_doc_type(DocType.CREDIT_MEMO) is True
    assert is_auto_doc_type(DocType.STATEMENT) is False
    assert is_auto_doc_type(DocType.OTHER) is False
    assert is_auto_doc_type("goods_invoice") is True
    assert is_auto_doc_type("utility_bill") is True
    assert is_auto_doc_type("unknown_type") is False
    assert is_auto_doc_type(None) is False


def test_is_fatal_flag():
    assert is_fatal_flag("file_unreadable") is True
    assert is_fatal_flag("ocr_failed: engine crash") is True
    assert is_fatal_flag("llm_error: timeout") is True
    assert is_fatal_flag("fatal_error") is True
    assert is_fatal_flag("unknown_token") is False
    assert is_fatal_flag("ambiguous_date") is False


def test_is_forbidden_flag():
    assert is_forbidden_flag("unknown_token") is True
    assert is_forbidden_flag("unknown_token: <N_99>") is True
    assert is_forbidden_flag("duplicate_token: <N_1>") is True
    assert is_forbidden_flag("orphan_money_tokens") is True
    assert is_forbidden_flag("ambiguous_date") is True
    assert is_forbidden_flag("ambiguous_amount") is True
    assert is_forbidden_flag("multi_invoice_suspected") is True
    assert is_forbidden_flag("low_conf") is True
    assert is_forbidden_flag("low_confidence") is True
    assert is_forbidden_flag("file_unreadable") is True
    assert is_forbidden_flag("clean_run") is False


def test_assign_invoice_status_none_raises():
    with pytest.raises(ValueError, match="cannot be None"):
        assign_invoice_status(None)  # type: ignore[arg-type]


# =============================================================================
# VERIFIED test cases
# =============================================================================

@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_verified_standard_goods_invoice(mock_t1, mock_t2, mock_t3, mock_meta):
    """Test standard goods invoice passes all checks to become VERIFIED."""
    inv = make_goods_invoice()
    result = assign_invoice_status(inv, rehydrator_flags=None, target_month="2026-08")
    assert result.status == InvoiceStatus.VERIFIED
    assert result.review_reasons == []


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 4, 1))
def test_verified_goods_invoice_at_80_percent_checkable_lines(mock_t1, mock_t2, mock_t3, mock_meta):
    """Test goods invoice with exactly 80% checkable lines (4/5) is VERIFIED."""
    # 5 line items total
    lines = [make_line(f"Item {i}", checkable=(i <= 4)) for i in range(1, 6)]
    inv = make_goods_invoice()
    inv.line_items = lines
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.VERIFIED
    assert result.review_reasons == []


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 9, 1))
def test_verified_goods_invoice_above_80_percent_checkable_lines(mock_t1, mock_t2, mock_t3, mock_meta):
    """Test goods invoice with 90% checkable lines (9/10) is VERIFIED."""
    lines = [make_line(f"Item {i}", checkable=(i <= 9)) for i in range(1, 11)]
    inv = make_goods_invoice()
    inv.line_items = lines
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.VERIFIED
    assert result.review_reasons == []


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier4_utility_total", return_value=(True, []))
def test_verified_utility_bill(mock_t4, mock_meta):
    """Test utility bill without lines passing Tier 4 is VERIFIED."""
    inv = make_utility_invoice()
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.VERIFIED
    assert result.review_reasons == []


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_verified_credit_memo(mock_t1, mock_t2, mock_t3, mock_meta):
    """Test credit memo with negative total passing Tier 3 is VERIFIED."""
    inv = make_goods_invoice(subtotal="-20.00", grand_total="-20.00")
    inv.doc_type = DocType.CREDIT_MEMO
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.VERIFIED
    assert result.review_reasons == []


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 1, 0))
def test_verified_receipt_with_lines(mock_t1, mock_t2, mock_t3, mock_meta):
    """Test receipt with itemized lines passing Tier 1, 2, 3 is VERIFIED."""
    inv = make_goods_invoice(subtotal="10.00", grand_total="10.00", line_count=1)
    inv.doc_type = DocType.RECEIPT
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.VERIFIED
    assert result.review_reasons == []


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier4_utility_total", return_value=(True, []))
def test_verified_receipt_without_subtotal_using_charges(mock_t4, mock_meta):
    """Test receipt without subtotal having charges passing Tier 4 is VERIFIED."""
    inv = make_utility_invoice()
    inv.doc_type = DocType.RECEIPT
    inv.subtotal = None
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.VERIFIED
    assert result.review_reasons == []


# =============================================================================
# REVIEW_NEEDED: Tier failures
# =============================================================================

@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(False, ["Line 1: math mismatch"], 2, 0))
def test_review_needed_tier1_math_error(mock_t1, mock_t2, mock_t3, mock_meta):
    """Tier 1 math failure forces REVIEW_NEEDED."""
    inv = make_goods_invoice()
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Line 1: math mismatch" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 3, 2))
def test_review_needed_checkable_ratio_below_80_percent(mock_t1, mock_t2, mock_t3, mock_meta):
    """Checkable ratio 3/5 = 60% < 80% forces REVIEW_NEEDED."""
    lines = [make_line(f"Item {i}", checkable=(i <= 3)) for i in range(1, 6)]
    inv = make_goods_invoice()
    inv.line_items = lines
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Checkable lines ratio" in r and "below minimum" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(False, ["Subtotal sum mismatch"]))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_tier2_subtotal_mismatch(mock_t1, mock_t2, mock_t3, mock_meta):
    """Tier 2 subtotal mismatch forces REVIEW_NEEDED."""
    inv = make_goods_invoice()
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Subtotal sum mismatch" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(False, ["Grand total mismatch"]))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_tier3_grand_total_mismatch(mock_t1, mock_t2, mock_t3, mock_meta):
    """Tier 3 grand total mismatch forces REVIEW_NEEDED."""
    inv = make_goods_invoice()
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Grand total mismatch" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier4_utility_total", return_value=(False, ["Charges sum mismatch"]))
def test_review_needed_tier4_utility_mismatch(mock_t4, mock_meta):
    """Tier 4 mismatch on utility bill forces REVIEW_NEEDED."""
    inv = make_utility_invoice()
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Charges sum mismatch" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=["due_date is before invoice_date"])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_date_metadata_error(mock_t1, mock_t2, mock_t3, mock_meta):
    """Date or metadata sanity check failure forces REVIEW_NEEDED."""
    inv = make_goods_invoice()
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("due_date is before invoice_date" in r for r in result.review_reasons)


# =============================================================================
# REVIEW_NEEDED: Invariant - missing mandatory checks must NEVER be VERIFIED
# =============================================================================

def test_invariant_unimplemented_tier_checks_never_verified():
    """Unimplemented tier checks (calling real unmocked stubs) must NEVER assign VERIFIED."""
    inv = make_goods_invoice()
    # On this branch, validator_lines and validator_totals have stubs raising NotImplementedError
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert len(result.review_reasons) > 0
    assert any("not implemented" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", side_effect=NotImplementedError("Tier 1 missing"))
def test_invariant_tier1_not_implemented_forces_review(mock_t1, mock_t2, mock_t3, mock_meta):
    inv = make_goods_invoice()
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Tier 1 line validation not implemented" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", side_effect=NotImplementedError("Tier 3 missing"))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_invariant_tier3_not_implemented_forces_review(mock_t1, mock_t2, mock_t3, mock_meta):
    inv = make_goods_invoice()
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Tier 3 grand total validation not implemented" in r for r in result.review_reasons)


# =============================================================================
# REVIEW_NEEDED: Missing lines or totals
# =============================================================================

@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
def test_review_needed_goods_invoice_missing_lines(mock_t3, mock_meta):
    """Goods invoice without line items cannot be VERIFIED."""
    inv = make_goods_invoice()
    inv.line_items = []
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Missing itemized line items" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_missing_both_tier3_and_tier4(mock_t1, mock_t2, mock_meta):
    """Invoice without grand_total, subtotal, or charges cannot evaluate total tiers."""
    inv = make_goods_invoice()
    inv.subtotal = None
    inv.grand_total = None
    inv.charges = []
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Neither Tier 3" in r for r in result.review_reasons)


# =============================================================================
# REVIEW_NEEDED: Non-auto doc_types
# =============================================================================

@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_doc_type_statement(mock_t1, mock_t2, mock_t3, mock_meta):
    """STATEMENT doc_type is not auto-verified."""
    inv = make_goods_invoice()
    inv.doc_type = DocType.STATEMENT
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("statement" in r and "not an auto-verified" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_doc_type_other(mock_t1, mock_t2, mock_t3, mock_meta):
    """OTHER doc_type is not auto-verified."""
    inv = make_goods_invoice()
    inv.doc_type = DocType.OTHER
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("other" in r and "not an auto-verified" in r for r in result.review_reasons)


# =============================================================================
# REVIEW_NEEDED: Forbidden rehydrator flags
# =============================================================================

@pytest.mark.parametrize(
    "flag",
    [
        "unknown_token: <N_99>",
        "duplicate_token: <N_1>",
        "orphan_money_tokens: page 1 line 4",
        "ambiguous_date: 05/06/2026",
        "ambiguous_amount: 1,000",
        "multi_invoice_suspected: multiple page headers",
        "low_conf: field subtotal",
        "low_confidence_token",
    ],
)
@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_forbidden_flags(mock_t1, mock_t2, mock_t3, mock_meta, flag):
    """Any forbidden flag from rehydration blocks VERIFIED."""
    inv = make_goods_invoice()
    result = assign_invoice_status(inv, rehydrator_flags=[flag])
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert flag in result.review_reasons


# =============================================================================
# REVIEW_NEEDED: Low OCR confidence on participating numbers
# =============================================================================

@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_low_conf_line_qty(mock_t1, mock_t2, mock_t3, mock_meta):
    """Low OCR confidence on line quantity forces REVIEW_NEEDED."""
    inv = make_goods_invoice()
    inv.line_items[0].qty_prov = make_prov(conf=0.75, page=1)
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Low OCR confidence" in r and "line 1 qty" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_low_conf_line_price(mock_t1, mock_t2, mock_t3, mock_meta):
    """Low OCR confidence on line unit price forces REVIEW_NEEDED."""
    inv = make_goods_invoice()
    inv.line_items[0].unit_price_prov = make_prov(conf=0.88, page=1)
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Low OCR confidence" in r and "line 1 unit_price" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_low_conf_line_total(mock_t1, mock_t2, mock_t3, mock_meta):
    """Low OCR confidence on line total forces REVIEW_NEEDED."""
    inv = make_goods_invoice()
    inv.line_items[1].line_total_prov = make_prov(conf=0.80, page=2)
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Low OCR confidence" in r and "line 2 line_total" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_low_conf_subtotal(mock_t1, mock_t2, mock_t3, mock_meta):
    """Low OCR confidence on document subtotal forces REVIEW_NEEDED."""
    inv = make_goods_invoice()
    inv.subtotal_prov = make_prov(conf=0.85, page=1)
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Low OCR confidence" in r and "document subtotal" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_low_conf_grand_total(mock_t1, mock_t2, mock_t3, mock_meta):
    """Low OCR confidence on document grand_total forces REVIEW_NEEDED."""
    inv = make_goods_invoice()
    inv.grand_total_prov = make_prov(conf=0.70, page=1)
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Low OCR confidence" in r and "document grand_total" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_low_conf_tax(mock_t1, mock_t2, mock_t3, mock_meta):
    """Low OCR confidence on document tax forces REVIEW_NEEDED."""
    inv = make_goods_invoice()
    inv.tax = Decimal("1.50")
    inv.tax_prov = make_prov(conf=0.70, page=1)
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Low OCR confidence" in r and "document tax" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_low_conf_shipping(mock_t1, mock_t2, mock_t3, mock_meta):
    """Low OCR confidence on document shipping forces REVIEW_NEEDED."""
    inv = make_goods_invoice()
    inv.shipping = Decimal("5.00")
    inv.shipping_prov = make_prov(conf=0.60, page=1)
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Low OCR confidence" in r and "document shipping" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_low_conf_discount(mock_t1, mock_t2, mock_t3, mock_meta):
    """Low OCR confidence on document discount forces REVIEW_NEEDED."""
    inv = make_goods_invoice()
    inv.discount = Decimal("2.00")
    inv.discount_prov = make_prov(conf=0.75, page=1)
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Low OCR confidence" in r and "document discount" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_review_needed_low_conf_tip(mock_t1, mock_t2, mock_t3, mock_meta):
    """Low OCR confidence on document tip forces REVIEW_NEEDED."""
    inv = make_goods_invoice()
    inv.tip = Decimal("3.00")
    inv.tip_prov = make_prov(conf=0.80, page=1)
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Low OCR confidence" in r and "document tip" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier4_utility_total", return_value=(True, []))
def test_review_needed_low_conf_utility_charge_amount(mock_t4, mock_meta):
    """Low OCR confidence on utility charge amount forces REVIEW_NEEDED."""
    inv = make_utility_invoice()
    inv.charges[0].amount_prov = make_prov(conf=0.65, page=1)
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Low OCR confidence" in r and "charge" in r for r in result.review_reasons)


@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier4_utility_total", return_value=(True, []))
def test_review_needed_low_conf_amount_due(mock_t4, mock_meta):
    """Low OCR confidence on amount_due forces REVIEW_NEEDED."""
    inv = make_utility_invoice()
    inv.amount_due_prov = make_prov(conf=0.89, page=1)
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.REVIEW_NEEDED
    assert any("Low OCR confidence" in r and "document amount_due" in r for r in result.review_reasons)


# =============================================================================
# FAILED status test cases
# =============================================================================

def test_failed_when_already_failed():
    """An invoice already marked FAILED retains FAILED status."""
    inv = make_goods_invoice()
    inv.status = InvoiceStatus.FAILED
    inv.review_reasons = ["OCR engine failure on page 1"]
    result = assign_invoice_status(inv)
    assert result.status == InvoiceStatus.FAILED
    assert "OCR engine failure on page 1" in result.review_reasons


@pytest.mark.parametrize(
    "flag",
    [
        "file_unreadable: corrupt PDF",
        "ocr_failed: timeout after 60s",
        "ocr_error: unreadable scan",
        "llm_failed: 429 quota exhausted",
        "llm_error: malformed response",
        "fatal: out of memory",
        "failed_to_extract_text",
    ],
)
def test_failed_on_fatal_rehydrator_flags(flag):
    """Fatal flags in rehydrator_flags assign InvoiceStatus.FAILED."""
    inv = make_goods_invoice()
    result = assign_invoice_status(inv, rehydrator_flags=[flag])
    assert result.status == InvoiceStatus.FAILED
    assert flag in result.review_reasons


# =============================================================================
# Privacy and Logging Invariants
# =============================================================================

@patch("core.validator.validate_dates_and_metadata", return_value=[])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_privacy_no_raw_numbers_in_system_review_reasons(mock_t1, mock_t2, mock_t3, mock_meta):
    """Review reasons generated by validator must NOT expose raw dollar values."""
    inv = make_goods_invoice(subtotal="12345.67", grand_total="12345.67")
    inv.subtotal_prov = make_prov(conf=0.60)
    result = assign_invoice_status(inv)
    for reason in result.review_reasons:
        # Check that the raw dollar value "12345.67" is NOT leaked in the reason string
        assert "12345.67" not in reason
        assert "12,345" not in reason


# =============================================================================
# Idempotency and Deduplication
# =============================================================================

@patch("core.validator.validate_dates_and_metadata", return_value=["Date warning"])
@patch("core.validator.validate_tier3_grand_total", return_value=(True, []))
@patch("core.validator.validate_tier2_subtotal", return_value=(True, []))
@patch("core.validator.validate_tier1_lines", return_value=(True, [], 2, 0))
def test_assign_invoice_status_idempotent(mock_t1, mock_t2, mock_t3, mock_meta):
    """Calling assign_invoice_status multiple times does not produce duplicate reasons."""
    inv = make_goods_invoice()
    res1 = assign_invoice_status(inv)
    count1 = len(res1.review_reasons)
    res2 = assign_invoice_status(res1)
    count2 = len(res2.review_reasons)
    assert count1 == count2
    assert res1.status == res2.status
