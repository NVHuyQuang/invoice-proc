"""Contact PII redactor module.

PLAN 3.2: Redact email, URL, phone numbers (US/VN/int'l), card numbers, and long barcodes.
Replaces matches with <EMAIL>, <URL>, <PHONE>, <CARD>, <BARCODE>.
Must NOT redact or mask product specifications (e.g. 750ML, 12OZ).
"""

import re
from typing import Tuple, List, Dict, Any, NamedTuple


class SpanCandidate(NamedTuple):
    start: int
    end: int
    kind: str       # "card", "email", "url", "phone", "barcode"
    token: str      # "<CARD>", "<EMAIL>", "<URL>", "<PHONE>", "<BARCODE>"
    raw: str
    priority: int   # lower number = higher precedence


# 1. Product specifications protection regex
# Must NOT mask specs: 750ML, 12OZ, 500G, 5LB, A4, 6X32 OZ, 12x1 L, 24/12 OZ, 12-PACK, 6-CT, 10-INCH, etc.
SPEC_UNITS_REGEX = (
    r"(?:OZ|LB|ML|L|G|KG|CT|PK|PACK|CS|CASE|EA|GAL|INCH|PT|QT|FL\s*OZ|"
    r"DOZ|BAG|BOX|BTL|CAN|ROLL|TUB|JAR|TIN|PIECE|PAIR|SET)"
)

SPEC_PATTERN = re.compile(
    rf"\b(?:"
    rf"\d+(?:\.\d+)?\s*{SPEC_UNITS_REGEX}\b"
    rf"|[A-B][1-6]\b"
    rf"|\d+\s*[xX/]\s*\d+(?:\.\d+)?\s*{SPEC_UNITS_REGEX}\b"
    rf"|\d+\s*-\s*{SPEC_UNITS_REGEX}\b"
    rf")",
    re.IGNORECASE,
)

# 2. Date patterns protection (prevent confusing date with phone / card / barcode)
DATE_PATTERN = re.compile(
    r"\b(?:"
    r"(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])\b"
    r"|(?:0?[1-9]|[12]\d|3[01])[-/.](?:0?[1-9]|1[0-2])[-/.](?:19|20)\d{2}\b"
    r"|(?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])[-/.](?:19|20)\d{2}\b"
    r"|\d{1,2}[-\s](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-\s](?:19|20)?\d{2}\b"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+(?:19|20)\d{2}\b"
    r")",
    re.IGNORECASE,
)

# 3. Existing tokens protection (never modify already generated tokens like <ADDR>, <N_1>, etc.)
EXISTING_TOKEN_PATTERN = re.compile(r"<[A-Z0-9_:]+>")

# 4. CARD patterns
CARD_BRAND_ENDING_PATTERN = re.compile(
    r"\b(?:(?:Visa|MasterCard|Mastercard|MC|Amex|American Express|Discover|JCB|Diners|Card|Debit|Credit)\s+)?"
    r"ending(?:\s+in)?\s*[:#-]?\s*(?:\*{1,4}\s*|[xX]{1,4}\s*)?(\d{4})\b",
    re.IGNORECASE,
)

CARD_MASKED_BLOCKS_PATTERN = re.compile(
    r"(?:^|(?<=[\s,;:\"\'\(\[]))(?:(?:\*{4}|[xX]{4})[ -]?){1,3}\d{4}\b"
)

CARD_MASKED_LONG_PATTERN = re.compile(
    r"(?:^|(?<=[\s,;:\"\'\(\[]))(?:\*{4,16}|[xX]{4,16})\s*\d{4}\b"
)

CARD_PARTIALLY_MASKED_PATTERN = re.compile(
    r"\b(?:\d{4}[ -]?)?(?:(?:\*{4}|[xX]{4})[ -]?){2}\d{4}\b"
)

CARD_FORMATTED_PATTERN = re.compile(
    r"\b\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{4}\b"
)

CARD_AMEX_PATTERN = re.compile(
    r"\b3[47]\d{2}[ -]\d{6}[ -]\d{5}\b"
)

CARD_LABELED_PATTERN = re.compile(
    r"(?i)\b(?:card|card\s*#|card\s*number|acct|account)\s*[:#]?\s*([0-9*-]{12,20})\b"
)

# 5. EMAIL pattern
EMAIL_PATTERN = re.compile(
    r"<?\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b>?"
)

# 6. URL patterns
URL_SCHEME_PATTERN = re.compile(
    r"\b(?:https?|ftp)://[^\s<>\"\'{}|\\^`\[\]]+"
)

URL_WWW_PATTERN = re.compile(
    r"\bwww\.[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+(?:/[^\s<>\"\'{}|\\^`\[\]]*)?"
)

