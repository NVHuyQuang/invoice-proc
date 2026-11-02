"""Unit tests for validator_totals (Tiers 3 & 4 + Date and Metadata Checks).

Covers PLAN 5.4:
- Tier 3: validate_tier3_grand_total (|subtotal + tax + shipping + tip + fees - discount - grand_total| <= 0.02)
  * multiple tax lines
  * credit memos
  * shipping, tip, fees, discount
  * tolerance boundaries
  * missing values
- Tier 4: validate_tier4_utility_total (|sum(charges) - amount_due| <= 0.02)
  * utility bills with charges
  * previous balance and payments (signed vs positive description)
  * line items fallback
  * tolerance boundaries
- Additional checks: validate_dates_and_metadata
  * grand_total > 0 check (and credit_memo exception)
  * due_date >= invoice_date check
  * invoice_date within target_month +- DATE_WINDOW_DAYS (45 days)
  * various date formats and error handling
"""

from decimal import Decimal
import pytest

from config import DATE_WINDOW_DAYS, TIER3_TOLERANCE, TIER4_TOLERANCE
from models.schema import (
    CanonicalCharge,
    CanonicalInvoice,
    CanonicalLineItem,
    DocType,
    InvoiceStatus,
    LineItemKind,
)
from core.validator_totals import (
    validate_tier3_grand_total,
    validate_tier4_utility_total,
    validate_dates_and_metadata,
)


def _make_invoice(**kwargs) -> CanonicalInvoice:
    """Helper to create a CanonicalInvoice with default required fields."""
    defaults = {
        "source_file": "synthetic_invoice.pdf",
        "source_sha256": "abcdef1234567890",
        "status": InvoiceStatus.REVIEW_NEEDED,
        "doc_type": DocType.GOODS_INVOICE,
    }
    defaults.update(kwargs)
    return CanonicalInvoice(**defaults)


# =========================================================================
# Tier 3 Tests (Grand Total)
# =========================================================================

def test_tier3_exact_match():
    inv = _make_invoice(
        subtotal=Decimal("100.00"),
        tax=Decimal("8.50"),
        shipping=Decimal("10.00"),
        tip=Decimal("2.00"),
        fees=[Decimal("3.00"), Decimal("1.50")],
        discount=Decimal("5.00"),
        grand_total=Decimal("120.00"),  # 100 + 8.5 + 10 + 2 + 4.5 - 5 = 120.00
    )
    is_valid, errors = validate_tier3_grand_total(inv)
    assert is_valid is True
    assert errors == []


def test_tier3_within_tolerance():
    inv = _make_invoice(
        subtotal=Decimal("100.00"),
        tax=Decimal("10.00"),
        grand_total=Decimal("110.02"),  # diff = 0.02 == TIER3_TOLERANCE
    )
    is_valid, errors = validate_tier3_grand_total(inv)
    assert is_valid is True
    assert errors == []


def test_tier3_outside_tolerance():
    inv = _make_invoice(
        subtotal=Decimal("100.00"),
        tax=Decimal("10.00"),
        grand_total=Decimal("110.03"),  # diff = 0.03 > 0.02
    )
    is_valid, errors = validate_tier3_grand_total(inv)
    assert is_valid is False
    assert len(errors) == 1
    assert "mismatch" in errors[0]


def test_tier3_missing_subtotal():
    inv = _make_invoice(
        subtotal=None,
        tax=Decimal("5.00"),
        grand_total=Decimal("105.00"),
    )
    is_valid, errors = validate_tier3_grand_total(inv)
    assert is_valid is False
    assert any("subtotal" in err for err in errors)


def test_tier3_missing_grand_total():
    inv = _make_invoice(
        subtotal=Decimal("100.00"),
        tax=Decimal("5.00"),
        grand_total=None,
    )
    is_valid, errors = validate_tier3_grand_total(inv)
    assert is_valid is False
    assert any("grand_total" in err for err in errors)


