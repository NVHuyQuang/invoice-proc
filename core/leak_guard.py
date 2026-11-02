"""Leak Guard pre-egress payload validator.

PLAN 3.5: Mandatory pre-send gate for all LLM payloads.
Rejects any payload containing:
- Raw money strings (e.g. \\d+[.,]\\d{2}\\b)
- Consecutive 4+ digits not matching protected specification patterns
- Unmasked email, phone, card number, or URL patterns
- Exceeds MAX_PAYLOAD_CHARS
Crucial invariant: Never logs or prints the offending raw text in logs or exceptions.
"""

from typing import Tuple, List, Optional
from config import MAX_PAYLOAD_CHARS


class LeakGuardViolation(Exception):
    """Raised when an unmasked sensitive token or pattern is detected in egress payload."""

    def __init__(self, rule_name: str, line_no: int) -> None:
        super().__init__(f"LeakGuard violation: rule '{rule_name}' failed at line {line_no}")
        self.rule_name = rule_name
        self.line_no = line_no


def verify_payload(payload: str) -> Tuple[bool, List[str]]:
    """Scan payload before sending to LLM.

    Args:
        payload: Masked document string ready for egress.

    Returns:
        Tuple of (is_valid, list_of_violation_summaries).

    Raises:
        LeakGuardViolation: If payload contains illegal sensitive patterns (when strict=True).
    """
    raise NotImplementedError("W1-leakguard implementation pending")
