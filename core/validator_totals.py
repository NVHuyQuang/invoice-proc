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

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple

from config import DATE_WINDOW_DAYS, TIER3_TOLERANCE, TIER4_TOLERANCE
from models.schema import CanonicalInvoice, DocType, LineItemKind


def _parse_date(d_str: Optional[str]) -> Optional[date]:
    """Parse date string into a datetime.date object supporting common invoice date formats."""
    if not d_str or not isinstance(d_str, str):
        return None
    d_str = d_str.strip()
    if not d_str:
        return None

    try:
        return date.fromisoformat(d_str)
    except ValueError:
        pass

    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%m-%d-%Y",
        "%d-%m-%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%m/%d/%y",
        "%d/%m/%y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(d_str, fmt).date()
        except ValueError:
            continue
    return None


def validate_tier3_grand_total(invoice: CanonicalInvoice) -> Tuple[bool, List[str]]:
    """Validate grand total formula for standard invoices.

    PLAN 5.4:
    |subtotal + tax + shipping + tip + sum(fees) - discount - grand_total| <= 0.02.
    Supports multiple tax lines, credit memos.

    Args:
        invoice: CanonicalInvoice instance.

    Returns:
        Tuple of (is_consistent, error_messages).
    """
    if invoice.subtotal is None:
        return False, ["Tier 3 failed: missing subtotal"]
    if invoice.grand_total is None:
        return False, ["Tier 3 failed: missing grand_total"]

    subtotal = invoice.subtotal
    grand_total = invoice.grand_total

    # Tax: check line items with TAX_LINE kind as well as summary tax
    tax_lines = [
        item.line_total
        for item in invoice.line_items
        if item.kind == LineItemKind.TAX_LINE and item.line_total is not None
    ]
    tax_lines_sum = sum(tax_lines, Decimal("0")) if tax_lines else None
    summary_tax = invoice.tax

    candidate_taxes: List[Decimal] = []
    if tax_lines_sum is not None:
        candidate_taxes.append(tax_lines_sum)
    if summary_tax is not None and summary_tax not in candidate_taxes:
        candidate_taxes.append(summary_tax)
    if (
        tax_lines_sum is not None
        and summary_tax is not None
        and abs(tax_lines_sum - summary_tax) > TIER3_TOLERANCE
    ):
        candidate_taxes.append(tax_lines_sum + summary_tax)
    if not candidate_taxes:
        candidate_taxes.append(Decimal("0"))

    # Shipping: from summary or shipping line items
    shipping_lines = [
        item.line_total
        for item in invoice.line_items
        if item.kind == LineItemKind.SHIPPING and item.line_total is not None
    ]
    shipping_lines_sum = sum(shipping_lines, Decimal("0")) if shipping_lines else None
    if invoice.shipping is not None:
        shipping = invoice.shipping
    elif shipping_lines_sum is not None:
        shipping = shipping_lines_sum
    else:
        shipping = Decimal("0")

    tip = invoice.tip if invoice.tip is not None else Decimal("0")
    fees_sum = sum((f for f in invoice.fees if f is not None), Decimal("0"))
    discount = abs(invoice.discount) if invoice.discount is not None else Decimal("0")

    is_credit_memo = (
        invoice.doc_type == DocType.CREDIT_MEMO
        or str(invoice.doc_type).lower() == "credit_memo"
    )

    best_diff = None
    best_expected = None

    for candidate_tax in candidate_taxes:
        expected = subtotal + candidate_tax + shipping + tip + fees_sum - discount
        diff = abs(expected - grand_total)

        if is_credit_memo:
            diff_flipped = abs(-expected - grand_total)
            diff_abs = abs(abs(expected) - abs(grand_total))
            diff = min(diff, diff_flipped, diff_abs)

        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_expected = expected

        if diff <= TIER3_TOLERANCE:
            return True, []

    chosen_tax = candidate_taxes[0]
    errors = [
        f"Tier 3 grand total mismatch: subtotal ({subtotal}) + tax ({chosen_tax}) + "
        f"shipping ({shipping}) + tip ({tip}) + fees ({fees_sum}) - discount ({discount}) = "
        f"{best_expected}, but grand_total = {grand_total} (diff: {best_diff:.4f} > tolerance: {TIER3_TOLERANCE})"
    ]
    return False, errors


