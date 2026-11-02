"""Rehydration and token-verification module.

PLAN 5.1, 5.3:
Pre-rehydration checks:
1. Token must exist in vault (reject ghost tokens -> unknown_token).
2. Token must not be reused across numeric fields (duplicate_token).
3. Coverage: all money tokens in vault must be assigned or listed in unassigned (orphan_money_tokens).
4. No real numbers in token references (reject \\d in _ref).

Rehydration:
- Map tokens to raw strings, parse to Decimal with locale detection and neg_hint.
- Parse dates to ISO YYYY-MM-DD; detect ambiguous dates.
- Propagate Provenance and low_conf flags.
"""

from collections import defaultdict
import datetime
from decimal import Decimal
import re
from typing import Tuple, List, Optional, Iterator

from config import DEFAULT_DATE_LOCALE, OCR_CONFIDENCE_THRESHOLD, Category, SCHEMA_VERSION
from core.numparse import AmbiguousNumberError, detect_document_locale, parse_number
from core.types import Vault, VaultEntry, Provenance
from models.schema import (
    LLMInvoice,
    CanonicalInvoice,
    CanonicalLineItem,
    CanonicalCharge,
    InvoiceStatus,
    LineItemKind,
    TOKEN_REF_PATTERN,
)


def _is_money_token(entry: VaultEntry) -> bool:
    """Check if vault entry is money or has decimal money format without currency symbol."""
    kind = getattr(entry, "kind", None)
    if kind == "money":
        return True
    if kind == "number":
        raw = getattr(entry, "raw", "")
        if isinstance(raw, str):
            cleaned = raw.strip().strip("()+-*# \t\n")
            cleaned = re.sub(r'(?i)\s*(?:TX|TAX|T|F|N|E|X)$', '', cleaned).strip()
            # Match decimal money format e.g. 12.50, 1,234.56, 1.234,56
            if re.search(r'\d+[.,]\d{2}$', cleaned):
                return True
    return False


class TokenVerificationError(Exception):
    """Raised when token references violate integrity or security rules."""
    pass


MONTH_NAMES = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9, "sept": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _normalize_token(token: str) -> str:
    """Strip whitespace and collapse ':neg>' modifier to base token."""
    token = token.strip()
    if token.endswith(":neg>"):
        return token[:-5] + ">"
    return token


def _resolve_vault_entry(vault: Vault, token: str) -> Optional[VaultEntry]:
    """Lookup token in vault, supporting base and negative variants."""
    if not token:
        return None
    token = token.strip()
    entry = vault.get(token)
    if entry is not None:
        return entry
    norm = _normalize_token(token)
    entry = vault.get(norm)
    if entry is not None:
        return entry
    if not token.endswith(":neg>"):
        neg_token = token[:-1] + ":neg>"
        entry = vault.get(neg_token)
        if entry is not None:
            return entry
    return None


def _iter_all_refs(llm_invoice: LLMInvoice) -> Iterator[Tuple[str, Optional[str], bool]]:
    """Yield (field_path, value, is_numeric) across all token fields."""
    yield ("invoice_no_ref", llm_invoice.invoice_no_ref, False)
    yield ("invoice_date_ref", llm_invoice.invoice_date_ref, False)
    yield ("due_date_ref", llm_invoice.due_date_ref, False)

    for idx, item in enumerate(llm_invoice.line_items):
        yield (f"line_items[{idx}].qty_ref", item.qty_ref, True)
        yield (f"line_items[{idx}].unit_price_ref", item.unit_price_ref, True)
        yield (f"line_items[{idx}].line_total_ref", item.line_total_ref, True)
        if item.extra_refs:
            for k, v in item.extra_refs.items():
                yield (f"line_items[{idx}].extra_refs[{k}]", v, True)

    for idx, charge in enumerate(llm_invoice.charges):
        yield (f"charges[{idx}].amount_ref", charge.amount_ref, True)

    summary = llm_invoice.summary
    if summary:
        yield ("summary.subtotal_ref", summary.subtotal_ref, True)
        yield ("summary.tax_ref", summary.tax_ref, True)
        yield ("summary.discount_ref", summary.discount_ref, True)
        yield ("summary.shipping_ref", summary.shipping_ref, True)
        yield ("summary.tip_ref", summary.tip_ref, True)
        for idx, fee_ref in enumerate(summary.fees_ref):
            yield (f"summary.fees_ref[{idx}]", fee_ref, True)
        yield ("summary.grand_total_ref", summary.grand_total_ref, True)
        yield ("summary.amount_due_ref", summary.amount_due_ref, True)

    for idx, u_ref in enumerate(llm_invoice.unassigned):
        yield (f"unassigned[{idx}]", u_ref, False)


