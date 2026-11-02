"""Number parsing module.

PLAN 5.2: Locale-aware numeric parsing into Decimal.
Handles:
- US locale ("1,234.56"), EU/VN locale ("1.234,56").
- Negative formats: parenthesized "(12.50)", trailing minus "12.50-", credit "12.50 CR", leading "-12.50".
- Tax flags stripped ("33.99T" -> 33.99).
- Currency symbols stripped ("$12.50", "12.50 USD").
- Ambiguity detection ("1,234" without clear decimal vs thousands separator).
- Always returns Decimal, never float.
"""

from decimal import Decimal
import re
from typing import Optional


class AmbiguousNumberError(ValueError):
    """Raised when a number's locale cannot be determined unambiguously."""
    pass


_CURRENCY_CODES_PATTERN = re.compile(
    r'(?i)\b(?:USD|EUR|GBP|VND|CAD|AUD|JPY|SGD|CHF)\b'
)
_CREDIT_PATTERN = re.compile(
    r'(?i)(?:\bCR\b|\bCREDIT\b|(?<=\d)CR\b|\bCR(?=\d))'
)
_DEBIT_PATTERN = re.compile(
    r'(?i)\b(?:DB|DR)\b'
)
_TAX_FLAG_PATTERN = re.compile(
    r'(?i)(?<=\d|\.)\s*(?:TX|TAX|T|F|N|E|X)\s*$'
)
_DIGIT_SPACE_PATTERN = re.compile(
    r'(?<=\d)\s+(?=\d)'
)


