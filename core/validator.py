"""Final invoice status assignment module.

PLAN 5.5: Combines tier results, rehydrator flags, confidence flags into:
- VERIFIED: All mandatory checks ran AND passed.
  * Tier 3 or 4 passed.
  * >= 80% lines checkable, 0 line errors.
  * No low_conf on participating numbers.
  * No unknown/duplicate/orphan tokens, no ambiguous flags, no multi-invoice flags.
  * doc_type in auto-verified types (goods_invoice, receipt, utility_bill, credit_memo).
- REVIEW_NEEDED: Incomplete checks, math discrepancies, ambiguity flags, or non-auto doc_types.
- FAILED: File unreadable, fatal parsing or LLM failure.
"""

from decimal import Decimal
from typing import Any, Iterable, List, Optional, Set, Tuple

from config import MIN_CHECKABLE_LINE_RATIO, OCR_CONFIDENCE_THRESHOLD
from core.types import Provenance
from core.validator_lines import validate_tier1_lines, validate_tier2_subtotal
from core.validator_totals import (
    validate_dates_and_metadata,
    validate_tier3_grand_total,
    validate_tier4_utility_total,
)
from models.schema import CanonicalInvoice, DocType, InvoiceStatus

AUTO_DOC_TYPES: Set[DocType] = {
    DocType.GOODS_INVOICE,
    DocType.RECEIPT,
    DocType.UTILITY_BILL,
    DocType.CREDIT_MEMO,
}

AUTO_DOC_TYPE_VALUES: Set[str] = {
    DocType.GOODS_INVOICE.value,
    DocType.RECEIPT.value,
    DocType.UTILITY_BILL.value,
    DocType.CREDIT_MEMO.value,
}

FATAL_FAIL_PREFIXES: Tuple[str, ...] = (
    "file_unreadable",
    "ocr_failed",
    "ocr_error",
    "llm_failed",
    "llm_error",
    "fatal",
    "failed",
    "read_error",
    "corrupt",
)

FORBIDDEN_FLAG_PREFIXES: Tuple[str, ...] = (
    "unknown_token",
    "duplicate_token",
    "orphan_money_tokens",
    "ambiguous",
    "multi_invoice_suspected",
    "low_conf",
    "low_confidence",
)


def is_auto_doc_type(doc_type: Any) -> bool:
    """Check if a document type is eligible for automatic VERIFIED status."""
    if isinstance(doc_type, DocType):
        return doc_type in AUTO_DOC_TYPES
    if isinstance(doc_type, str):
        return doc_type.lower() in AUTO_DOC_TYPE_VALUES
    return False


def is_fatal_flag(flag: str) -> bool:
    """Check if a flag indicates a fatal processing failure."""
    flag_clean = flag.strip().lower()
    return any(flag_clean.startswith(prefix) for prefix in FATAL_FAIL_PREFIXES)


def is_forbidden_flag(flag: str) -> bool:
    """Check if a rehydrator flag blocks automatic verification."""
    flag_clean = flag.strip().lower()
    return any(
        flag_clean.startswith(prefix)
        for prefix in (FORBIDDEN_FLAG_PREFIXES + FATAL_FAIL_PREFIXES)
    )