def verify_llm_tokens(llm_invoice: LLMInvoice, vault: Vault) -> Tuple[bool, List[str]]:
    """Verify integrity, existence, uniqueness, and coverage of token references.

    Args:
        llm_invoice: LLM output with token refs.
        vault: In-memory document Vault.

    Returns:
        Tuple of (is_valid, list_of_issues).

    Raises:
        TokenVerificationError: If raw numeric digits are detected in reference fields.
    """
    issues: List[str] = []

    # 1. Check for real numeric digits in any reference field
    for field_path, val, _ in _iter_all_refs(llm_invoice):
        if val is None:
            continue
        if not isinstance(val, str):
            raise TokenVerificationError(f"Non-string or numeric value in reference field: {field_path}")
        val_str = val.strip()
        if not val_str:
            continue
        if re.search(r"\d", val_str) and not TOKEN_REF_PATTERN.match(val_str):
            raise TokenVerificationError(
                f"Real number character detected in token reference '{field_path}'"
            )

    # 2. Check token existence in vault
    has_unknown = False
    for path, val, _ in _iter_all_refs(llm_invoice):
        if path.startswith("unassigned"):
            continue
        if val:
            val_str = val.strip()
            if val_str and _resolve_vault_entry(vault, val_str) is None:
                has_unknown = True
                break
    if has_unknown:
        issues.append("unknown_token")

    # 3. Uniqueness: each token only used once across numeric fields
    numeric_counts = defaultdict(int)
    for _, val, is_numeric in _iter_all_refs(llm_invoice):
        if is_numeric and val:
            val_str = val.strip()
            if val_str:
                norm = _normalize_token(val_str)
                numeric_counts[norm] += 1

    # Check duplicate_token: also check invoice_no_ref if it points to a numeric token
    if llm_invoice.invoice_no_ref:
        inv_no_str = llm_invoice.invoice_no_ref.strip()
        if inv_no_str:
            inv_no_norm = _normalize_token(inv_no_str)
            inv_entry = _resolve_vault_entry(vault, inv_no_norm)
            is_inv_numeric = (
                (inv_entry is not None and getattr(inv_entry, "kind", None) in ("number", "money"))
                or inv_no_norm.startswith("<N_")
            )
            if is_inv_numeric:
                numeric_counts[inv_no_norm] += 1

    has_duplicate = any(count > 1 for count in numeric_counts.values())
    unassigned_tokens = {
        _normalize_token(u.strip())
        for u in llm_invoice.unassigned
        if u and isinstance(u, str)
    }
    if not has_duplicate:
        # Also check if a numeric token is mistakenly listed in unassigned
        if any(norm in unassigned_tokens for norm in numeric_counts):
            has_duplicate = True

    if has_duplicate:
        issues.append("duplicate_token")

    # 4. Coverage: all money tokens in vault must appear in numeric fields or unassigned
    all_used_tokens = set()
    for _, val, _ in _iter_all_refs(llm_invoice):
        if val and isinstance(val, str):
            val_str = val.strip()
            if val_str:
                all_used_tokens.add(_normalize_token(val_str))

    money_vault_tokens = {
        _normalize_token(entry.token)
        for entry in vault.values()
        if _is_money_token(entry)
    }

    # Exclude rate tokens associated with summary percentages (e.g. tax rate '8.25%' preceding tax amount)
    rate_tokens = set()
    summary = llm_invoice.summary
    if summary:
        for ref in [summary.tax_ref, summary.discount_ref, summary.tip_ref]:
            if ref and isinstance(ref, str):
                m = re.match(r"^<N_(\d+)(?::neg)?>$", ref.strip())
                if m:
                    k = int(m.group(1))
                    prev_tok = f"<N_{k - 1}>"
                    prev_entry = _resolve_vault_entry(vault, prev_tok)
                    if prev_entry is not None and getattr(prev_entry, "kind", None) == "number":
                        try:
                            cleaned_num = re.sub(r"[^\d.]", "", prev_entry.raw.replace(",", "."))
                            if cleaned_num:
                                raw_val = Decimal(cleaned_num)
                                if 0 < raw_val <= 100:
                                    rate_tokens.add(prev_tok)
                        except Exception:
                            pass

    orphan_money = (money_vault_tokens - all_used_tokens) - rate_tokens
    if orphan_money:
        issues.append("orphan_money_tokens")

    is_valid = len(issues) == 0
    return (is_valid, issues)


