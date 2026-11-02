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

from typing import Tuple, List, Optional
from core.types import Vault, Document
from models.schema import LLMInvoice, CanonicalInvoice


class TokenVerificationError(Exception):
    """Raised when token references violate integrity or security rules."""
    pass


def verify_llm_tokens(llm_invoice: LLMInvoice, vault: Vault) -> Tuple[bool, List[str]]:
    """Verify integrity, existence, uniqueness, and coverage of token references.

    Args:
        llm_invoice: LLM output with token refs.
        vault: In-memory document Vault.

    Returns:
        Tuple of (is_valid, list_of_issues).
    """
    raise NotImplementedError("W1-rehydrator implementation pending")


def rehydrate_invoice(
    llm_invoice: LLMInvoice,
    vault: Vault,
    source_file: str,
    source_sha256: str
) -> CanonicalInvoice:
    """Resolve token references into Decimal values and CanonicalInvoice data structure.

    Args:
        llm_invoice: Validated LLM output.
        vault: In-memory document Vault.
        source_file: File path.
        source_sha256: File SHA-256 hash.

    Returns:
        CanonicalInvoice with real numeric Decimals and Provenance.
    """
    raise NotImplementedError("W1-rehydrator implementation pending")
