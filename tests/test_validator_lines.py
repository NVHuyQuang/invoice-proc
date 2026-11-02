"""Tests for core/validator_lines.py (PLAN 5.4 Tiers 1 and 2).

Verifies:
- Tier 1: individual line items with tolerance 0.01 + 0.005 * |qty|.
  Weighted goods, missing qty/price, non-goods items, returns.
- Tier 2: subtotal validation with tolerance 0.02 + 0.005 * n_lines.
  Signed discounts, fees, missing subtotal ('no_subtotal'), rounding tolerances.
"""

from decimal import Decimal
import pytest

from config import (
    TIER1_BASE_TOLERANCE,
    TIER1_QTY_FACTOR,
    TIER2_BASE_TOLERANCE,
    TIER2_LINE_FACTOR,
)
from core.validator_lines import validate_tier1_lines, validate_tier2_subtotal
from models.schema import CanonicalInvoice, CanonicalLineItem, LineItemKind


# =============================================================================
# Tier 1 Tests: Individual Line Items
# =============================================================================

def test_tier1_standard_goods_exact():
    """Exact arithmetic matches should pass with 0 errors."""
    items = [
        CanonicalLineItem(
            item_name="Whole Milk",
            qty=Decimal("2"),
            unit_price=Decimal("3.50"),
            line_total=Decimal("7.00"),
            kind=LineItemKind.GOODS,
        ),
        CanonicalLineItem(
            item_name="Bread",
            qty=Decimal("1"),
            unit_price=Decimal("2.25"),
            line_total=Decimal("2.25"),
            kind=LineItemKind.GOODS,
        ),
    ]

    all_passed, errors, checkable, uncheckable = validate_tier1_lines(items)
    assert all_passed is True
    assert errors == []
    assert checkable == 2
    assert uncheckable == 0
    assert items[0].checkable is True
    assert items[0].math_error is None
    assert items[1].checkable is True
    assert items[1].math_error is None


def test_tier1_weighted_goods_within_tolerance():
    """Weighted goods (e.g. 1.25 lb) with rounding discrepancies within tolerance pass."""
    # 1.25 lb @ $3.33/lb = 4.1625 -> billed as 4.16
    # diff = 0.0025, tol = 0.01 + 0.005 * 1.25 = 0.01625
    items = [
        CanonicalLineItem(
            item_name="Organic Apples",
            qty=Decimal("1.25"),
            unit_price=Decimal("3.33"),
            line_total=Decimal("4.16"),
            unit="LB",
            kind=LineItemKind.GOODS,
        )
    ]

    all_passed, errors, checkable, uncheckable = validate_tier1_lines(items)
    assert all_passed is True
    assert errors == []
    assert checkable == 1
    assert uncheckable == 0
    assert items[0].checkable is True
    assert items[0].math_error is None


def test_tier1_weighted_goods_large_quantity():
    """Larger weighted quantity scaling tolerance with |qty|."""
    # 15.75 lb @ $12.49/lb = 196.7175 -> billed as 196.75 (diff = 0.0325)
    # tol = 0.01 + 0.005 * 15.75 = 0.01 + 0.07875 = 0.08875
    # diff (0.0325) <= tol (0.08875) -> passes
    items = [
        CanonicalLineItem(
            item_name="Ribeye Steak",
            qty=Decimal("15.75"),
            unit_price=Decimal("12.49"),
            line_total=Decimal("196.75"),
            unit="LB",
            kind=LineItemKind.GOODS,
        )
    ]

    all_passed, errors, checkable, uncheckable = validate_tier1_lines(items)
    assert all_passed is True
    assert errors == []
    assert checkable == 1
    assert uncheckable == 0
    assert items[0].checkable is True


