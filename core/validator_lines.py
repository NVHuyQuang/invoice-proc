"""Line items validation module (Tiers 1 & 2).

PLAN 5.4:
- Tier 1: individual line items |qty * unit_price - line_total| <= 0.01 + 0.005 * |qty|.
  Handles weighted goods, discounts, uncheckable lines.
- Tier 2: line totals sum |sum(line_total) - subtotal| <= 0.02 + 0.005 * line_count.
  Detects missing subtotal (flags review_needed).
"""

from typing import List, Tuple
from models.schema import CanonicalInvoice, CanonicalLineItem


def validate_tier1_lines(line_items: List[CanonicalLineItem]) -> Tuple[bool, List[str], int, int]:
    """Validate arithmetic consistency of individual line items.

    Args:
        line_items: Extracted line items.

    Returns:
        Tuple of (all_passed, error_messages, checkable_count, uncheckable_count).
    """
    raise NotImplementedError("W1-val-lines implementation pending")


def validate_tier2_subtotal(invoice: CanonicalInvoice) -> Tuple[bool, List[str]]:
    """Validate sum of line items against reported subtotal.

    Args:
        invoice: CanonicalInvoice instance.

    Returns:
        Tuple of (is_consistent, error_messages).
    """
    raise NotImplementedError("W1-val-lines implementation pending")