def check_low_confidence_numbers(
    invoice: CanonicalInvoice,
    threshold: float = OCR_CONFIDENCE_THRESHOLD,
) -> List[str]:
    """Check all numbers participating in calculations for low OCR confidence.

    In accordance with PLAN 5.5 and financial privacy guidelines, raw numeric
    values are never included in the review reasons.

    Args:
        invoice: CanonicalInvoice instance.
        threshold: Minimum required OCR confidence (default from config).

    Returns:
        List of low-confidence warning messages.
    """
    low_conf_reasons: List[str] = []

    def _check_prov(prov: Optional[Provenance], location_desc: str) -> None:
        if prov is not None and prov.ocr_conf is not None:
            if float(prov.ocr_conf) < threshold:
                low_conf_reasons.append(
                    f"Low OCR confidence ({prov.ocr_conf:.2f} < {threshold:.2f}) on {location_desc} (page {prov.page})"
                )

    # Check line items participating in Tier 1 and Tier 2
    for idx, item in enumerate(invoice.line_items, start=1):
        if item.line_total is not None:
            _check_prov(item.line_total_prov, f"line {idx} line_total")
        if item.qty is not None:
            _check_prov(item.qty_prov, f"line {idx} qty")
        if item.unit_price is not None:
            _check_prov(item.unit_price_prov, f"line {idx} unit_price")

    # Check charges participating in Tier 4
    for idx, charge in enumerate(invoice.charges, start=1):
        if charge.amount is not None:
            desc = f"charge '{charge.description}'" if charge.description else f"charge {idx}"
            _check_prov(charge.amount_prov, f"{desc} amount")

    # Check document-level totals participating in Tier 3
    doc_total_fields: List[Tuple[str, Optional[Decimal], Optional[Provenance]]] = [
        ("subtotal", invoice.subtotal, invoice.subtotal_prov),
        ("tax", invoice.tax, invoice.tax_prov),
        ("discount", invoice.discount, invoice.discount_prov),
        ("shipping", invoice.shipping, invoice.shipping_prov),
        ("tip", invoice.tip, invoice.tip_prov),
        ("grand_total", invoice.grand_total, invoice.grand_total_prov),
        ("amount_due", invoice.amount_due, invoice.amount_due_prov),
    ]
    for field_name, val, prov in doc_total_fields:
        if val is not None:
            _check_prov(prov, f"document {field_name}")

    return low_conf_reasons