def test_tier1_math_mismatch_fails():
    """Math mismatch exceeding tolerance fails and populates line.math_error."""
    # 2 * 10.00 = 20.00, billed as 25.00 (diff = 5.00 > tol = 0.02)
    items = [
        CanonicalLineItem(
            item_name="Olive Oil",
            qty=Decimal("2"),
            unit_price=Decimal("10.00"),
            line_total=Decimal("25.00"),
            kind=LineItemKind.GOODS,
        )
    ]

    all_passed, errors, checkable, uncheckable = validate_tier1_lines(items)
    assert all_passed is False
    assert len(errors) == 1
    assert "Olive Oil" in errors[0]
    assert "math mismatch" in errors[0]
    # Invariant: error message must not expose raw values
    assert "|2 * 10.00 - 25.00|" not in errors[0]
    assert "25.00" not in errors[0]
    assert "diff:" in errors[0]
    assert checkable == 1
    assert uncheckable == 0
    assert items[0].checkable is True
    assert items[0].math_error is not None
    assert "Olive Oil" in items[0].math_error
    assert "|2 * 10.00 - 25.00|" not in items[0].math_error


def test_tier1_missing_qty():
    """Line missing quantity is marked uncheckable and counted in uncheckable_count."""
    items = [
        CanonicalLineItem(
            item_name="Miscellaneous Deli",
            qty=None,
            unit_price=Decimal("5.50"),
            line_total=Decimal("5.50"),
            kind=LineItemKind.GOODS,
        )
    ]

    all_passed, errors, checkable, uncheckable = validate_tier1_lines(items)
    assert all_passed is True
    assert errors == []
    assert checkable == 0
    assert uncheckable == 1
    assert items[0].checkable is False
    assert items[0].math_error is None


def test_tier1_missing_unit_price():
    """Line missing unit price is marked uncheckable and counted in uncheckable_count."""
    items = [
        CanonicalLineItem(
            item_name="Bakery Item",
            qty=Decimal("3"),
            unit_price=None,
            line_total=Decimal("6.00"),
            kind=LineItemKind.GOODS,
        )
    ]

    all_passed, errors, checkable, uncheckable = validate_tier1_lines(items)
    assert all_passed is True
    assert errors == []
    assert checkable == 0
    assert uncheckable == 1
    assert items[0].checkable is False
    assert items[0].math_error is None


def test_tier1_missing_both_qty_and_price():
    """Line missing both qty and unit_price is marked uncheckable."""
    items = [
        CanonicalLineItem(
            item_name="Open Item",
            qty=None,
            unit_price=None,
            line_total=Decimal("15.00"),
            kind=LineItemKind.GOODS,
        )
    ]

    all_passed, errors, checkable, uncheckable = validate_tier1_lines(items)
    assert all_passed is True
    assert errors == []
    assert checkable == 0
    assert uncheckable == 1
    assert items[0].checkable is False


def test_tier1_missing_line_total():
    """Line missing line_total cannot be verified and is marked uncheckable."""
    items = [
        CanonicalLineItem(
            item_name="Incomplete Row",
            qty=Decimal("2"),
            unit_price=Decimal("5.00"),
            line_total=None,
            kind=LineItemKind.GOODS,
        )
    ]

    all_passed, errors, checkable, uncheckable = validate_tier1_lines(items)
    assert all_passed is True
    assert errors == []
    assert checkable == 0
    assert uncheckable == 1
    assert items[0].checkable is False


def test_tier1_non_goods_lines_are_uncheckable():
    """Non-goods lines (e.g. discount, fee, shipping, deposit) are bypassed and not counted in uncheckable_count."""
    items = [
        CanonicalLineItem(
            item_name="Store Coupon",
            qty=None,
            unit_price=None,
            line_total=Decimal("-5.00"),
            kind=LineItemKind.DISCOUNT,
        ),
        CanonicalLineItem(
            item_name="Service Fee",
            qty=Decimal("1"),
            unit_price=Decimal("2.50"),
            line_total=Decimal("2.50"),
            kind=LineItemKind.FEE,
        ),
        CanonicalLineItem(
            item_name="Bottle Deposit",
            qty=None,
            unit_price=None,
            line_total=Decimal("0.50"),
            kind=LineItemKind.DEPOSIT,
        ),
    ]

    all_passed, errors, checkable, uncheckable = validate_tier1_lines(items)
    assert all_passed is True
    assert errors == []
    assert checkable == 0
    assert uncheckable == 0  # Non-goods lines must NOT increase uncheckable count
    assert items[0].checkable is False
    assert items[1].checkable is False
    assert items[2].checkable is False


