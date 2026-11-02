"""Number and identifier tokenizer module.

PLAN 3.3: Mask all digit-bearing strings into deterministic sequential tokens <N_k> or <ID_k>.
Handles:
- Money formats: $33.99, 33.99, 1,234.56, 1.234,56, (12.50), 12.50-, 12.50 CR, -12.50, 33.99T.
- Quantities: 1.25 lb, 2 @ 3.50, 3 x 4.00.
- Alphanumeric identifiers: INV-2026-0831 -> <ID_k>.
- Preserves negative hints: <N_k:neg> for (12.50), -12.50, 12.50-, 12.50 CR.
- Saves raw text, bounding boxes, confidence, and neg_hint into Vault.
"""

from typing import Tuple, List, Optional
import re
from core.types import Vault, VaultEntry


CURR_SYMS = r"[$€£¥₫₹₽₩]|đ|Đ"
CURR_CODES = r"(?:USD|EUR|GBP|CAD|AUD|VND|JPY|CHF)"
CURR = rf"(?:{CURR_SYMS}|{CURR_CODES})"

TAX_FLAG = r"(?:TX|tx|[TtFfNnEe])"
TAX_SUFFIX = rf"(?:[ \t]*(?:{TAX_FLAG}))\b"
CR_SUFFIX = r"(?:[ \t]*(?:CR|cr|Cr|DR|dr|Dr))\b"

NUM_CORE = r"(?:\d+(?:[.,]\d+)*|[.,]\d+)"

# 1. Existing tokens / placeholders to preserve untouched:
EXISTING_TOKEN = r"<[A-Za-z0-9_:]+>|__[A-Za-z0-9_]+__"

# 2. Parenthesized negative numbers:
# Covers: (12.50), ($12.50), $(12.50), [12.50], [$12.50], (1,234.56), (12.50 CR), (33.99T), etc.
PAREN_NEG = (
    rf"\([ \t]*(?:{CURR}[ \t]*)?[-+]?[ \t]*{NUM_CORE}(?:{TAX_SUFFIX}|{CR_SUFFIX})?[ \t]*(?:{CURR})?[ \t]*\)"
    rf"|\[[ \t]*(?:{CURR}[ \t]*)?[-+]?[ \t]*{NUM_CORE}(?:{TAX_SUFFIX}|{CR_SUFFIX})?[ \t]*(?:{CURR})?[ \t]*\]"
    rf"|{CURR}[ \t]*\([ \t]*[-+]?[ \t]*{NUM_CORE}(?:{TAX_SUFFIX}|{CR_SUFFIX})?[ \t]*\)"
)

# 3. Trailing minus negative:
# Attached: 12.50-, $12.50-, 1,234.56- or spaced: 12.50 -, $12.50 -
TRAILING_MINUS = (
    rf"(?:{CURR}[ \t]*)?{NUM_CORE}(?:{TAX_SUFFIX})?"
    rf"(?:-(?!\w)|[ \t]+-(?![ \t]*(?:{CURR}|\d)))"
)

# 4. Trailing CR/DR negative:
# 12.50 CR, 12.50CR, $12.50 CR, 12.50 DR
TRAILING_CR = rf"(?:{CURR}[ \t]*)?{NUM_CORE}{CR_SUFFIX}"

# 5. Leading minus negative:
# -12.50, -$12.50, $-12.50, -1,234.56, - 12.50, - $12.50
# Must not be preceded by word char or closing paren/bracket
LEADING_MINUS = (
    rf"(?<![\w\)\]])(?:-[ \t]*(?:{CURR}[ \t]*{NUM_CORE}|{NUM_CORE})|{CURR}[ \t]*-[ \t]*{NUM_CORE})(?:{TAX_SUFFIX})?\b"
)

# 6. Numbers with tax flag:
# 33.99T, 33.99TX, 33.99 T
TAX_NUMBER = rf"(?:{CURR}[ \t]*)?{NUM_CORE}{TAX_SUFFIX}"

# 7. Numbers with currency prefix or suffix:
# $33.99, €1.234,56, 33.99 USD, 500,000 VND, 500.000 đ
CURR_NUMBER = rf"(?:{CURR}[ \t]*{NUM_CORE}|{NUM_CORE}[ \t]*(?:{CURR_SYMS}\b|{CURR_CODES}\b|đ\b|Đ\b|₫))"