def test_tier3_multiple_tax_lines_without_summary_tax():
    # Invoices where taxes are listed only as separate line items
    inv = _make_invoice(
        subtotal=Decimal("200.00"),
        tax=None,
        line_items=[
            CanonicalLineItem(item_name="Steak", line_total=Decimal("200.00"), kind=LineItemKind.GOODS),
            CanonicalLineItem(item_name="State Tax", line_total=Decimal("12.00"), kind=LineItemKind.TAX_LINE),
            CanonicalLineItem(item_name="County Tax", line_total=Decimal("4.00"), kind=LineItemKind.TAX_LINE),
            CanonicalLineItem(item_name="City Tax", line_total=Decimal("2.50"), kind=LineItemKind.TAX_LINE),
        ],
        grand_total=Decimal("218.50"),  # 200 + 12 + 4 + 2.5 = 218.50
    )
    is_valid, errors = validate_tier3_grand_total(inv)
    assert is_valid is True
    assert errors == []


def test_tier3_multiple_tax_lines_with_matching_summary_tax():
    # Invoices where tax is both in line items AND summarized in header
    inv = _make_invoice(
        subtotal=Decimal("100.00"),
        tax=Decimal("8.25"),  # Matches sum of tax lines (should not double count)
        line_items=[
            CanonicalLineItem(item_name="Goods", line_total=Decimal("100.00"), kind=LineItemKind.GOODS),
            CanonicalLineItem(item_name="Tax 1", line_total=Decimal("6.00"), kind=LineItemKind.TAX_LINE),
            CanonicalLineItem(item_name="Tax 2", line_total=Decimal("2.25"), kind=LineItemKind.TAX_LINE),
        ],
        grand_total=Decimal("108.25"),
    )
    is_valid, errors = validate_tier3_grand_total(inv)
    assert is_valid is True
    assert errors == []


def test_tier3_multiple_tax_lines_additive_summary_tax():
    # Invoice where summary tax is in addition to tax line
    inv = _make_invoice(
        subtotal=Decimal("100.00"),
        tax=Decimal("3.00"),
        line_items=[
            CanonicalLineItem(item_name="Tax line", line_total=Decimal("5.00"), kind=LineItemKind.TAX_LINE),
        ],
        grand_total=Decimal("108.00"),  # 100 + 5 + 3 = 108.00
    )
    is_valid, errors = validate_tier3_grand_total(inv)
    assert is_valid is True
    assert errors == []


def test_tier3_shipping_from_line_item():
    inv = _make_invoice(
        subtotal=Decimal("50.00"),
        shipping=None,
        line_items=[
            CanonicalLineItem(item_name="Item", line_total=Decimal("50.00"), kind=LineItemKind.GOODS),
            CanonicalLineItem(item_name="FedEx Shipping", line_total=Decimal("15.00"), kind=LineItemKind.SHIPPING),
        ],
        grand_total=Decimal("65.00"),
    )
    is_valid, errors = validate_tier3_grand_total(inv)
    assert is_valid is True
    assert errors == []


def test_tier3_negative_discount_handling():
    # Discount passed as negative decimal should still be subtracted
    inv = _make_invoice(
        subtotal=Decimal("100.00"),
        discount=Decimal("-20.00"),
        grand_total=Decimal("80.00"),
    )
    is_valid, errors = validate_tier3_grand_total(inv)
    assert is_valid is True
    assert errors == []


def test_tier3_credit_memo_positive_components_negative_grand_total():
    # Credit memo where line items/subtotal are positive but grand_total is negative
    inv = _make_invoice(
        doc_type=DocType.CREDIT_MEMO,
        subtotal=Decimal("100.00"),
        tax=Decimal("8.00"),
        grand_total=Decimal("-108.00"),
    )
    is_valid, errors = validate_tier3_grand_total(inv)
    assert is_valid is True
    assert errors == []


def test_tier3_credit_memo_all_negative_values():
    # Credit memo where all numbers are negative
    inv = _make_invoice(
        doc_type=DocType.CREDIT_MEMO,
        subtotal=Decimal("-100.00"),
        tax=Decimal("-8.00"),
        grand_total=Decimal("-108.00"),
    )
    is_valid, errors = validate_tier3_grand_total(inv)
    assert is_valid is True
    assert errors == []


def test_tier3_credit_memo_positive_credit_amount():
    # Credit memo where subtotal is negative but total is stated as positive credit
    inv = _make_invoice(
        doc_type=DocType.CREDIT_MEMO,
        subtotal=Decimal("-100.00"),
        tax=Decimal("-8.00"),
        grand_total=Decimal("108.00"),
    )
    is_valid, errors = validate_tier3_grand_total(inv)
    assert is_valid is True
    assert errors == []