def test_tier1_negative_qty_return():
    """Returned goods with negative qty evaluate tolerance with |qty|."""
    # qty = -2, unit_price = 5.00 -> expected = -10.00
    # line_total = -10.00
    # tol = 0.01 + 0.005 * |-2| = 0.02
    items = [
        CanonicalLineItem(
            item_name="Returned Shirt",
            qty=Decimal("-2"),
            unit_price=Decimal("5.00"),
            line_total=Decimal("-10.00"),
            kind=LineItemKind.GOODS,
        )
    ]

    all_passed, errors, checkable, uncheckable = validate_tier1_lines(items)
    assert all_passed is True
    assert errors == []
    assert checkable == 1
    assert uncheckable == 0
    assert items[0].checkable is True


def test_tier1_tolerance_boundary():
    """Exact boundary checks for Tier 1 formula."""
    qty = Decimal("2.00")
    unit_price = Decimal("3.00")  # expected = 6.0000
    # tolerance = 0.01 + 0.005 * 2 = 0.02
    tol = TIER1_BASE_TOLERANCE + TIER1_QTY_FACTOR * abs(qty)
    assert tol == Decimal("0.02")

    # Exact boundary: diff == 0.02
    items_pass = [
        CanonicalLineItem(
            item_name="Item Pass",
            qty=qty,
            unit_price=unit_price,
            line_total=Decimal("6.02"),
            kind=LineItemKind.GOODS,
        )
    ]
    all_passed, errors, checkable, uncheckable = validate_tier1_lines(items_pass)
    assert all_passed is True
    assert errors == []

    # Beyond boundary: diff == 0.021 > 0.02
    items_fail = [
        CanonicalLineItem(
            item_name="Item Fail",
            qty=qty,
            unit_price=unit_price,
            line_total=Decimal("6.021"),
            kind=LineItemKind.GOODS,
        )
    ]
    all_passed, errors, checkable, uncheckable = validate_tier1_lines(items_fail)
    assert all_passed is False
    assert len(errors) == 1


def test_tier1_empty_list():
    """Empty line items list returns all_passed=True with 0 counts."""
    all_passed, errors, checkable, uncheckable = validate_tier1_lines([])
    assert all_passed is True
    assert errors == []
    assert checkable == 0
    assert uncheckable == 0


def test_tier1_mixed_lines():
    """Mixed set: 1 valid goods, 1 math error goods, 1 missing qty, 1 discount."""
    items = [
        CanonicalLineItem(
            item_name="Good Milk",
            qty=Decimal("2"),
            unit_price=Decimal("4.00"),
            line_total=Decimal("8.00"),
            kind=LineItemKind.GOODS,
        ),
        CanonicalLineItem(
            item_name="Bad Eggs",
            qty=Decimal("1"),
            unit_price=Decimal("3.00"),
            line_total=Decimal("5.00"),  # mismatch
            kind=LineItemKind.GOODS,
        ),
        CanonicalLineItem(
            item_name="Bulk Rice",
            qty=None,
            unit_price=Decimal("12.00"),
            line_total=Decimal("12.00"),
            kind=LineItemKind.GOODS,
        ),
        CanonicalLineItem(
            item_name="Coupon",
            qty=None,
            unit_price=None,
            line_total=Decimal("-2.00"),
            kind=LineItemKind.DISCOUNT,
        ),
    ]

    all_passed, errors, checkable, uncheckable = validate_tier1_lines(items)
    assert all_passed is False
    assert len(errors) == 1
    assert "Bad Eggs" in errors[0]
    assert checkable == 2  # Good Milk and Bad Eggs
    assert uncheckable == 1  # Only Bulk Rice (goods), Coupon is non-goods and not counted


# =============================================================================
# Tier 2 Tests: Subtotal Consistency
# =============================================================================

