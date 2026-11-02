"""Date tokenizer module.

PLAN 3.3: Recognize and mask dates into sequential <D_k> tokens.
Formats: MM/DD/YYYY, DD.MM.YYYY, Aug 01, 2026, 2026-08-01, 01-Aug-26, etc.
Stores raw date strings in the Vault.
Does NOT ingest monetary amounts or quantities that resemble dates.
"""

from typing import Tuple, List
from core.types import Vault


def tokenize_dates(
    text: str,
    vault: Vault,
    start_index: int = 1,
    page: int = 1
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
    raise NotImplementedError("W1-tok-dates implementation pending")
