"""Deduplication module.

PLAN 6.3:
- Duplicate detection by:
  1. Exact SHA-256 match.
  2. Compound key: (normalized vendor, invoice_no, grand_total).
- Fuzzy vendor matching with rapidfuzz (similarity threshold >= 90).
- Keeps the first document; marks subsequent ones as DUPLICATE.
"""

from typing import List, Tuple
from models.schema import CanonicalInvoice


def deduplicate_invoices(invoices: List[CanonicalInvoice]) -> Tuple[List[CanonicalInvoice], List[Tuple[str, str, str]]]:
    """Scan invoices list and mark duplicate entries.

    Args:
        invoices: List of parsed CanonicalInvoice objects.

    Returns:
        Tuple of (updated_invoices_list, list_of_duplicate_pairs).
    """
    raise NotImplementedError("W1-dedup implementation pending")