def test_tier2_exact_subtotal():
    """Standard goods summing exactly to subtotal passes."""
    invoice = CanonicalInvoice(
        source_file="invoice_01.pdf",
        source_sha256="abc001",
        subtotal=Decimal("35.00"),
        line_items=[
            CanonicalLineItem(item_name="Item 1", line_total=Decimal("20.00")),
            CanonicalLineItem(item_name="Item 2", line_total=Decimal("15.00")),
        ],
    )

    is_consistent, errors = validate_tier2_subtotal(invoice)
    assert is_consistent is True
    assert errors == []


def test_tier2_discount_negative_line():
    """Invoice with a negative discount line item sums correctly."""
    # 50.00 (goods) + 25.00 (goods) + (-10.00) (discount) = 65.00
    invoice = CanonicalInvoice(
        source_file="invoice_discount.pdf",
        source_sha256="abc002",
        subtotal=Decimal("65.00"),
        line_items=[
            CanonicalLineItem(item_name="Goods A", line_total=Decimal("50.00"), kind=LineItemKind.GOODS),
            CanonicalLineItem(item_name="Goods B", line_total=Decimal("25.00"), kind=LineItemKind.GOODS),
            CanonicalLineItem(item_name="Loyalty Discount", line_total=Decimal("-10.00"), kind=LineItemKind.DISCOUNT),
        ],
    )

    is_consistent, errors = validate_tier2_subtotal(invoice)
    assert is_consistent is True
    assert errors == []


def test_tier2_discount_mismatch_fails():
    """Invoice with discount that does not match subtotal fails."""
    # sum = 50 + 25 - 10 = 65, but reported subtotal is 75 (discount omitted)
    invoice = CanonicalInvoice(
        source_file="invoice_discount_bad.pdf",
        source_sha256="abc003",
        subtotal=Decimal("75.00"),
        line_items=[
            CanonicalLineItem(item_name="Goods A", line_total=Decimal("50.00"), kind=LineItemKind.GOODS),
            CanonicalLineItem(item_name="Goods B", line_total=Decimal("25.00"), kind=LineItemKind.GOODS),
            CanonicalLineItem(item_name="Loyalty Discount", line_total=Decimal("-10.00"), kind=LineItemKind.DISCOUNT),
        ],
    )

    is_consistent, errors = validate_tier2_subtotal(invoice)
    assert is_consistent is False
    assert len(errors) == 1
    assert "Subtotal mismatch" in errors[0]


def test_tier2_fee_line_included_in_subtotal():
    """Fee lines in line_items are included in subtotal calculation."""
    # 40.00 (goods) + 5.00 (fee) = 45.00
    invoice = CanonicalInvoice(
        source_file="invoice_fee.pdf",
        source_sha256="abc004",
        subtotal=Decimal("45.00"),
        line_items=[
            CanonicalLineItem(item_name="Food Item", line_total=Decimal("40.00"), kind=LineItemKind.GOODS),
            CanonicalLineItem(item_name="Packaging Fee", line_total=Decimal("5.00"), kind=LineItemKind.FEE),
        ],
    )

    is_consistent, errors = validate_tier2_subtotal(invoice)
    assert is_consistent is True
    assert errors == []


def test_tier2_missing_subtotal():
    """Invoice without subtotal returns (False, ['no_subtotal'])."""
    invoice = CanonicalInvoice(
        source_file="invoice_no_subtotal.pdf",
        source_sha256="abc005",
        subtotal=None,
        line_items=[
            CanonicalLineItem(item_name="Goods", line_total=Decimal("20.00")),
        ],
    )

    is_consistent, errors = validate_tier2_subtotal(invoice)
    assert is_consistent is False
    assert errors == ["no_subtotal"]