URL_BARE_DOMAIN_PATTERN = re.compile(
    r"(?<!@)(?<![a-zA-Z0-9._%+-]@)\b[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\."
    r"(?:com|vn|org|net|edu|gov|io|ai|co|uk|us|de|jp|fr|au|ca|biz|info|store|shop|xyz|tech|app|me|com\.vn|edu\.vn|gov\.vn|org\.vn)"
    r"(?::\d+)?(?:/[^\s<>\"\'{}|\\^`\[\]]*)?\b",
    re.IGNORECASE,
)

# 7. PHONE patterns
US_PHONE_PATTERN = re.compile(
    r"(?:"
    r"(?:^|(?<=[\s,;:\"\'\[<]))(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\b\d{3})[-.\s]?\d{3}[-.\s]?\d{4}(?:\s*(?:ext\.?|x)\s*\d+)?\b"
    r"|\b1[-.\s]?8(?:00|88|77|66|55|44|33)[-.\s]?\d{3}[-.\s]?\d{4}\b"
    r")"
)

VN_MOBILE_PATTERN = re.compile(
    r"\b0[35789]\d(?:[-.\s]?\d){7}\b"
)

VN_LANDLINE_PATTERN = re.compile(
    r"(?:^|(?<=[\s,;:\"\'\[<]))(?:\b02\d{1,2}|\(02\d{1,2}\))(?:[-.\s]?\d){7,8}\b"
)

VN_INTL_PATTERN = re.compile(
    r"(?:^|(?<=[\s,;:\"\'\[<]))(?:\+84|\(\+84\)|0084|\(84\)|\b84)[-.\s]?(?:0?[35789]\d|2\d{1,2})(?:[-.\s]?\d){7,8}\b"
)

VN_HOTLINE_PATTERN = re.compile(
    r"\b(?:1900|1800)[-.\s]?\d{4}(?:[-.\s]?\d{2})?\b"
)

INTL_PHONE_PATTERN = re.compile(
    r"\+\d{1,3}[-.\s]?(?:\(?\d{1,4}\)?[-.\s]?){1,4}\d{2,4}\b"
)

LABELED_PHONE_PATTERN = re.compile(
    r"(?i)\b(?:tel|telephone|phone|hotline|fax|cell|mobile|sđt|đt|điện thoại)\s*[:#.]?\s*(\+?[\d()][\d\s().-]{5,}\d)"
)

# 8. BARCODE patterns
LABELED_BARCODE_PATTERN = re.compile(
    r"(?i)\b(?:barcode|upc|ean|jan|mã\s*vạch)\s*[:#]?\s*([A-Za-z0-9_-]{8,})\b"
)

STANDALONE_BARCODE_PATTERN = re.compile(
    r"\b\d{12,30}\b"
)


def _strip_trailing_punct(text: str, start: int, end: int) -> Tuple[int, int, str]:
    """Strip trailing punctuation marks commonly attached at the end of sentences."""
    val = text[start:end]
    while val and val[-1] in ".,;:!?)\"'>":
        val = val[:-1]
        end -= 1
    return start, end, val


def _has_overlap(s1: int, e1: int, s2: int, e2: int) -> bool:
    """Return True if two half-open intervals [s1, e1) and [s2, e2) overlap."""
    return max(s1, s2) < min(e1, e2)


