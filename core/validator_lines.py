"""Line items validation module (Tiers 1 & 2).

PLAN 5.4:
- Tier 1: individual line items |qty * unit_price - line_total| <= 0.01 + 0.005 * |qty|.
  Handles weighted goods, discounts, uncheckable lines.
- Tier 2: line totals sum |sum(line_total có dấu) - subtotal| <= 0.02 + 0.005 * số dòng.
  Detects missing subtotal (flags review_needed with 'no_subtotal').
"""

from decimal import Decimal
from typing import List, Tuple

from config import (
    TIER1_BASE_TOLERANCE,
    TIER1_QTY_FACTOR,
    TIER2_BASE_TOLERANCE,
    TIER2_LINE_FACTOR,
)
from models.schema import CanonicalInvoice, CanonicalLineItem, LineItemKind


def validate_tier1_lines(line_items: List[CanonicalLineItem]) -> Tuple[bool, List[str], int, int]:
    """Validate arithmetic consistency of individual line items.

    Args:
        line_items: Extracted line items.

    Returns:
        Tuple of (all_passed, error_messages, checkable_count, uncheckable_count).
    """
    checkable_count = 0
    uncheckable_count = 0
    error_messages: List[str] = []
    all_passed = True

    for idx, line in enumerate(line_items, start=1):
        kind_val = line.kind.value if hasattr(line.kind, "value") else str(line.kind)
        is_goods = (kind_val == LineItemKind.GOODS.value or line.kind == LineItemKind.GOODS)

        # Only goods lines with qty, unit_price, and line_total can be arithmetically verified
        if is_goods:
            if line.qty is not None and line.unit_price is not None and line.line_total is not None:
                qty = Decimal(str(line.qty))
                unit_price = Decimal(str(line.unit_price))
                line_total = Decimal(str(line.line_total))

                expected_total = qty * unit_price
                diff = abs(expected_total - line_total)
                tolerance = TIER1_BASE_TOLERANCE + TIER1_QTY_FACTOR * abs(qty)

                if diff <= tolerance:
                    line.checkable = True
                    line.math_error = None
                    checkable_count += 1
                else:
                    line.checkable = True
                    err_msg = (
                        f"Line {idx} ('{line.item_name}'): math mismatch "
                        f"(diff: {diff} > tolerance: {tolerance})"
                    )
                    line.math_error = err_msg
                    error_messages.append(err_msg)
                    checkable_count += 1
                    all_passed = False
            else:
                line.checkable = False
                line.math_error = None
                uncheckable_count += 1
        else:
            # Non-goods lines (discount, fee, tax_line, deposit, shipping) are not goods
            # and do not increment uncheckable_count (so they don't penalize checkable_ratio)
            line.checkable = False
            line.math_error = None

    if len(error_messages) > 0:
        all_passed = False

    return all_passed, error_messages, checkable_count, uncheckable_count


def validate_tier2_subtotal(invoice: CanonicalInvoice) -> Tuple[bool, List[str]]:
    """Validate sum of line items against reported subtotal.

    Args:
        invoice: CanonicalInvoice instance.

    Returns:
        Tuple of (is_consistent, error_messages).
    """
    if invoice.subtotal is None:
        return False, ["no_subtotal"]

    subtotal = Decimal(str(invoice.subtotal))

    # Kinds contributing to subtotal (goods, fee, discount có dấu)
    subtotal_kinds = {
        LineItemKind.GOODS,
        LineItemKind.FEE,
        LineItemKind.DISCOUNT,
        LineItemKind.GOODS.value,
        LineItemKind.FEE.value,
        LineItemKind.DISCOUNT.value,
    }

    applicable_lines = [
        item for item in invoice.line_items
        if item.kind in subtotal_kinds or getattr(item.kind, "value", str(item.kind)) in subtotal_kinds
    ]

    line_sum = Decimal("0")
    for idx, item in enumerate(applicable_lines, start=1):
        if item.line_total is None:
            return False, [f"Line {idx} ('{item.item_name}') missing line_total, cannot validate subtotal"]
        line_sum += Decimal(str(item.line_total))

    n_lines = len(applicable_lines)
    tolerance = TIER2_BASE_TOLERANCE + TIER2_LINE_FACTOR * Decimal(n_lines)
    diff = abs(line_sum - subtotal)

    if diff <= tolerance:
        return True, []

    err_msg = (
        f"Subtotal mismatch: sum(line_totals)={line_sum} != subtotal={subtotal} "
        f"(diff={diff}, tolerance={tolerance})"
    )
    return False, [err_msg]