def _parse_decimal(raw: str, neg_hint: bool = False, locale: Optional[str] = None) -> Decimal:
    """Parse raw string to Decimal using core.numparse or internal fallback."""
    try:
        try:
            return parse_number(raw, neg_hint=neg_hint, document_locale=locale)
        except NotImplementedError:
            pass
    except AmbiguousNumberError:
        raise
    except Exception:
        pass

    if not raw or not isinstance(raw, str):
        raise ValueError(f"Invalid raw value for decimal parsing: {raw!r}")

    s = raw.strip()
    is_negative = bool(neg_hint)

    # Negative formats
    if s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1].strip()
    if s.endswith("-"):
        is_negative = True
        s = s[:-1].strip()
    if s.startswith("-"):
        is_negative = True
        s = s[1:].strip()
    if re.search(r"CR\b", s, re.IGNORECASE):
        is_negative = True
        s = re.sub(r"CR\b", "", s, flags=re.IGNORECASE).strip()

    # Strip currency symbols and text codes
    s = re.sub(r"[\$\€\£\¥\₫]", "", s)
    s = re.sub(r"\b(?:USD|VND|EUR|CAD|GBP)\b", "", s, flags=re.IGNORECASE)
    # Strip tax flags like 'T', 'F', 'TX' at end
    s = re.sub(r"\s*[TtFfXx]+\b", "", s).strip()

    # Detect separators
    if "," in s and "." in s:
        last_comma = s.rfind(",")
        last_dot = s.rfind(".")
        if last_comma < last_dot:
            # US format: 1,234.56
            s = s.replace(",", "")
        else:
            # EU/VN format: 1.234,56
            s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) == 2:
            s = parts[0] + "." + parts[1]
        elif locale == "EU_VN":
            s = s.replace(",", ".")
        else:
            if len(parts) == 2 and len(parts[1]) == 3:
                s = parts[0] + parts[1]
            else:
                s = s.replace(",", "")
    elif "." in s:
        parts = s.split(".")
        if locale == "EU_VN" and len(parts) == 2 and len(parts[1]) == 3:
            s = parts[0] + parts[1]

    s = s.replace(" ", "")
    val = Decimal(s)
    if is_negative:
        val = -abs(val)
    return val


