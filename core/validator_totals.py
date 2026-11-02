"""Grand total and document-level validation module (Tiers 3 & 4 + Checks).

PLAN 5.4:
- Tier 3: |subtotal + tax + shipping + tip + sum(fees) - discount - grand_total| <= 0.02.
  Handles multiple tax lines, credit memos.
- Tier 4: Utility bills / receipts without subtotal: |sum(charges) - amount_due| <= 0.02.
  Supports previous balance / payments.
- Additional checks:
  * grand_total > 0 (unless credit memo)
  * due_date >= invoice_date
  * invoice_date within processing month +- 45 days
"""

from typing import Tuple, List, Optional
from models.schema import CanonicalInvoice


def validate_tier3_grand_total(invoice: CanonicalInvoice) -> Tuple[bool, List[str]]:
    """Validate grand total formula for standard invoices.

    Args:
        invoice: CanonicalInvoice instance.

    Returns:
        Tuple of (is_consistent, error_messages).
    """
    raise NotImplementedError("W1-val-totals implementation pending")


def validate_tier4_utility_total(invoice: CanonicalInvoice) -> Tuple[bool, List[str]]:
    """Validate amount due for utility bills and non-subtotal receipts.

    Args:
        invoice: CanonicalInvoice instance.

    Returns:
        Tuple of (is_consistent, error_messages).
    """
    raise NotImplementedError("W1-val-totals implementation pending")


def validate_dates_and_metadata(invoice: CanonicalInvoice, target_month: Optional[str] = None) -> List[str]:
    """Perform sanity checks on dates and total signs.

    Args:
        invoice: CanonicalInvoice instance.
        target_month: Target month string 'YYYY-MM'.

    Returns:
        List of warning/error messages.
    """
    raise NotImplementedError("W1-val-totals implementation pending")
