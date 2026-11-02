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
from core.types import Vault


def tokenize_numbers(
    text: str,
    vault: Vault,
    start_index: int = 1,
    page: int = 1
) -> Tuple[str, List[str]]:
    """Scan text and replace numbers and identifiers with <N_k> or <ID_k>.

    Args:
        text: Input string.
        vault: In-memory Vault to store VaultEntry objects.
        start_index: Starting integer for token counters.
        page: Page number for provenance.

    Returns:
        Tuple of (masked_text, list_of_assigned_tokens).
    """
    raise NotImplementedError("W1-tok-numbers implementation pending")