def _parse_date(raw: str, default_locale: str = DEFAULT_DATE_LOCALE) -> Tuple[Optional[str], bool]:
    """Parse raw date string to ISO YYYY-MM-DD and report ambiguity.

    Returns:
        (iso_date, is_ambiguous)
    """
    if not raw or not isinstance(raw, str):
        return (None, True)

    s = raw.strip()
    # Strip trailing time component if present
    s = re.split(r"[\sT]\d{1,2}:", s)[0].strip().rstrip(",")

    # 1. Named month formats (unambiguous)
    month_match = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", raw.lower())
    if month_match:
        m_name = month_match.group(1)
        m_num = MONTH_NAMES[m_name]
        nums = [int(n) for n in re.findall(r"\d+", s)]
        if len(nums) >= 2:
            y = next((n for n in nums if 1900 <= n <= 2100), None)
            if y is None:
                y = next((n for n in nums if n >= 100), None)
            if y is None:
                # 2-digit year
                # If one number is > 31 it must be the year;
                # otherwise in expressions like "Aug 28, 26" or "28 Aug 26", the year is the last number
                if any(n > 31 for n in nums):
                    y_cand = next(n for n in reversed(nums) if n > 31)
                else:
                    y_cand = nums[-1]
                y = y_cand + 2000 if y_cand < 100 else y_cand
                d = next((n for n in nums if n != y_cand and 1 <= n <= 31), None)
            else:
                d = next((n for n in nums if (n != y and n != (y - 2000)) and 1 <= n <= 31), None)

            if y is not None and d is not None:
                try:
                    valid_d = datetime.date(y, m_num, d)
                    return (f"{valid_d.year:04d}-{valid_d.month:02d}-{valid_d.day:02d}", False)
                except ValueError:
                    return (None, True)

    # 2. ISO format YYYY-MM-DD or YYYY/MM/DD
    iso_match = re.match(r"^(\d{4})\s*[-/\.]\s*(\d{1,2})\s*[-/\.]\s*(\d{1,2})$", s)
    if iso_match:
        y = int(iso_match.group(1))
        m = int(iso_match.group(2))
        d = int(iso_match.group(3))
        try:
            valid_d = datetime.date(y, m, d)
            return (f"{valid_d.year:04d}-{valid_d.month:02d}-{valid_d.day:02d}", False)
        except ValueError:
            return (None, True)

    # 3. Numeric 3-component: MM/DD/YYYY or DD/MM/YYYY
    num_match = re.match(r"^(\d{1,2})\s*[-/\.]\s*(\d{1,2})\s*[-/\.]\s*(\d{2,4})$", s)
    if num_match:
        a = int(num_match.group(1))
        b = int(num_match.group(2))
        raw_year = int(num_match.group(3))
        y = raw_year + 2000 if raw_year < 100 else raw_year

        if a > 12 and b <= 12:
            try:
                valid_d = datetime.date(y, b, a)
                return (f"{valid_d.year:04d}-{valid_d.month:02d}-{valid_d.day:02d}", False)
            except ValueError:
                return (None, True)
        elif a <= 12 and b > 12:
            try:
                valid_d = datetime.date(y, a, b)
                return (f"{valid_d.year:04d}-{valid_d.month:02d}-{valid_d.day:02d}", False)
            except ValueError:
                return (None, True)
        elif a <= 12 and b <= 12:
            if a == b:
                try:
                    valid_d = datetime.date(y, a, b)
                    return (f"{valid_d.year:04d}-{valid_d.month:02d}-{valid_d.day:02d}", False)
                except ValueError:
                    return (None, True)
            # Ambiguous date
            if default_locale == "MM/DD":
                m, d = a, b
            else:
                m, d = b, a
            try:
                valid_d = datetime.date(y, m, d)
                return (f"{valid_d.year:04d}-{valid_d.month:02d}-{valid_d.day:02d}", True)
            except ValueError:
                return (None, True)

    return (None, True)


def _make_provenance(entry: VaultEntry) -> Provenance:
    """Create Provenance from a VaultEntry."""
    source = getattr(entry, "source", "pdf_text" if entry.conf >= 1.0 else "ocr")
    return Provenance(
        page=entry.page,
        bbox=entry.bbox,
        ocr_conf=entry.conf,
        source=source,
    )


