"""Deduplication module.

PLAN 6.3:
- Duplicate detection by:
  1. Exact SHA-256 match.
  2. Compound key: (normalized vendor, invoice_no, grand_total).
- Fuzzy vendor matching with rapidfuzz (similarity threshold >= 90).
- Keeps the first document; marks subsequent ones as DUPLICATE.
"""

from decimal import Decimal
from typing import List, Optional, Tuple
from rapidfuzz import fuzz, utils

from config import DEDUP_SIMILARITY_THRESHOLD
from models.schema import CanonicalInvoice, InvoiceStatus


def normalize_vendor_name(vendor: Optional[str]) -> str:
    """Normalize vendor name for matching.

    Uses rapidfuzz default_process (lowercase, strip whitespace and punctuation).
    """
    if not vendor:
        return ""
    processed = utils.default_process(vendor)
    return processed.strip() if processed else ""


def normalize_invoice_no(invoice_no: Optional[str]) -> str:
    """Normalize invoice number for exact matching.

    Strips whitespace, leading '#' symbols, and normalizes to uppercase.
    """
    if not invoice_no:
        return ""
    return invoice_no.strip().lstrip("#").strip().upper()


def is_vendor_similar(
    vendor1: Optional[str],
    vendor2: Optional[str],
    threshold: float = DEDUP_SIMILARITY_THRESHOLD,
) -> bool:
    """Check if two vendor names are similar enough to be considered identical.

    Uses rapidfuzz token_set_ratio and ratio on processed strings.
    """
    s1 = normalize_vendor_name(vendor1)
    s2 = normalize_vendor_name(vendor2)

    if not s1 or not s2:
        return False

    if s1 == s2:
        return True

    score = max(
        fuzz.token_set_ratio(s1, s2),
        fuzz.ratio(s1, s2),
    )
    return score >= threshold


def deduplicate_invoices(
    invoices: List[CanonicalInvoice],
    similarity_threshold: float = DEDUP_SIMILARITY_THRESHOLD,
) -> Tuple[List[CanonicalInvoice], List[Tuple[str, str, str]]]:
    """Scan invoices list and mark duplicate entries.

    Preserves the first occurrence; subsequent matching invoices are marked with:
        - is_duplicate = True
        - status = InvoiceStatus.DUPLICATE
        - duplicate_of = first_invoice.source_file

    Detection criteria:
    1. Exact SHA-256 match: same source file content (source_sha256).
    2. Compound key match: (normalized vendor, invoice_no, grand_total),
       where vendor similarity >= similarity_threshold (rapidfuzz).

    Args:
        invoices: List of parsed CanonicalInvoice objects.
        similarity_threshold: Threshold for fuzzy vendor matching (default from config).

    Returns:
        Tuple of (updated_invoices_list, list_of_duplicate_pairs),
        where each duplicate pair is (duplicate_source_file, original_source_file, reason).
    """
    canonical_invoices: List[CanonicalInvoice] = []
    duplicate_pairs: List[Tuple[str, str, str]] = []

    for inv in invoices:
        is_dup = False
        dup_target: Optional[CanonicalInvoice] = None
        reason = ""

        # 1. Exact SHA-256 match
        if inv.source_sha256:
            for canon in canonical_invoices:
                if canon.source_sha256 and canon.source_sha256 == inv.source_sha256:
                    is_dup = True
                    dup_target = canon
                    reason = "exact_sha256"
                    break

        # 2. Compound key match (if not already matched by SHA-256)
        if not is_dup:
            inv_no_norm = normalize_invoice_no(inv.invoice_no)
            if inv_no_norm and inv.grand_total is not None and inv.vendor_name:
                for canon in canonical_invoices:
                    if (
                        canon.invoice_no
                        and canon.grand_total is not None
                        and canon.vendor_name
                    ):
                        if canon.grand_total == inv.grand_total:
                            if normalize_invoice_no(canon.invoice_no) == inv_no_norm:
                                if is_vendor_similar(
                                    inv.vendor_name,
                                    canon.vendor_name,
                                    similarity_threshold,
                                ):
                                    is_dup = True
                                    dup_target = canon
                                    reason = "compound_key"
                                    break

        if is_dup and dup_target is not None:
            inv.is_duplicate = True
            inv.status = InvoiceStatus.DUPLICATE
            inv.duplicate_of = dup_target.source_file
            duplicate_pairs.append((inv.source_file, dup_target.source_file, reason))
        else:
            inv.is_duplicate = False
            inv.duplicate_of = None
            canonical_invoices.append(inv)

    return invoices, duplicate_pairs