def redact_contacts(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Redact emails, URLs, phone numbers, card numbers, and barcodes.

    Args:
        text: Input raw text.

    Returns:
        Tuple of (redacted_text, list_of_redaction_metadata).
    """
    if not text:
        return text, []

    # Step 1: Identify protected zones (specs, dates, existing tokens)
    protected_intervals: List[Tuple[int, int]] = []

    for m in SPEC_PATTERN.finditer(text):
        protected_intervals.append((m.start(), m.end()))

    for m in DATE_PATTERN.finditer(text):
        protected_intervals.append((m.start(), m.end()))

    for m in EXISTING_TOKEN_PATTERN.finditer(text):
        protected_intervals.append((m.start(), m.end()))

    candidates: List[SpanCandidate] = []

    # Step 2: Extract Card candidates (Priority 1)
    for m in CARD_BRAND_ENDING_PATTERN.finditer(text):
        candidates.append(SpanCandidate(m.start(), m.end(), "card", "<CARD>", m.group(0), 1))

    for m in CARD_MASKED_BLOCKS_PATTERN.finditer(text):
        candidates.append(SpanCandidate(m.start(), m.end(), "card", "<CARD>", m.group(0), 1))

    for m in CARD_MASKED_LONG_PATTERN.finditer(text):
        candidates.append(SpanCandidate(m.start(), m.end(), "card", "<CARD>", m.group(0), 1))

    for m in CARD_PARTIALLY_MASKED_PATTERN.finditer(text):
        candidates.append(SpanCandidate(m.start(), m.end(), "card", "<CARD>", m.group(0), 1))

    for m in CARD_FORMATTED_PATTERN.finditer(text):
        candidates.append(SpanCandidate(m.start(), m.end(), "card", "<CARD>", m.group(0), 1))

    for m in CARD_AMEX_PATTERN.finditer(text):
        candidates.append(SpanCandidate(m.start(), m.end(), "card", "<CARD>", m.group(0), 1))

    for m in CARD_LABELED_PATTERN.finditer(text):
        s, e = m.span(1)
        candidates.append(SpanCandidate(s, e, "card", "<CARD>", m.group(1), 1))

    # Step 3: Extract Email candidates (Priority 2)
    for m in EMAIL_PATTERN.finditer(text):
        s, e = m.start(), m.end()
        raw = m.group(0)
        candidates.append(SpanCandidate(s, e, "email", "<EMAIL>", raw, 2))

    # Step 4: Extract URL candidates (Priority 3)
    for m in URL_SCHEME_PATTERN.finditer(text):
        s, e, val = _strip_trailing_punct(text, m.start(), m.end())
        if val:
            candidates.append(SpanCandidate(s, e, "url", "<URL>", val, 3))

    for m in URL_WWW_PATTERN.finditer(text):
        s, e, val = _strip_trailing_punct(text, m.start(), m.end())
        if val:
            candidates.append(SpanCandidate(s, e, "url", "<URL>", val, 3))

    for m in URL_BARE_DOMAIN_PATTERN.finditer(text):
        s, e, val = _strip_trailing_punct(text, m.start(), m.end())
        if val:
            candidates.append(SpanCandidate(s, e, "url", "<URL>", val, 3))

    # Step 5: Extract Phone candidates (Priority 4)
    for m in US_PHONE_PATTERN.finditer(text):
        candidates.append(SpanCandidate(m.start(), m.end(), "phone", "<PHONE>", m.group(0), 4))

    for m in VN_MOBILE_PATTERN.finditer(text):
        candidates.append(SpanCandidate(m.start(), m.end(), "phone", "<PHONE>", m.group(0), 4))

    for m in VN_LANDLINE_PATTERN.finditer(text):
        candidates.append(SpanCandidate(m.start(), m.end(), "phone", "<PHONE>", m.group(0), 4))

    for m in VN_INTL_PATTERN.finditer(text):
        candidates.append(SpanCandidate(m.start(), m.end(), "phone", "<PHONE>", m.group(0), 4))

    for m in VN_HOTLINE_PATTERN.finditer(text):
        candidates.append(SpanCandidate(m.start(), m.end(), "phone", "<PHONE>", m.group(0), 4))

    for m in INTL_PHONE_PATTERN.finditer(text):
        # Validate that international numbers have between 7 and 15 digits
        digits_count = sum(c.isdigit() for c in m.group(0))
        if 7 <= digits_count <= 15:
            candidates.append(SpanCandidate(m.start(), m.end(), "phone", "<PHONE>", m.group(0), 4))

    for m in LABELED_PHONE_PATTERN.finditer(text):
        s, e = m.span(1)
        raw = m.group(1)
        digits_count = sum(c.isdigit() for c in raw)
        if digits_count >= 6:
            candidates.append(SpanCandidate(s, e, "phone", "<PHONE>", raw, 4))

    # Step 6: Extract Barcode candidates (Priority 5)
    for m in LABELED_BARCODE_PATTERN.finditer(text):
        s, e = m.span(1)
        candidates.append(SpanCandidate(s, e, "barcode", "<BARCODE>", m.group(1), 5))

    for m in STANDALONE_BARCODE_PATTERN.finditer(text):
        candidates.append(SpanCandidate(m.start(), m.end(), "barcode", "<BARCODE>", m.group(0), 5))

    # Step 7: Filter out candidates that overlap with protected zones (specs, dates, existing tokens)
    valid_candidates: List[SpanCandidate] = []
    for c in candidates:
        if any(_has_overlap(c.start, c.end, ps, pe) for ps, pe in protected_intervals):
            continue
        valid_candidates.append(c)

    # Step 8: Resolve overlapping candidates by precedence and length
    # Sort key: priority asc, length desc, start asc
    valid_candidates.sort(key=lambda c: (c.priority, -(c.end - c.start), c.start))

    accepted: List[SpanCandidate] = []
    claimed_mask = bytearray(len(text))

    for c in valid_candidates:
        if any(claimed_mask[i] for i in range(c.start, c.end)):
            continue
        for i in range(c.start, c.end):
            claimed_mask[i] = 1
        accepted.append(c)

    # Step 9: Re-sort accepted candidates by start position ascending
    accepted.sort(key=lambda c: c.start)

    # Step 10: Build redacted text and metadata events
    pieces: List[str] = []
    events: List[Dict[str, Any]] = []
    last_idx = 0

    for c in accepted:
        pieces.append(text[last_idx:c.start])
        pieces.append(c.token)
        events.append({
            "type": c.kind,
            "token": c.token,
            "raw": c.raw,
            "start": c.start,
            "end": c.end,
        })
        last_idx = c.end

    pieces.append(text[last_idx:])
    redacted_text = "".join(pieces)

    return redacted_text, events