def assign_invoice_status(
    invoice: CanonicalInvoice,
    rehydrator_flags: Optional[List[str]] = None,
    target_month: Optional[str] = None,
) -> CanonicalInvoice:
    """Evaluate all mathematical tiers and flags to assign final InvoiceStatus.

    VERIFIED ONLY WHEN ALL CONDITIONS ARE MET:
    1. Tier 3 OR Tier 4 ran AND passed.
    2. Tier 1 & 2: >= 80% lines checkable and 0 line errors.
    3. NO low_conf on any numbers participating in calculations (< threshold).
    4. NO forbidden flags: unknown_token, duplicate_token, orphan_money_tokens,
       ambiguous_*, multi_invoice_suspected, or low_conf.
    5. doc_type in auto-verified types (goods_invoice, receipt, utility_bill, credit_memo).
    6. Date/metadata sanity checks pass.

    OTHERWISE:
    - REVIEW_NEEDED with detailed review_reasons (without leaking raw numeric values).
    - FAILED if file unreadable, fatal OCR or LLM failure.

    INVARIANT: NEVER assign VERIFIED if any mandatory check is missing or failed.

    Args:
        invoice: Rehydrated CanonicalInvoice.
        rehydrator_flags: Warning/error flags from token rehydration.
        target_month: Processing month 'YYYY-MM' for date window checking.

    Returns:
        Updated CanonicalInvoice with final status and review_reasons populated.
    """
    if invoice is None:
        raise ValueError("invoice cannot be None")

    reasons: List[str] = list(invoice.review_reasons)
    flags_list = list(rehydrator_flags) if rehydrator_flags else []

    # -------------------------------------------------------------
    # Step 0: Check for FAILED status (Fatal file, OCR, or LLM errors)
    # -------------------------------------------------------------
    has_fatal_flag = any(is_fatal_flag(f) for f in flags_list)
    if invoice.status == InvoiceStatus.FAILED or has_fatal_flag:
        invoice.status = InvoiceStatus.FAILED
        for f in flags_list:
            if f not in reasons:
                reasons.append(f)
        if not reasons:
            reasons.append("Fatal processing error: file unreadable, OCR or LLM failure")
        invoice.review_reasons = _dedup_list(reasons)
        return invoice

    # -------------------------------------------------------------
    # Step 1: Check document type eligibility
    # -------------------------------------------------------------
    doc_type_val = invoice.doc_type.value if isinstance(invoice.doc_type, DocType) else str(invoice.doc_type)
    if not is_auto_doc_type(invoice.doc_type):
        reasons.append(
            f"Document type '{doc_type_val}' requires manual review (not an auto-verified doc_type)"
        )

    # -------------------------------------------------------------
    # Step 2: Check rehydrator flags
    # -------------------------------------------------------------
    for f in flags_list:
        if f not in reasons:
            reasons.append(f)

    # -------------------------------------------------------------
    # Step 3: Check low confidence numbers participating in calculation
    # -------------------------------------------------------------
    low_conf_reasons = check_low_confidence_numbers(invoice, threshold=OCR_CONFIDENCE_THRESHOLD)
    if low_conf_reasons:
        for r in low_conf_reasons:
            if r not in reasons:
                reasons.append(r)

    # -------------------------------------------------------------
    # Step 4: Validate Tier 1 (Line Items) and Tier 2 (Subtotal)
    # -------------------------------------------------------------
    lines_ok = False
    if invoice.line_items:
        tier1_ratio_ok = False
        tier1_math_ok = False

        # Tier 1: individual line items
        try:
            t1_passed, t1_errors, checkable_count, uncheckable_count = validate_tier1_lines(invoice.line_items)
            goods_total = checkable_count + uncheckable_count

            if goods_total > 0:
                checkable_ratio = checkable_count / goods_total
                if checkable_ratio < MIN_CHECKABLE_LINE_RATIO:
                    reasons.append(
                        f"Checkable lines ratio {checkable_ratio:.1%} is below minimum threshold "
                        f"{MIN_CHECKABLE_LINE_RATIO:.1%} ({checkable_count}/{goods_total} checkable)"
                    )
                    tier1_ratio_ok = False
                else:
                    tier1_ratio_ok = True
            else:
                tier1_ratio_ok = True

            if not t1_passed or t1_errors:
                tier1_math_ok = False
                for err in t1_errors:
                    if err not in reasons:
                        reasons.append(err)
            else:
                tier1_math_ok = True

        except NotImplementedError:
            tier1_ratio_ok = False
            tier1_math_ok = False
            reasons.append("Tier 1 line validation not implemented")
        except Exception as exc:
            tier1_ratio_ok = False
            tier1_math_ok = False
            reasons.append(f"Tier 1 line validation error: {type(exc).__name__}")

        # Tier 2: subtotal consistency
        try:
            t2_passed, t2_errors = validate_tier2_subtotal(invoice)
            if not t2_passed or t2_errors:
                tier2_ok = False
                for err in t2_errors:
                    if err not in reasons:
                        reasons.append(err)
            else:
                tier2_ok = True
        except NotImplementedError:
            tier2_ok = False
            reasons.append("Tier 2 subtotal validation not implemented")
        except Exception as exc:
            tier2_ok = False
            reasons.append(f"Tier 2 subtotal validation error: {type(exc).__name__}")

        lines_ok = tier1_ratio_ok and tier1_math_ok and tier2_ok

    elif doc_type_val == DocType.UTILITY_BILL.value:
        # Utility bills typically have charges rather than itemized goods lines
        lines_ok = True
    elif doc_type_val == DocType.RECEIPT.value and invoice.charges and invoice.subtotal is None:
        # Non-subtotal receipts evaluated under Tier 4
        lines_ok = True
    else:
        # Itemized lines are mandatory for goods invoices, credit memos, standard receipts
        lines_ok = False
        reasons.append("Missing itemized line items for document requiring lines")

    # -------------------------------------------------------------
    # Step 5: Validate Tier 3 (Grand Total) OR Tier 4 (Utility Total)
    # -------------------------------------------------------------
    tier3_attempted = False
    tier3_passed = False
    tier3_errors: List[str] = []

    tier4_attempted = False
    tier4_passed = False
    tier4_errors: List[str] = []

    # Tier 3 evaluation: standard for goods invoices, credit memos, receipts with subtotal/grand_total
    is_non_subtotal_receipt = (
        doc_type_val == DocType.RECEIPT.value and bool(invoice.charges) and invoice.subtotal is None
    )
    if (
        doc_type_val != DocType.UTILITY_BILL.value
        and not is_non_subtotal_receipt
        and (invoice.grand_total is not None or invoice.subtotal is not None)
    ):
        tier3_attempted = True
        try:
            t3_ok, t3_errs = validate_tier3_grand_total(invoice)
            if t3_ok and not t3_errs:
                tier3_passed = True
            else:
                tier3_errors.extend(t3_errs)
        except NotImplementedError:
            tier3_errors.append("Tier 3 grand total validation not implemented")
        except Exception as exc:
            tier3_errors.append(f"Tier 3 validation error: {type(exc).__name__}")

    # Tier 4 evaluation: standard for utility bills and non-subtotal receipts with charges
    if doc_type_val == DocType.UTILITY_BILL.value or (
        invoice.charges and invoice.subtotal is None
    ):
        tier4_attempted = True
        try:
            t4_ok, t4_errs = validate_tier4_utility_total(invoice)
            if t4_ok and not t4_errs:
                tier4_passed = True
            else:
                tier4_errors.extend(t4_errs)
        except NotImplementedError:
            tier4_errors.append("Tier 4 utility total validation not implemented")
        except Exception as exc:
            tier4_errors.append(f"Tier 4 validation error: {type(exc).__name__}")

    # Total consistency verification
    totals_ok = False
    if doc_type_val == DocType.UTILITY_BILL.value or is_non_subtotal_receipt:
        if tier4_attempted and tier4_passed and not tier4_errors:
            totals_ok = True
        else:
            for err in tier4_errors:
                if err not in reasons:
                    reasons.append(err)
            if not tier4_attempted:
                reasons.append("Tier 4 utility total check could not be evaluated")
  
    else:
        if tier3_attempted or tier4_attempted:
            t3_ok = (tier3_passed and not tier3_errors) if tier3_attempted else True
            t4_ok = (tier4_passed and not tier4_errors) if tier4_attempted else True

            if tier3_attempted and (not tier3_passed or tier3_errors):
                for err in tier3_errors:
                    if err not in reasons:
                        reasons.append(err)

            if tier4_attempted and (not tier4_passed or tier4_errors):
                for err in tier4_errors:
                    if err not in reasons:
                        reasons.append(err)

            totals_ok = t3_ok and t4_ok
        else:
            reasons.append("Neither Tier 3 (grand total) nor Tier 4 (charges) could be evaluated")
            totals_ok = False

    # -------------------------------------------------------------
    # Step 6: Dates and metadata validation
    # -------------------------------------------------------------
    date_meta_ok = False
    try:
        meta_errors = validate_dates_and_metadata(invoice, target_month=target_month)
        if meta_errors:
            for err in meta_errors:
                if err not in reasons:
                    reasons.append(err)
        else:
            date_meta_ok = True
    except NotImplementedError:
        date_meta_ok = False
        reasons.append("Date and metadata validation not implemented")
    except Exception as exc:
        date_meta_ok = False
        reasons.append(f"Date and metadata validation error: {type(exc).__name__}")

    # -------------------------------------------------------------
    # Step 7: Final Status Assignment
    # -------------------------------------------------------------
    has_forbidden_flags = any(is_forbidden_flag(f) for f in flags_list)

    can_verify = (
        is_auto_doc_type(invoice.doc_type)
        and not has_forbidden_flags
        and not low_conf_reasons
        and lines_ok
        and totals_ok
        and date_meta_ok
        and (len(reasons) == 0)
    )

    if can_verify:
        invoice.status = InvoiceStatus.VERIFIED
        invoice.review_reasons = []
    else:
        invoice.status = InvoiceStatus.REVIEW_NEEDED
        invoice.review_reasons = _dedup_list(reasons)

    return invoice


def _dedup_list(items: Iterable[str]) -> List[str]:
    """Preserve order while removing duplicates."""
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
