"""Tokenizer composer module.

Orchestrates sequential masking pipeline:
1. Protect product specifications (tokenizer_specs)
2. Tokenize dates into <D_k> (tokenizer_dates)
3. Tokenize numbers and IDs into <N_k>/<ID_k> (tokenizer_numbers)
4. Restore preserved specifications
Populates the in-memory Vault.
"""

import unicodedata
from typing import Tuple, List, Optional
from core.types import Vault
from core.tokenizer_specs import protect_specs, unprotect_specs
from core.tokenizer_dates import tokenize_dates
from core.tokenizer_numbers import tokenize_numbers


def tokenize_text(
    text: str,
    vault: Optional[Vault] = None,
    page: int = 1,
    date_start_idx: int = 1,
    num_start_idx: int = 1
) -> Tuple[str, Vault]:
    """Tokenize text by protecting specs, masking dates, and masking numbers.

    Args:
        text: Plain input string from document/layout.
        vault: In-memory Vault instance. If None, a new Vault is created.
        page: Page number for entry provenance.
        date_start_idx: Starting counter for date tokens.
        num_start_idx: Starting counter for number tokens.

    Returns:
        Tuple of (masked_text, populated_vault).
    """
    if vault is None:
        vault = Vault()

    if text is None:
        return "", vault

    text = unicodedata.normalize("NFKC", text)

    # Step 1: Protect specifications
    protected_text, specs = protect_specs(text)

    # Step 2: Tokenize dates
    date_masked_text, date_tokens = tokenize_dates(
        protected_text,
        vault=vault,
        start_index=date_start_idx,
        page=page
    )

    # Step 3: Tokenize numbers and IDs
    num_masked_text, num_tokens = tokenize_numbers(
        date_masked_text,
        vault=vault,
        start_index=num_start_idx,
        page=page
    )

    # Step 4: Restore protected specifications
    final_text = unprotect_specs(num_masked_text, specs)

    return final_text, vault
