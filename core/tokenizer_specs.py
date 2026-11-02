"""Product specifications tokenizer / protection module.

PLAN 3.4: Preserve product specs without masking.
Strict matching against SPEC_UNITS from config.py:
Positive examples (kept as-is): 750ML, 5LB, 12OZ, A4, 500G, 6X32 OZ, 12x1 L, 12-PACK, 6-CT, 10-INCH.
Negative examples (MUST NOT be preserved as specs, MUST be masked by numbers/quantity): 2 lb, 3 ea, 1 case.
"""

from typing import Tuple, List, Dict, Any


def protect_specs(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Identify product specification patterns and mark/protect them from number tokenization.

    Args:
        text: Input string.

    Returns:
        Tuple of (protected_text, list_of_detected_specs).
    """
    raise NotImplementedError("W1-tok-specs implementation pending")


def unprotect_specs(text: str, specs: List[Dict[str, Any]]) -> str:
    """Restore preserved specification text if placeholders were used during tokenization.

    Args:
        text: Tokenized text with specification placeholders.
        specs: List of preserved specifications.

    Returns:
        Final string with preserved specs restored.
    """
    raise NotImplementedError("W1-tok-specs implementation pending")