def test_tier2_line_items_missing_unit_price_or_qty_still_valid_in_subtotal():
    """Lines missing unit_price/qty but having line_total are summed in Tier 2."""
    invoice = CanonicalInvoice(
        source_file="invoice_mixed_data.pdf",
        source_sha256="abc006",
        subtotal=Decimal("30.00"),
        line_items=[
            CanonicalLineItem(
                item_name="Standard",
                qty=Decimal("2"),
                unit_price=Decimal("10.00"),
                line_total=Decimal("20.00"),
                kind=LineItemKind.GOODS,
            ),
            CanonicalLineItem(
                item_name="Custom Adjustment",
                qty=None,
                unit_price=None,
                line_total=Decimal("10.00"),
                kind=LineItemKind.GOODS,
            ),
        ],
    )

    is_consistent, errors = validate_tier2_subtotal(invoice)
    assert is_consistent is True
    assert errors == []


def test_tier2_line_missing_line_total_fails():
    """Line item missing line_total fails Tier 2 because subtotal cannot be verified."""
    invoice = CanonicalInvoice(
        source_file="invoice_missing_tot.pdf",
        source_sha256="abc007",
        subtotal=Decimal("30.00"),
        line_items=[
            CanonicalLineItem(item_name="Item 1", line_total=Decimal("20.00")),
            CanonicalLineItem(item_name="Item 2", line_total=None),
        ],
    )

    is_consistent, errors = validate_tier2_subtotal(invoice)
    assert is_consistent is False
    assert len(errors) == 1
    assert "missing line_total" in errors[0]


def test_tier2_excluded_kinds():
    """Tax and shipping line items are not included in subtotal."""
    # goods=100.00, tax_line=8.00 -> subtotal should be 100.00
    invoice = CanonicalInvoice(
        source_file="invoice_tax_line.pdf",
        source_sha256="abc008",
        subtotal=Decimal("100.00"),
        line_items=[
            CanonicalLineItem(item_name="Goods", line_total=Decimal("100.00"), kind=LineItemKind.GOODS),
            CanonicalLineItem(item_name="Sales Tax Line", line_total=Decimal("8.00"), kind=LineItemKind.TAX_LINE),
            CanonicalLineItem(item_name="Freight", line_total=Decimal("15.00"), kind=LineItemKind.SHIPPING),
        ],
    )

    is_consistent, errors = validate_tier2_subtotal(invoice)
    assert is_consistent is True
    assert errors == []


def test_tier2_multi_line_tolerance_scaling():
    """Tolerance scales with number of lines (0.02 + 0.005 * n_lines)."""
    # 10 lines of 9.99 = 99.90
    # Suppose subtotal on invoice is 99.95 (diff = 0.05)
    # n_lines = 10 -> tolerance = 0.02 + 0.005 * 10 = 0.07
    # diff (0.05) <= 0.07 -> passes
    lines = [
        CanonicalLineItem(
            item_name=f"Line {i}",
            line_total=Decimal("9.99"),
            kind=LineItemKind.GOODS,
        )
        for i in range(10)
    ]

    invoice_pass = CanonicalInvoice(
        source_file="invoice_multi_pass.pdf",
        source_sha256="abc009",
        subtotal=Decimal("99.95"),
        line_items=lines,
    )
    is_consistent, errors = validate_tier2_subtotal(invoice_pass)
    assert is_consistent is True
    assert errors == []

    # If diff = 0.08 > 0.07 -> fails
    invoice_fail = CanonicalInvoice(
        source_file="invoice_multi_fail.pdf",
        source_sha256="abc010",
        subtotal=Decimal("99.98"),
        line_items=lines,
    )
    is_consistent, errors = validate_tier2_subtotal(invoice_fail)
    assert is_consistent is False
    assert len(errors) == 1


def test_tier2_empty_line_items():
    """Empty line items with subtotal 0 passes, with non-zero fails."""
    inv_zero = CanonicalInvoice(
        source_file="empty_zero.pdf",
        source_sha256="abc011",
        subtotal=Decimal("0.00"),
        line_items=[],
    )
    assert validate_tier2_subtotal(inv_zero) == (True, [])

    inv_nonzero = CanonicalInvoice(
        source_file="empty_nonzero.pdf",
        source_sha256="abc012",
        subtotal=Decimal("50.00"),
        line_items=[],
    )
    is_consistent, errors = validate_tier2_subtotal(inv_nonzero)
    assert is_consistent is False
    assert len(errors) == 1