# 8. Hyphenated numbers (pure digits and hyphens, e.g. phone or pure digit ID):
HYPHEN_NUM = r"\b\d+(?:-\d+)+\b"

# 9. Alphanumeric IDs (contains both letter(s) and digit(s)):
# e.g. INV-2026-0831, PO#12345, ACCT_9876, ORD/2026/01, A1234B, 1234-XYZ
ALPHANUM_ID = r"\b(?=[A-Za-z0-9_/#:.-]*[A-Za-z])(?=[A-Za-z0-9_/#:.-]*\d)[A-Za-z0-9]+(?:[-_/#:.][A-Za-z0-9]+)*\b"

# 10. Plain numbers:
PLAIN_NUMBER = rf"\b{NUM_CORE}\b|{NUM_CORE}"

TOKENIZER_REGEX = re.compile(
    rf"({EXISTING_TOKEN})"
    rf"|({PAREN_NEG})"
    rf"|({TRAILING_MINUS})"
    rf"|({TRAILING_CR})"
    rf"|({LEADING_MINUS})"
    rf"|({TAX_NUMBER})"
    rf"|({CURR_NUMBER})"
    rf"|({HYPHEN_NUM})"
    rf"|({ALPHANUM_ID})"
    rf"|({PLAIN_NUMBER})"
)

CURR_CHECK_RE = re.compile(rf"{CURR_SYMS}|{CURR_CODES}")


def tokenize_numbers(
    text: str,
    vault: Vault,
    start_index: int = 1,
    page: int = 1,
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    conf: float = 1.0,
) -> Tuple[str, List[str]]:
    """Scan text and replace numbers and identifiers with <N_k> or <ID_k>.

    Args:
        text: Input string.
        vault: In-memory Vault to store VaultEntry objects.
        start_index: Starting integer for token counters.
        page: Page number for provenance.
        bbox: Optional bounding box coordinates (x0, y0, x1, y1).
        conf: Optional OCR / text confidence score.

    Returns:
        Tuple of (masked_text, list_of_assigned_tokens).
    """
    if not text:
        return text, []

    assigned_tokens: List[str] = []
    current_k = start_index
    parts: List[str] = []
    last_idx = 0

    for m in TOKENIZER_REGEX.finditer(text):
        parts.append(text[last_idx:m.start()])
        raw = m.group(0)

        # Group 1: Existing token -> preserve as is without re-tokenizing
        if m.group(1):
            parts.append(raw)
            last_idx = m.end()
            continue

        # Check negative groups (2: paren_neg, 3: trailing_minus, 4: trailing_cr, 5: leading_minus)
        is_neg = bool(m.group(2) or m.group(3) or m.group(4) or m.group(5))
        # Check alphanumeric ID group (9)
        is_id = bool(m.group(9))

        # Check if leading minus is actually an infix subtraction operator (e.g. "100.00 - 10.00")
        if m.group(5) and not m.group(2) and not m.group(3) and not m.group(4):
            prev_text = text[:m.start()].rstrip()
            if prev_text and prev_text[-1] in "0123456789)]>":
                minus_match = re.match(r"^-[ \t]*", raw)
                if minus_match:
                    minus_prefix = minus_match.group(0)
                    parts.append(minus_prefix)
                    raw = raw[len(minus_prefix):]
                    is_neg = False

        if is_id:
            token = f"<ID_{current_k}>"
            kind = "id"
            neg_hint = False
        else:
            neg_hint = is_neg
            token = f"<N_{current_k}:neg>" if is_neg else f"<N_{current_k}>"
            # Kind classification
            if CURR_CHECK_RE.search(raw) or bool(m.group(4)):
                kind = "money"
            else:
                kind = "number"

        current_k += 1
        assigned_tokens.append(token)
        entry = VaultEntry(
            token=token,
            raw=raw,
            kind=kind,
            page=page,
            bbox=bbox,
            conf=conf,
            neg_hint=neg_hint,
        )
        vault.add(entry)
        parts.append(token)
        last_idx = m.end()

    parts.append(text[last_idx:])
    return "".join(parts), assigned_tokens