def validate_tier4_utility_total(invoice: CanonicalInvoice) -> Tuple[bool, List[str]]:
    """Validate amount due for utility bills and non-subtotal receipts.

    PLAN 5.4:
    |sum(charges) - amount_due| <= 0.02.
    Supports previous balance / payments.

    Args:
        invoice: CanonicalInvoice instance.

    Returns:
        Tuple of (is_consistent, error_messages).
    """
    target = invoice.amount_due if invoice.amount_due is not None else invoice.grand_total
    if target is None:
        return False, ["Tier 4 failed: missing amount_due or grand_total"]

    if invoice.charges:
        items = [(c.description, c.amount, getattr(c, "kind", None)) for c in invoice.charges]
    elif invoice.line_items:
        items = [
            (item.item_name, item.line_total, item.kind)
            for item in invoice.line_items
            if item.line_total is not None
        ]
    else:
        return False, ["Tier 4 failed: no charges or line items found"]

    # Candidate 1: direct sum (signed charges)
    direct_sum = sum((amount for _, amount, _ in items), Decimal("0"))
    if abs(direct_sum - target) <= TIER4_TOLERANCE:
        return True, []

    # Candidate 2: kind-aware sum
    payment_kinds = {"payment", "payments", "credit", "discount", "deposit"}
    kind_sum = Decimal("0")
    for _, amount, kind in items:
        k_str = str(kind.value if hasattr(kind, "value") else kind).lower() if kind else ""
        if k_str in payment_kinds:
            kind_sum -= abs(amount)
        else:
            kind_sum += amount

    if abs(kind_sum - target) <= TIER4_TOLERANCE:
        return True, []

    # Candidate 3: description-aware sum
    payment_keywords = ("payment", "paid", "credit", "thank you", "payments applied")
    desc_sum = Decimal("0")
    for desc, amount, _ in items:
        d_lower = desc.lower() if desc else ""
        if any(kw in d_lower for kw in payment_keywords):
            desc_sum -= abs(amount)
        else:
            desc_sum += amount

    if abs(desc_sum - target) <= TIER4_TOLERANCE:
        return True, []

    diff = min(abs(direct_sum - target), abs(kind_sum - target), abs(desc_sum - target))
    return False, [
        f"Tier 4 utility total mismatch: charges sum ({direct_sum}) != target ({target}) "
        f"(diff: {diff:.4f} > tolerance: {TIER4_TOLERANCE})"
    ]


def validate_dates_and_metadata(
    invoice: CanonicalInvoice,
    target_month: Optional[str] = None
) -> List[str]:
    """Perform sanity checks on dates and total signs.

    PLAN 5.4:
    - grand_total > 0 (unless credit memo).
    - due_date >= invoice_date if both are present.
    - invoice_date within target_month +- DATE_WINDOW_DAYS (45 days).

    Args:
        invoice: CanonicalInvoice instance.
        target_month: Target month string 'YYYY-MM' or 'YYYY-MM-DD'.

    Returns:
        List of warning/error messages.
    """
    messages: List[str] = []

    # 1. grand_total > 0 unless credit memo
    is_credit_memo = (
        invoice.doc_type == DocType.CREDIT_MEMO
        or str(invoice.doc_type).lower() == "credit_memo"
    )

    if not is_credit_memo:
        total_to_check = invoice.grand_total if invoice.grand_total is not None else invoice.amount_due
        if total_to_check is not None:
            if total_to_check <= Decimal("0"):
                messages.append(
                    f"grand_total must be > 0 for {invoice.doc_type} (got {total_to_check})"
                )
        else:
            messages.append("grand_total is missing")

    # 2. due_date >= invoice_date if both are present
    inv_date = _parse_date(invoice.invoice_date)
    due_date = _parse_date(invoice.due_date)

    if invoice.invoice_date is not None and inv_date is None:
        messages.append(f"Unparseable invoice_date: '{invoice.invoice_date}'")

    if invoice.due_date is not None and due_date is None:
        messages.append(f"Unparseable due_date: '{invoice.due_date}'")

    if inv_date is not None and due_date is not None:
        if due_date < inv_date:
            messages.append(
                f"due_date ({invoice.due_date}) cannot be before invoice_date ({invoice.invoice_date})"
            )

    # 3. invoice_date within target_month +- DATE_WINDOW_DAYS
    if target_month is not None:
        if inv_date is None:
            messages.append("invoice_date is missing or invalid for target month verification")
        else:
            tm_str = target_month.strip()
            month_start = None
            month_end = None
            try:
                if len(tm_str.split("-")) == 2:
                    parts = tm_str.split("-")
                    year, month = int(parts[0]), int(parts[1])
                    month_start = date(year, month, 1)
                    _, last_day = calendar.monthrange(year, month)
                    month_end = date(year, month, last_day)
                elif len(tm_str.split("-")) == 3:
                    parsed_dt = _parse_date(tm_str)
                    if parsed_dt:
                        year, month = parsed_dt.year, parsed_dt.month
                        month_start = date(year, month, 1)
                        _, last_day = calendar.monthrange(year, month)
                        month_end = date(year, month, last_day)
            except Exception:
                pass

            if month_start is None or month_end is None:
                messages.append(f"Invalid target_month format: '{target_month}'")
            else:
                window_start = month_start - timedelta(days=DATE_WINDOW_DAYS)
                window_end = month_end + timedelta(days=DATE_WINDOW_DAYS)
                if inv_date < window_start or inv_date > window_end:
                    messages.append(
                        f"invoice_date ({invoice.invoice_date}) is outside target month {target_month} "
                        f"+- {DATE_WINDOW_DAYS} days (allowed: {window_start} to {window_end})"
                    )

    return messages