def rehydrate_invoice(
    llm_invoice: LLMInvoice,
    vault: Vault,
    source_file: str,
    source_sha256: str,
    date_locale: Optional[str] = None,
) -> CanonicalInvoice:
    """Resolve token references into Decimal values and CanonicalInvoice data structure.

    Args:
        llm_invoice: Validated LLM output.
        vault: In-memory document Vault.
        source_file: File path.
        source_sha256: File SHA-256 hash.
        date_locale: Optional date format convention ("MM/DD" or "DD/MM").

    Returns:
        CanonicalInvoice with real numeric Decimals and Provenance.

    Raises:
        TokenVerificationError: If raw numeric digits are detected in reference fields.
    """
    eff_date_locale = date_locale or DEFAULT_DATE_LOCALE

    # Detect document locale from numeric entries in vault
    doc_numbers = [
        entry.raw
        for entry in vault.values()
        if getattr(entry, "kind", None) in ("number", "money") and isinstance(entry.raw, str)
    ]
    doc_locale = detect_document_locale(doc_numbers) if doc_numbers else None

    # 1. Pre-rehydration token verification
    _, issues = verify_llm_tokens(llm_invoice, vault)
    review_reasons: List[str] = list(issues)

    def _resolve_and_parse_num(token_ref: Optional[str]) -> Tuple[Optional[Decimal], Optional[Provenance]]:
        if not token_ref:
            return (None, None)
        entry = _resolve_vault_entry(vault, token_ref)
        if entry is None:
            return (None, None)
        if entry.conf < OCR_CONFIDENCE_THRESHOLD:
            if "low_conf" not in review_reasons:
                review_reasons.append("low_conf")
        neg = entry.neg_hint or token_ref.endswith(":neg>")
        try:
            val = _parse_decimal(entry.raw, neg_hint=neg, locale=doc_locale)
        except AmbiguousNumberError:
            if "ambiguous_number" not in review_reasons:
                review_reasons.append("ambiguous_number")
            val = None
        except Exception:
            val = None
        prov = _make_provenance(entry)
        return (val, prov)

    # Rehydrate header fields
    invoice_no: Optional[str] = None
    invoice_no_prov: Optional[Provenance] = None
    if llm_invoice.invoice_no_ref:
        entry = _resolve_vault_entry(vault, llm_invoice.invoice_no_ref)
        if entry is not None:
            invoice_no = entry.raw.strip()
            invoice_no_prov = _make_provenance(entry)
            if entry.conf < OCR_CONFIDENCE_THRESHOLD:
                if "low_conf" not in review_reasons:
                    review_reasons.append("low_conf")

    invoice_date: Optional[str] = None
    invoice_date_prov: Optional[Provenance] = None
    if llm_invoice.invoice_date_ref:
        entry = _resolve_vault_entry(vault, llm_invoice.invoice_date_ref)
        if entry is not None:
            parsed_d, is_ambig = _parse_date(entry.raw, default_locale=eff_date_locale)
            invoice_date = parsed_d
            invoice_date_prov = _make_provenance(entry)
            if is_ambig and "ambiguous_date" not in review_reasons:
                review_reasons.append("ambiguous_date")
            if entry.conf < OCR_CONFIDENCE_THRESHOLD:
                if "low_conf" not in review_reasons:
                    review_reasons.append("low_conf")

    due_date: Optional[str] = None
    due_date_prov: Optional[Provenance] = None
    if llm_invoice.due_date_ref:
        entry = _resolve_vault_entry(vault, llm_invoice.due_date_ref)
        if entry is not None:
            parsed_d, is_ambig = _parse_date(entry.raw, default_locale=eff_date_locale)
            due_date = parsed_d
            due_date_prov = _make_provenance(entry)
            if is_ambig and "ambiguous_date" not in review_reasons:
                review_reasons.append("ambiguous_date")
            if entry.conf < OCR_CONFIDENCE_THRESHOLD:
                if "low_conf" not in review_reasons:
                    review_reasons.append("low_conf")

    currency = llm_invoice.currency or "USD"
    if currency == "$":
        currency = "USD"

    category = llm_invoice.category if llm_invoice.category is not None else Category.OTHER

    # Rehydrate Line Items
    canonical_lines: List[CanonicalLineItem] = []
    for item in llm_invoice.line_items:
        qty, qty_prov = _resolve_and_parse_num(item.qty_ref)
        unit_price, up_prov = _resolve_and_parse_num(item.unit_price_ref)
        line_total, lt_prov = _resolve_and_parse_num(item.line_total_ref)

        checkable = (
            qty is not None
            and unit_price is not None
            and line_total is not None
            and item.kind == LineItemKind.GOODS
        )

        canonical_lines.append(
            CanonicalLineItem(
                item_name=item.item_name,
                qty=qty,
                qty_prov=qty_prov,
                unit_price=unit_price,
                unit_price_prov=up_prov,
                line_total=line_total,
                line_total_prov=lt_prov,
                unit=item.unit,
                kind=item.kind,
                checkable=checkable,
            )
        )

    # Rehydrate Charges
    canonical_charges: List[CanonicalCharge] = []
    for ch in llm_invoice.charges:
        amt, amt_prov = _resolve_and_parse_num(ch.amount_ref)
        if amt is None:
            if "charge_amount_parse_failed" not in review_reasons:
                review_reasons.append("charge_amount_parse_failed")
            amt = Decimal("0")
        canonical_charges.append(
            CanonicalCharge(
                description=ch.description,
                amount=amt,
                amount_prov=amt_prov,
            )
        )

    # Rehydrate Summary
    subtotal, subtotal_prov = _resolve_and_parse_num(llm_invoice.summary.subtotal_ref)
    tax, tax_prov = _resolve_and_parse_num(llm_invoice.summary.tax_ref)
    discount, discount_prov = _resolve_and_parse_num(llm_invoice.summary.discount_ref)
    shipping, shipping_prov = _resolve_and_parse_num(llm_invoice.summary.shipping_ref)
    tip, tip_prov = _resolve_and_parse_num(llm_invoice.summary.tip_ref)
    grand_total, gt_prov = _resolve_and_parse_num(llm_invoice.summary.grand_total_ref)
    amount_due, ad_prov = _resolve_and_parse_num(llm_invoice.summary.amount_due_ref)

    fees: List[Decimal] = []
    for fee_ref in llm_invoice.summary.fees_ref:
        fee_val, _ = _resolve_and_parse_num(fee_ref)
        if fee_val is not None:
            fees.append(fee_val)

    return CanonicalInvoice(
        source_file=source_file,
        source_sha256=source_sha256,
        status=InvoiceStatus.REVIEW_NEEDED,
        doc_type=llm_invoice.doc_type,
        vendor_name=llm_invoice.vendor_name,
        invoice_no=invoice_no,
        invoice_no_prov=invoice_no_prov,
        invoice_date=invoice_date,
        invoice_date_prov=invoice_date_prov,
        due_date=due_date,
        due_date_prov=due_date_prov,
        currency=currency,
        category=category,
        line_items=canonical_lines,
        charges=canonical_charges,
        subtotal=subtotal,
        subtotal_prov=subtotal_prov,
        tax=tax,
        tax_prov=tax_prov,
        discount=discount,
        discount_prov=discount_prov,
        shipping=shipping,
        shipping_prov=shipping_prov,
        tip=tip,
        tip_prov=tip_prov,
        fees=fees,
        grand_total=grand_total,
        grand_total_prov=gt_prov,
        amount_due=amount_due,
        amount_due_prov=ad_prov,
        review_reasons=review_reasons,
        schema_version=SCHEMA_VERSION,
    )
