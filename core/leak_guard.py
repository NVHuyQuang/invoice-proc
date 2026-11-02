"""Leak Guard pre-egress payload validator.

PLAN 3.5: Mandatory pre-send gate for all LLM payloads.
Rejects any payload containing:
- Raw money strings (e.g. \\d+[.,]\\d{2}\\b)
- Consecutive 4+ digits not matching protected specification patterns
- Unmasked email, phone, card number, or URL patterns
- Exceeds MAX_PAYLOAD_CHARS
Crucial invariant: Never logs or prints the offending raw text in logs or exceptions.
"""

import logging
import re
import unicodedata
from typing import Tuple, List, Optional, Set
from config import MAX_PAYLOAD_CHARS, SPEC_UNITS

logger = logging.getLogger(__name__)

# Rule identifier constants
RULE_MAX_PAYLOAD = "max_payload_chars"
RULE_RAW_MONEY = "raw_money"
RULE_CONSECUTIVE_DIGITS = "consecutive_digits"
RULE_EMAIL = "email"
RULE_PHONE = "phone"
RULE_CARD = "card_number"
RULE_URL = "url"


class LeakGuardViolation(Exception):
    """Raised when an unmasked sensitive token or pattern is detected in egress payload."""

    def __init__(self, rule_name: str, line_no: int) -> None:
        super().__init__(f"LeakGuard violation: rule '{rule_name}' failed at line {line_no}")
        self.rule_name = rule_name
        self.line_no = line_no


# Legitimate tokens produced by tokenizer and redactor (PLAN 3.2, 3.3)
# Valid formats: <N_k>, <N_k:hint>, <D_k>, <ID_k>, <ADDR>, <PHONE>, <EMAIL>, <URL>, <CARD>, <PERSON>, <BARCODE>
TOKEN_PATTERN = re.compile(
    r"<(?:N_\d+(?::[a-zA-Z]{2,10})?|D_\d+|ID_\d+|(?:ADDR|PHONE|EMAIL|URL|CARD|PERSON|BARCODE)(?:_\d+)?(?::[a-zA-Z]{2,10})?)>"
)

# Invisible / zero-width characters and unusual whitespace used in evasion attacks
INVISIBLE_CHARS = re.compile(r"[\u2000-\u200f\ufeff\u202a-\u202e\u202f\u205f\u2060\u3000\u00a0]")

# Specifications from config.py and PLAN 3.4
_units_pattern = "|".join(sorted([re.escape(u) for u in SPEC_UNITS], key=len, reverse=True))

# 1. Connected: digits immediately followed by unit (no space), e.g. 750ML, 5LB, 12OZ, 500G, 1000ML
SPEC_CONNECTED = re.compile(rf"\b\d+(?:\.\d+)?(?:{_units_pattern})\b", re.IGNORECASE)

# Paper sizes: A0 to A9
SPEC_PAPER = re.compile(r"\bA\d\b", re.IGNORECASE)

# 2. Hyphenated: digits-unit, e.g. 12-PACK, 6-CT, 10-INCH, 1000-CT
SPEC_HYPHEN = re.compile(rf"\b\d+(?:\.\d+)?-(?:{_units_pattern})\b", re.IGNORECASE)

# 3. Multiplier / division: NxM unit, N/M unit, e.g. 6X32 OZ, 12x1 L, 24/12 OZ, 4x1000 ML
SPEC_MULT = re.compile(rf"\b\d+\s*[xX/]\s*\d+(?:\.\d+)?\s*(?:{_units_pattern})\b", re.IGNORECASE)

