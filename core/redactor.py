"""Redactor composer module.

Orchestrates sequential PII redaction:
1. Contact redaction (email, phone, URL, card, barcode) via redactor_contact
2. Address and person redaction via redactor_address
Returns sanitized text and redaction events log.
"""

from typing import Tuple, List, Dict, Any
from core.redactor_contact import redact_contacts
from core.redactor_address import redact_addresses


def redact_text(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Execute complete PII redaction on input text.

    Args:
        text: Input string.

    Returns:
        Tuple of (sanitized_text, list_of_all_redaction_events).
    """
    contacts_redacted, contact_events = redact_contacts(text)
    fully_redacted, address_events = redact_addresses(contacts_redacted)
    all_events = list(contact_events) + list(address_events)
    return fully_redacted, all_events