# =========================================================================
# Tier 4 Tests (Utility Bills / Charges)
# =========================================================================

def test_tier4_standard_utility_charges():
    inv = _make_invoice(
        doc_type=DocType.UTILITY_BILL,
        charges=[
            CanonicalCharge(description="Electricity supply", amount=Decimal("72.50")),
            CanonicalCharge(description="Gas delivery", amount=Decimal("35.00")),
            CanonicalCharge(description="Regulatory surcharge", amount=Decimal("4.25")),
        ],
        amount_due=Decimal("111.75"),
    )
    is_valid, errors = validate_tier4_utility_total(inv)
    assert is_valid is True
    assert errors == []


def test_tier4_within_and_outside_tolerance():
    inv_pass = _make_invoice(
        doc_type=DocType.UTILITY_BILL,
        charges=[CanonicalCharge(description="Power", amount=Decimal("100.00"))],
        amount_due=Decimal("100.02"),  # diff = 0.02 <= 0.02
    )
    assert validate_tier4_utility_total(inv_pass)[0] is True

    inv_fail = _make_invoice(
        doc_type=DocType.UTILITY_BILL,
        charges=[CanonicalCharge(description="Power", amount=Decimal("100.00"))],
        amount_due=Decimal("100.03"),  # diff = 0.03 > 0.02
    )
    assert validate_tier4_utility_total(inv_fail)[0] is False


def test_tier4_with_previous_balance_and_signed_payment():
    # Previous balance 85.00, Payment -85.00, New charges 120.00 -> Amount due 120.00
    inv = _make_invoice(
        doc_type=DocType.UTILITY_BILL,
        charges=[
            CanonicalCharge(description="Previous balance", amount=Decimal("85.00")),
            CanonicalCharge(description="Payment received", amount=Decimal("-85.00")),
            CanonicalCharge(description="Current electric charges", amount=Decimal("120.00")),
        ],
        amount_due=Decimal("120.00"),
    )
    is_valid, errors = validate_tier4_utility_total(inv)
    assert is_valid is True
    assert errors == []


def test_tier4_with_positive_payment_in_description():
    # OCR parsed payment as positive number 85.00 with "Payment - Thank You"
    inv = _make_invoice(
        doc_type=DocType.UTILITY_BILL,
        charges=[
            CanonicalCharge(description="Previous Balance", amount=Decimal("85.00")),
            CanonicalCharge(description="Payment Received - Thank You", amount=Decimal("85.00")),
            CanonicalCharge(description="Current Charges", amount=Decimal("120.00")),
        ],
        amount_due=Decimal("120.00"),
    )
    is_valid, errors = validate_tier4_utility_total(inv)
    assert is_valid is True
    assert errors == []


def test_tier4_charges_from_line_items_fallback():
    # When charges list is empty but line_items has receipt charges
    inv = _make_invoice(
        doc_type=DocType.RECEIPT,
        line_items=[
            CanonicalLineItem(item_name="Charge A", line_total=Decimal("40.00")),
            CanonicalLineItem(item_name="Charge B", line_total=Decimal("60.00")),
        ],
        amount_due=Decimal("100.00"),
    )
    is_valid, errors = validate_tier4_utility_total(inv)
    assert is_valid is True
    assert errors == []


def test_tier4_fallback_to_grand_total_when_amount_due_none():
    inv = _make_invoice(
        doc_type=DocType.UTILITY_BILL,
        charges=[CanonicalCharge(description="Utility", amount=Decimal("55.00"))],
        amount_due=None,
        grand_total=Decimal("55.00"),
    )
    is_valid, errors = validate_tier4_utility_total(inv)
    assert is_valid is True
    assert errors == []


def test_tier4_missing_targets_or_charges():
    inv_no_target = _make_invoice(
        charges=[CanonicalCharge(description="Utility", amount=Decimal("55.00"))],
        amount_due=None,
        grand_total=None,
    )
    assert validate_tier4_utility_total(inv_no_target)[0] is False

    inv_no_charges = _make_invoice(
        charges=[],
        line_items=[],
        amount_due=Decimal("55.00"),
    )
    assert validate_tier4_utility_total(inv_no_charges)[0] is False