def parse_number(
    raw: str,
    neg_hint: bool = False,
    document_locale: Optional[str] = None
) -> Decimal:
    """Parse a numeric string into Decimal.

    Args:
        raw: Raw string from vault or OCR.
        neg_hint: Optional boolean hint indicating negative value from token hint.
        document_locale: Detected locale ("US", "EU_VN", or None for auto-detect).

    Returns:
        Decimal representation of the numeric value.

    Raises:
        AmbiguousNumberError: If format is ambiguous without locale context.
        ValueError: If text cannot be parsed into a number.
    """
    if raw is None or not isinstance(raw, str):
        raise ValueError("Invalid numeric input")

    if document_locale is not None:
        document_locale = document_locale.upper()
        if document_locale not in ("US", "EU_VN"):
            raise ValueError("Invalid document_locale")

    s = raw.strip()
    if not s:
        raise ValueError("Empty numeric string")

    # Invariant: neg_hint forces negative sign
    is_negative = bool(neg_hint)

    # Normalize whitespace
    s = s.replace('\u00a0', ' ').replace('\u202f', ' ').strip()

    # Credit / debit flags
    if _CREDIT_PATTERN.search(s):
        is_negative = True
        s = _CREDIT_PATTERN.sub('', s).strip()
    if _DEBIT_PATTERN.search(s):
        s = _DEBIT_PATTERN.sub('', s).strip()

    # Repeatedly strip surrounding symbols, currency, minuses, and tax flags
    changed = True
    while changed:
        orig = s

        # Outer parentheses e.g. (12.50), ($12.50)
        m_paren = re.match(r'^\((.*)\)$', s)
        if m_paren:
            is_negative = True
            s = m_paren.group(1).strip()

        # Currency codes
        s = _CURRENCY_CODES_PATTERN.sub('', s).strip()

        # Unicode / ASCII minus characters: -, − (U+2212), – (U+2013), — (U+2014)
        if any(s.endswith(ch) for ch in "-−–—"):
            is_negative = True
            s = s.rstrip("-−–— ").strip()
        if any(s.startswith(ch) for ch in "-−–—"):
            is_negative = True
            s = s.lstrip("-−–— ").strip()

        # Explicit leading plus
        if s.startswith("+"):
            s = s.lstrip("+ ").strip()

        # Currency symbols: $, €, £, ¥, ₫, đ
        if any(s.startswith(ch) for ch in "$€£¥₫đ"):
            s = s.lstrip("$€£¥₫đ ").strip()
        if any(s.endswith(ch) for ch in "$€£¥₫đ"):
            s = s.rstrip("$€£¥₫đ ").strip()

        # Trailing tax flags: 33.99T, 33.99 F, 33.99TX
        s = _TAX_FLAG_PATTERN.sub('', s).strip()

        # Strip footnotes / annotations
        s = s.strip("*# ")

        changed = (s != orig)

    # Strip space between digits (thousands grouping e.g. "1 234,56")
    s = _DIGIT_SPACE_PATTERN.sub('', s).strip()

    if not s or not re.search(r'\d', s):
        raise ValueError("Invalid numeric format")

    # Handle leading/trailing decimal point without integer/fraction part
    if s.startswith('.') or s.startswith(','):
        s = '0' + s
    if s.endswith('.') or s.endswith(','):
        s = s[:-1]

    # Validate characters
    if not re.match(r'^\d[\d.,]*$', s):
        raise ValueError("Invalid numeric format")

    dot_count = s.count('.')
    comma_count = s.count(',')

    if dot_count == 0 and comma_count == 0:
        val = Decimal(s)

    elif dot_count > 0 and comma_count > 0:
        last_dot = s.rfind('.')
        last_comma = s.rfind(',')

        if last_dot > last_comma:
            # US format: 1,234.56 or 1,234,567.89
            int_part = s[:last_dot]
            dec_part = s[last_dot + 1:]
            parts = int_part.split(',')
            if not (1 <= len(parts[0]) <= 3) or any(len(p) != 3 for p in parts[1:]):
                raise ValueError("Invalid numeric format")
            if not dec_part.isdigit():
                raise ValueError("Invalid numeric format")
            val = Decimal(int_part.replace(',', '') + '.' + dec_part)
        else:
            # EU/VN format: 1.234,56 or 1.234.567,89
            int_part = s[:last_comma]
            dec_part = s[last_comma + 1:]
            parts = int_part.split('.')
            if not (1 <= len(parts[0]) <= 3) or any(len(p) != 3 for p in parts[1:]):
                raise ValueError("Invalid numeric format")
            if not dec_part.isdigit():
                raise ValueError("Invalid numeric format")
            val = Decimal(int_part.replace('.', '') + '.' + dec_part)

    elif comma_count > 0 and dot_count == 0:
        if comma_count > 1:
            # Multiple commas: must be thousands separators (1,234,567)
            parts = s.split(',')
            if not (1 <= len(parts[0]) <= 3) or any(len(p) != 3 for p in parts[1:]):
                raise ValueError("Invalid numeric format")
            val = Decimal(s.replace(',', ''))
        else:
            # Exactly one comma
            parts = s.split(',')
            left, right = parts[0], parts[1]
            if not left.isdigit() or not right.isdigit():
                raise ValueError("Invalid numeric format")

            if len(right) == 3 and (1 <= len(left) <= 3):
                # Ambiguous without locale context
                if document_locale == "US":
                    val = Decimal(left + right)
                elif document_locale == "EU_VN":
                    val = Decimal(left + '.' + right)
                else:
                    raise AmbiguousNumberError("Ambiguous numeric format without locale context")
            else:
                # Comma followed by non-3 digits (e.g. 12,50 or 12,5) is decimal
                val = Decimal(left + '.' + right)

    else:
        # dot_count > 0 and comma_count == 0
        if dot_count > 1:
            # Multiple dots: must be thousands separators (1.234.567)
            parts = s.split('.')
            if not (1 <= len(parts[0]) <= 3) or any(len(p) != 3 for p in parts[1:]):
                raise ValueError("Invalid numeric format")
            val = Decimal(s.replace('.', ''))
        else:
            # Exactly one dot
            parts = s.split('.')
            left, right = parts[0], parts[1]
            if not left.isdigit() or not right.isdigit():
                raise ValueError("Invalid numeric format")

            if len(right) == 3 and (1 <= len(left) <= 3) and document_locale == "EU_VN":
                # In EU/VN, dot with 3 digits is thousands separator (1.234 -> 1234)
                val = Decimal(left + right)
            else:
                # Decimal separator (US default)
                val = Decimal(left + '.' + right)

    if is_negative:
        val = -abs(val) if not val.is_zero() else abs(val)
    else:
        val = abs(val) if val.is_zero() else val

    return val


def detect_document_locale(texts: list[str]) -> str:
    """Infer dominant numeric locale from a list of number strings in a document.

    Args:
        texts: List of number strings from document.

    Returns:
        "US" or "EU_VN".
    """
    if not texts:
        return "US"

    eu_pattern = re.compile(r'\b\d{1,3}(?:\.\d{3})+,\d{2}\b')
    us_pattern = re.compile(r'\b\d{1,3}(?:,\d{3})+\.\d{2}\b')

    eu_score = 0
    us_score = 0

    for text in texts:
        if not isinstance(text, str):
            continue
        if eu_pattern.search(text):
            eu_score += 10
        if us_pattern.search(text):
            us_score += 10

        # Currency-assisted signals
        if re.search(r'(?i)(?:VND|₫|đ)', text) and re.search(r'\d{1,3}(?:\.\d{3})+', text):
            eu_score += 5
        if re.search(r'(?:€|\bEUR\b)', text) and re.search(r'\d+,\d{2}', text):
            eu_score += 5

        # Decimal format frequency
        if re.search(r'\b\d+,\d{2}\b', text) and not re.search(r'\.\d{2}\b', text):
            eu_score += 1
        if re.search(r'\b\d+\.\d{2}\b', text) and not re.search(r',\d{2}\b', text):
            us_score += 1

    if eu_score > us_score:
        return "EU_VN"
    return "US"
