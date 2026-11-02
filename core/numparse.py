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
from typing import Optional, Tuple


class AmbiguousNumberError(ValueError):
    """Raised when a number's locale cannot be determined unambiguously."""
    pass


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
    raise NotImplementedError("W1-numparse implementation pending")


def detect_document_locale(texts: list[str]) -> str:
    """Infer dominant numeric locale from a list of number strings in a document.

    Args:
        texts: List of number strings from document.

    Returns:
        "US" or "EU_VN".
    """
    raise NotImplementedError("W1-numparse implementation pending")