# Money / currency patterns (PLAN 3.3, 3.5)
# Catches $33.99, 33.99, 1,234.56, 1.234,56, (12.50), 12.50-, 12.50 CR, -12.50, 33.99T, @ 3.50, etc.
MONEY_PATTERN = re.compile(
    r"(?:"
    r"[\$€£¥₫]\s*\d+(?:[.,]\d+)?|"               # $10, €20.50, ₫1000
    r"\d+(?:[.,]\d+)?\s*[\$€£¥₫]|"               # 10$, 50.00€, 50000₫
    r"\b(?:USD|EUR|GBP|VND|CAD|AUD)\s*[:=]?\s*\d+(?:[.,]\d+)?\b|" # USD 50, EUR: 100
    r"\b\d+(?:[.,]\d+)?\s*(?:USD|EUR|GBP|VND|CAD|AUD|đ)\b|"       # 50 USD, 50000 đ
    r"(?<![a-zA-Z0-9])\d+[.,]\d{2}(?:\s*[TF])?(?![0-9])|"        # 33.99, 12.50, 1,234.56, 1.234,56, 12,50, 33.99T, <N_33.99>
    r"\(\s*\d+(?:[.,]\d+)?\s*\)|"                 # (12.50), (100)
    r"\b\d+(?:[.,]\d+)?\s*(?:CR|DR)\b|"          # 12.50 CR, 50 DR
    r"\b\d+[.,]\d{2}\s*-\b|"                     # 12.50-
    r"-\s*\d+[.,]\d{2}\b|"                       # -12.50
    r"@\s*\d+(?:[.,]\d+)?|"                      # @ 3.50, @ 10
    r"\b\d{1,3}(?:,\d{3})+|"                     # 1,000, 10,000, 1,000,000
    r"\b\d{1,3}(?:\.\d{3})+,\d{2}\b"             # 1.000.000,00
    r")",
    re.IGNORECASE
)

# Email pattern
EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# URL pattern (excludes email addresses by pre-masking emails)
URL_PATTERN = re.compile(
    r"(?:"
    r"https?://\S+|"
    r"www\.[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\S*|"
    r"\b[a-zA-Z0-9-]{2,}\.(?:com|org|net|edu|gov|io|vn|info|biz|ai)\b(?:/\S*)?"
    r")",
    re.IGNORECASE
)

# Phone pattern (US, VN, international, labeled)
PHONE_PATTERN = re.compile(
    r"(?:"
    r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b|"           # US format
    r"(?:\+?84|0)[35789]\d{8}\b|"                                        # VN mobile 10 digits
    r"(?:\+?84|0)[35789](?:[-.\s]?\d{2,4}){2,3}\b|"                     # VN mobile with separators
    r"(?:\+?84|0)2\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}\b|"                 # VN landline
    r"\+\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b|"    # International
    r"\b(?:Tel|Phone|Fax|Mobile|Cell|Hotline)[:\s]+[+\d()-. ]{7,}\b"     # Labeled phone
    r")",
    re.IGNORECASE
)

# Card pattern (16-digit raw, Amex 15-digit, masked **** 1234, brand ending 1234)
CARD_PATTERN = re.compile(
    r"(?:"
    r"\b(?:\d{4}[-\s]?){3}\d{4}\b|"                                       # 16-digit card
    r"\b3[47]\d{2}[-\s]?\d{6}[-\s]?\d{5}\b|"                              # 15-digit Amex
    r"(?:\*{4}|[xX]{4})[-\s]*\d{4}\b|"                                    # **** 1234, xxxx 1234
    r"\b(?:Visa|Mastercard|MasterCard|MC|Amex|AMEX|Discover)\s+(?:ending\s+(?:in\s+)?|x+|\*+)\s*\d{4}\b|" # Visa ending 1234
    r"\bCard\s+(?:ending\s+(?:in\s+)?|#|no\.?|num\.?)[:\s]*[\*xX\d-]{4,}\b"
    r")",
    re.IGNORECASE
)

# Consecutive digits pattern (>= 4 digits)
CONSECUTIVE_DIGITS_PATTERN = re.compile(r"\d{4,}")