# =========================================================================
# Additional Checks (Dates & Metadata)
# =========================================================================

def test_dates_due_date_after_or_equal_invoice_date():
    inv1 = _make_invoice(
        invoice_date="2026-08-01",
        due_date="2026-08-31",
        grand_total=Decimal("100.00"),
    )
    assert validate_dates_and_metadata(inv1) == []

    inv2 = _make_invoice(
        invoice_date="2026-08-01",
        due_date="2026-08-01",
        grand_total=Decimal("100.00"),
    )
    assert validate_dates_and_metadata(inv2) == []


def test_dates_due_date_before_invoice_date():
    inv = _make_invoice(
        invoice_date="2026-08-15",
        due_date="2026-08-10",
        grand_total=Decimal("100.00"),
    )
    errors = validate_dates_and_metadata(inv)
    assert len(errors) == 1
    assert "cannot be before invoice_date" in errors[0]


def test_dates_different_formats():
    inv = _make_invoice(
        invoice_date="08/01/2026",
        due_date="Aug 25, 2026",
        grand_total=Decimal("50.00"),
    )
    assert validate_dates_and_metadata(inv) == []


def test_dates_target_month_within_45_days():
    # Target month: 2026-08 (August 2026)
    # Window is 2026-08-01 - 45d (2026-06-17) to 2026-08-31 + 45d (2026-10-15)

    # In August
    inv1 = _make_invoice(invoice_date="2026-08-15", grand_total=Decimal("10.00"))
    assert validate_dates_and_metadata(inv1, target_month="2026-08") == []

    # Late July (within 45 days)
    inv2 = _make_invoice(invoice_date="2026-07-05", grand_total=Decimal("10.00"))
    assert validate_dates_and_metadata(inv2, target_month="2026-08") == []

    # Late September (within 45 days)
    inv3 = _make_invoice(invoice_date="2026-09-25", grand_total=Decimal("10.00"))
    assert validate_dates_and_metadata(inv3, target_month="2026-08") == []


def test_dates_target_month_outside_45_days():
    # Outside earlier (> 45 days before Aug 1: June 16, 2026)
    inv_early = _make_invoice(invoice_date="2026-06-16", grand_total=Decimal("10.00"))
    errors_early = validate_dates_and_metadata(inv_early, target_month="2026-08")
    assert any("outside target month" in e for e in errors_early)

    # Outside later (> 45 days after Aug 31: Oct 16, 2026)
    inv_late = _make_invoice(invoice_date="2026-10-16", grand_total=Decimal("10.00"))
    errors_late = validate_dates_and_metadata(inv_late, target_month="2026-08")
    assert any("outside target month" in e for e in errors_late)


def test_metadata_grand_total_positive_for_standard_invoices():
    inv_neg = _make_invoice(
        doc_type=DocType.GOODS_INVOICE,
        grand_total=Decimal("-50.00"),
    )
    errors_neg = validate_dates_and_metadata(inv_neg)
    assert any("grand_total must be > 0" in e for e in errors_neg)

    inv_zero = _make_invoice(
        doc_type=DocType.RECEIPT,
        grand_total=Decimal("0.00"),
    )
    errors_zero = validate_dates_and_metadata(inv_zero)
    assert any("grand_total must be > 0" in e for e in errors_zero)


def test_metadata_credit_memo_negative_grand_total_allowed():
    inv_cm = _make_invoice(
        doc_type=DocType.CREDIT_MEMO,
        grand_total=Decimal("-50.00"),
    )
    errors = validate_dates_and_metadata(inv_cm)
    assert errors == []


def test_metadata_credit_memo_zero_grand_total_allowed():
    inv_cm = _make_invoice(
        doc_type=DocType.CREDIT_MEMO,
        grand_total=Decimal("0.00"),
    )
    errors = validate_dates_and_metadata(inv_cm)
    assert errors == []


def test_dates_unparseable_strings():
    inv = _make_invoice(
        invoice_date="not-a-real-date",
        due_date="also-invalid",
        grand_total=Decimal("10.00"),
    )
    errors = validate_dates_and_metadata(inv)
    assert any("Unparseable" in e for e in errors)
