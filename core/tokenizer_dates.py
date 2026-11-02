"""Date tokenizer module.

PLAN 3.3: Recognize and mask dates into sequential <D_k> tokens.
Formats: MM/DD/YYYY, DD.MM.YYYY, Aug 01, 2026, 2026-08-01, 01-Aug-26, etc.
Stores raw date strings in the Vault with kind='date'.
Does NOT ingest monetary amounts, quantities, or product specifications.
"""

import re
import datetime
from typing import Tuple, List, Optional
from core.types import Vault, VaultEntry

# Month names mapping for English names and common abbreviations
MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

MONTH_NAMES_LIST = [
    r"Jan(?:\.|uary)?",
    r"Feb(?:\.|ruary)?",
    r"Mar(?:\.|ch)?",
    r"Apr(?:\.|il)?",
    r"May",
    r"Jun(?:\.|e)?",
    r"Jul(?:\.|y)?",
    r"Aug(?:\.|ust)?",
    r"Sep(?:\.|t\.|t|tember)?",
    r"Oct(?:\.|ober)?",
    r"Nov(?:\.|ember)?",
    r"Dec(?:\.|ember)?",
]
MONTH_NAMES_RE = r"(?:" + "|".join(MONTH_NAMES_LIST) + r")"

# Alphanumeric month regexes
P_MONTH_DAY_YEAR = re.compile(
    rf"(?<![A-Za-z0-9_/\-])(?P<m>{MONTH_NAMES_RE})\s+(?P<d>\d{{1,2}}(?:st|nd|rd|th)?)(?:,)?\s+(?P<y>'?\d{{2}}|\d{{4}})(?![A-Za-z0-9_/\-])",
    re.IGNORECASE,
)

P_DAY_MONTH_YEAR = re.compile(
    rf"(?<![A-Za-z0-9_/\-])(?P<d>\d{{1,2}}(?:st|nd|rd|th)?)(?P<sep>[\s.\-/]+)(?P<m>{MONTH_NAMES_RE})(?P=sep)(?P<y>'?\d{{2}}|\d{{4}})(?![A-Za-z0-9_/\-])",
    re.IGNORECASE,
)

P_DAY_MONTH_YEAR_SPACE = re.compile(
    rf"(?<![A-Za-z0-9_/\-])(?P<d>\d{{1,2}}(?:st|nd|rd|th)?)\s+(?P<m>{MONTH_NAMES_RE})\s+(?P<y>'?\d{{2}}|\d{{4}})(?![A-Za-z0-9_/\-])",
    re.IGNORECASE,
)

P_MONTH_D_Y_HYPHEN = re.compile(
    rf"(?<![A-Za-z0-9_/\-])(?P<m>{MONTH_NAMES_RE})-(?P<d>\d{{1,2}}(?:st|nd|rd|th)?)-(?P<y>'?\d{{2}}|\d{{4}})(?![A-Za-z0-9_/\-])",
    re.IGNORECASE,
)

P_YEAR_MONTH_DAY = re.compile(
    rf"(?<![A-Za-z0-9_/\-])(?P<y>\d{{4}})-(?P<m>{MONTH_NAMES_RE})-(?P<d>\d{{1,2}}(?:st|nd|rd|th)?)(?![A-Za-z0-9_/\-])",
    re.IGNORECASE,
)

P_MONTH_YEAR = re.compile(
    rf"(?<![A-Za-z0-9_/\-])(?P<m>{MONTH_NAMES_RE})\s+(?P<y>19\d{{2}}|20\d{{2}})(?![A-Za-z0-9_/\-])",
    re.IGNORECASE,
)

# Numeric date regexes
LOOKAHEAD_NUMERIC = r"(?![A-Za-z0-9_]|[-/]\w|\.\d)"

P_NUM_ISO = re.compile(
    rf"(?<![A-Za-z0-9_/\-\.\$€£¥₫])(?P<y>\d{{4}})(?P<sep>[-/.])(?P<m>\d{{1,2}})(?P=sep)(?P<d>\d{{1,2}}){LOOKAHEAD_NUMERIC}"
)

P_NUM_4Y = re.compile(
    rf"(?<![A-Za-z0-9_/\-\.\$€£¥₫])(?P<p1>\d{{1,2}})(?P<sep>[-/.])(?P<p2>\d{{1,2}})(?P=sep)(?P<y>\d{{4}}){LOOKAHEAD_NUMERIC}"
)

P_NUM_2Y = re.compile(
    rf"(?<![A-Za-z0-9_/\-\.\$€£¥₫])(?P<p1>\d{{1,2}})(?P<sep>[-/.])(?P<p2>\d{{1,2}})(?P=sep)(?P<y>\d{{2}}){LOOKAHEAD_NUMERIC}"
)


def _clean_ordinal(day_str: str) -> int:
    """Strip ordinal suffixes (st, nd, rd, th) from day string."""
    cleaned = re.sub(r"(?:st|nd|rd|th)$", "", day_str, flags=re.IGNORECASE)
    return int(cleaned)


def _clean_year(year_str: str) -> int:
    """Normalize 2-digit or 4-digit year string to 4-digit integer."""
    year_str = year_str.lstrip("'")
    y = int(year_str)
    if y < 100:
        y += 2000 if y < 50 else 1900
    return y


