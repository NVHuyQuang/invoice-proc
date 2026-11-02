"""Prompt construction and few-shot examples module.

PLAN 4.2:
- PROMPT_VERSION constant.
- System prompt and few-shot examples for structured token-only extraction.
- Few-shots cover:
  1. Standard goods invoice with line items.
  2. Utility bill with charges, previous balance, payments, no qty*price.
  3. Receipt with discounts and negative values (<N_k:neg>).
- Invariant: Prompt text contains ZERO real financial digits (only token patterns).
"""

from config import PROMPT_VERSION


def build_system_prompt() -> str:
    """Construct system prompt instructing LLM to extract token references only."""
    raise NotImplementedError("W1-prompt implementation pending")


def build_user_message(masked_document_text: str) -> str:
    """Format user prompt payload."""
    raise NotImplementedError("W1-prompt implementation pending")