def _scan_line(line: str, line_no: int) -> List[Tuple[str, int]]:
    """Scan a single line for leak patterns.

    Returns a list of (rule_name, line_no) tuples.
    Never exposes matched text.
    """
    detected: List[Tuple[str, int]] = []
    seen_rules: Set[str] = set()

    # Step 0: Unicode normalization & strip invisible/zero-width characters
    normalized = unicodedata.normalize("NFKC", line)
    cleaned = INVISIBLE_CHARS.sub("", normalized)

    # Step 1: Replace legitimate tokens with safe placeholder
    token_masked = TOKEN_PATTERN.sub("[TOKEN]", cleaned)

    # Step 2: Check Email
    if EMAIL_PATTERN.search(token_masked):
        if RULE_EMAIL not in seen_rules:
            detected.append((RULE_EMAIL, line_no))
            seen_rules.add(RULE_EMAIL)
    no_email = EMAIL_PATTERN.sub("[EMAIL]", token_masked)

    # Step 3: Check URL (on email-masked string so email domains are not double-flagged)
    if URL_PATTERN.search(no_email):
        if RULE_URL not in seen_rules:
            detected.append((RULE_URL, line_no))
            seen_rules.add(RULE_URL)
    no_url = URL_PATTERN.sub("[URL]", no_email)

    # Step 4: Check Card Number
    if CARD_PATTERN.search(token_masked):
        if RULE_CARD not in seen_rules:
            detected.append((RULE_CARD, line_no))
            seen_rules.add(RULE_CARD)
    no_card = CARD_PATTERN.sub("[CARD]", no_url)

    # Step 5: Check Phone (on card-masked string)
    if PHONE_PATTERN.search(no_card):
        if RULE_PHONE not in seen_rules:
            detected.append((RULE_PHONE, line_no))
            seen_rules.add(RULE_PHONE)
    no_phone = PHONE_PATTERN.sub("[PHONE]", no_card)

    # Step 6: Check Raw Money
    condensed_digits = re.sub(r"(?<=\d)\s+(?=\d|[.,])", "", token_masked)
    condensed_digits = re.sub(r"(?<=[.,])\s+(?=\d)", "", condensed_digits)
    if MONEY_PATTERN.search(token_masked) or MONEY_PATTERN.search(condensed_digits):
        if RULE_RAW_MONEY not in seen_rules:
            detected.append((RULE_RAW_MONEY, line_no))
            seen_rules.add(RULE_RAW_MONEY)

    # Step 7: Check Consecutive 4+ Digits (excluding valid specifications under PLAN 3.4)
    # Mask specifications first so valid spec digits do not trigger false positives
    spec_masked = SPEC_MULT.sub("[SPEC]", no_phone)
    spec_masked = SPEC_HYPHEN.sub("[SPEC]", spec_masked)
    spec_masked = SPEC_CONNECTED.sub("[SPEC]", spec_masked)
    spec_masked = SPEC_PAPER.sub("[SPEC]", spec_masked)

    condensed_specs = re.sub(r"(?<=\d)\s+(?=\d)", "", spec_masked)
    if CONSECUTIVE_DIGITS_PATTERN.search(spec_masked) or CONSECUTIVE_DIGITS_PATTERN.search(condensed_specs):
        if RULE_CONSECUTIVE_DIGITS not in seen_rules:
            detected.append((RULE_CONSECUTIVE_DIGITS, line_no))
            seen_rules.add(RULE_CONSECUTIVE_DIGITS)

    return detected


def verify_payload(payload: str, strict: bool = False) -> Tuple[bool, List[str]]:
    """Scan payload before sending to LLM.

    PLAN 3.5: Mandatory pre-send gate for all LLM payloads.
    Hard invariant: Never logs or prints the offending raw text in logs or exceptions.

    Args:
        payload: Masked document string ready for egress.
        strict: If True, raises LeakGuardViolation on first detected violation.

    Returns:
        Tuple of (is_valid, list_of_violation_summaries).

    Raises:
        TypeError: If payload is not a string.
        LeakGuardViolation: If payload contains illegal sensitive patterns (when strict=True).
    """
    if not isinstance(payload, str):
        raise TypeError("Payload must be a string")

    violations: List[str] = []
    violation_pairs: List[Tuple[str, int]] = []

    # Check Rule: Payload size limit
    if len(payload) > MAX_PAYLOAD_CHARS:
        rule_name = RULE_MAX_PAYLOAD
        line_no = 1
        logger.warning("LeakGuard violation: rule '%s' failed at line %d", rule_name, line_no)
        violations.append(f"Rule '{rule_name}' failed at line {line_no}")
        violation_pairs.append((rule_name, line_no))

    # Check line-by-line for sensitive patterns
    lines = payload.splitlines()
    for line_idx, line in enumerate(lines, start=1):
        detected_pairs = _scan_line(line, line_idx)
        for rule_name, line_no in detected_pairs:
            logger.warning("LeakGuard violation: rule '%s' failed at line %d", rule_name, line_no)
            violations.append(f"Rule '{rule_name}' failed at line {line_no}")
            violation_pairs.append((rule_name, line_no))

    is_valid = len(violations) == 0

    if not is_valid and strict:
        first_rule, first_line = violation_pairs[0]
        raise LeakGuardViolation(first_rule, first_line)

    return is_valid, violations