def _is_valid_date(year: int, month: int, day: int) -> bool:
    """Validate calendar date within supported business range (1900-2099)."""
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return False
    if year < 100:
        year += 2000 if year < 50 else 1900
    if not (1900 <= year <= 2099):
        return False
    try:
        datetime.date(year, month, day)
        return True
    except (ValueError, OverflowError):
        return False


def _parse_month_name(m_str: str) -> int:
    """Convert month name or abbreviation to 1-12 integer."""
    clean_m = m_str.rstrip(".").lower()
    return MONTH_MAP.get(clean_m, 0)


def _is_preceded_by_currency(text: str, start: int) -> bool:
    """Check if matched span is immediately preceded by a currency symbol."""
    prefix = text[:start]
    return bool(re.search(r"(?:[$€£¥₫]|\b(?:USD|VND|EUR|GBP|CAD|AUD))\s*$", prefix, re.IGNORECASE))


def _is_followed_by_currency(text: str, end: int) -> bool:
    """Check if matched span is immediately followed by a standalone currency code."""
    suffix = text[end:]
    return bool(re.match(r"^\s*(?:USD|VND|EUR|GBP|CAD|AUD)\b(?!\s*[\d\$])", suffix, re.IGNORECASE))


def _find_date_spans(text: str) -> List[Tuple[int, int, str]]:
    """Scan text and return non-overlapping (start, end, raw_date_str) tuples."""
    matches: List[Tuple[int, int, str]] = []

    def check_match(m: re.Match, kind: str) -> None:
        start, end = m.start(), m.end()
        if _is_preceded_by_currency(text, start):
            return
        if _is_followed_by_currency(text, end):
            return

        if kind == "month_day_year":
            m_val = _parse_month_name(m.group("m"))
            d_val = _clean_ordinal(m.group("d"))
            y_val = _clean_year(m.group("y"))
            if m_val and _is_valid_date(y_val, m_val, d_val):
                matches.append((start, end, m.group(0)))
        elif kind == "month_year":
            m_val = _parse_month_name(m.group("m"))
            y_val = int(m.group("y"))
            if m_val and 1900 <= y_val <= 2099:
                matches.append((start, end, m.group(0)))
        elif kind == "iso":
            y_val = int(m.group("y"))
            m_val = int(m.group("m"))
            d_val = int(m.group("d"))
            if _is_valid_date(y_val, m_val, d_val):
                matches.append((start, end, m.group(0)))
        elif kind == "num_4y":
            p1 = int(m.group("p1"))
            p2 = int(m.group("p2"))
            y_val = int(m.group("y"))
            if _is_valid_date(y_val, p1, p2) or _is_valid_date(y_val, p2, p1):
                matches.append((start, end, m.group(0)))
        elif kind == "num_2y":
            p1 = int(m.group("p1"))
            p2 = int(m.group("p2"))
            y_val = _clean_year(m.group("y"))
            if _is_valid_date(y_val, p1, p2) or _is_valid_date(y_val, p2, p1):
                matches.append((start, end, m.group(0)))

    for m in P_MONTH_DAY_YEAR.finditer(text):
        check_match(m, "month_day_year")
    for m in P_DAY_MONTH_YEAR.finditer(text):
        check_match(m, "month_day_year")
    for m in P_DAY_MONTH_YEAR_SPACE.finditer(text):
        check_match(m, "month_day_year")
    for m in P_MONTH_D_Y_HYPHEN.finditer(text):
        check_match(m, "month_day_year")
    for m in P_YEAR_MONTH_DAY.finditer(text):
        check_match(m, "month_day_year")
    for m in P_MONTH_YEAR.finditer(text):
        check_match(m, "month_year")
    for m in P_NUM_ISO.finditer(text):
        check_match(m, "iso")
    for m in P_NUM_4Y.finditer(text):
        check_match(m, "num_4y")
    for m in P_NUM_2Y.finditer(text):
        check_match(m, "num_2y")

    # Sort matches by start ascending, then length descending
    matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))

    # Deduplicate overlapping spans
    non_overlapping: List[Tuple[int, int, str]] = []
    last_end = -1
    for start, end, matched_text in matches:
        if start >= last_end:
            non_overlapping.append((start, end, matched_text))
            last_end = end

    return non_overlapping


def tokenize_dates(
    text: str,
    vault: Vault,
    start_index: int = 1,
    page: int = 1,
) -> Tuple[str, List[str]]:
    """Identify date patterns in text and mask them with <D_k>.

    Args:
        text: Input string.
        vault: In-memory Vault to record date entries.
        start_index: Starting sequential counter for <D_k>.
        page: Page number for provenance.

    Returns:
        Tuple of (masked_text, list_of_assigned_tokens).
    """
    if not text:
        return text, []

    date_spans = _find_date_spans(text)
    if not date_spans:
        return text, []

    assigned_tokens: List[str] = []
    current_idx = start_index
    parts: List[str] = []
    last_pos = 0

    for start, end, raw_str in date_spans:
        token = f"<D_{current_idx}>"
        assigned_tokens.append(token)

        entry = VaultEntry(
            token=token,
            raw=raw_str,
            kind="date",
            page=page,
            bbox=(0.0, 0.0, 0.0, 0.0),
            conf=1.0,
            neg_hint=False,
        )
        vault.add(entry)
        current_idx += 1

        parts.append(text[last_pos:start])
        parts.append(token)
        last_pos = end

    parts.append(text[last_pos:])
    masked_text = "".join(parts)
    return masked_text, assigned_tokens
