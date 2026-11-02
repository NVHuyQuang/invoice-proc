"""Final invoice status assignment module.

PLAN 5.5: Combines tier results, rehydrator flags, confidence flags into:
- VERIFIED: All mandatory checks ran AND passed.
  * Tier 3 or 4 passed.
  * >= 80% lines checkable, 0 line errors.
  * No low_conf on participating numbers.
  * No unknown/duplicate/orphan tokens, no ambiguous flags, no multi-invoice flags.
- REVIEW_NEEDED: Incomplete checks, math discrepancies, or ambiguity flags.
- FAILED: File unreadable, fatal parsing or LLM failure.
"""

from typing import List, Optional
from models.schema import CanonicalInvoice, InvoiceStatus


def assign_invoice_status(
    invoice: CanonicalInvoice,
    rehydrator_flags: Optional[List[str]] = None,
    target_month: Optional[str] = None
) -> CanonicalInvoice:
    """Evaluate all mathematical tiers and flags to assign final InvoiceStatus.

    Args:
        invoice: Rehydrated CanonicalInvoice.
        rehydrator_flags: Warning flags from token rehydration.
        target_month: Processing month 'YYYY-MM' for date window checking.

    Returns:
        Updated CanonicalInvoice with final status and review_reasons populated.
    """
    raise NotImplementedError("W1-val-status implementation pending")
