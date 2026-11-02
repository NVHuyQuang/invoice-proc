"""Red team adversarial privacy leak attack tests.

Validates that sensitive financial digits, dates, PII, and identifiers
CANNOT leak to LLM prompts, logs, exceptions, tracebacks, or vault repr/str.

Attack Vectors:
1. Unicode digits (Arabic-Indic, Extended Arabic-Indic/Persian, Fullwidth, Devanagari)
2. Digits split by whitespace, tabs, and invisible characters (zero-width space, ZWNJ, ZWJ, NBSP, BOM)
3. PII injected into item names ('Invoice for John Doe, 123 Main St')
4. Obfuscated / non-standard dates
5. Vault security invariants (RAM-only, __repr__, __str__, pickle prohibition, clear lifecycle)
6. Exception & Traceback leak invariants (LeakGuardViolation never leaks raw text)
7. Logging invariants (caplog assertions against raw digit/PII leakage)
8. System prompt & user message invariants (zero raw digits in prompt/few-shots)
9. Leak Guard mandatory pre-send gate attacks (raw money, 4+ digits, card, email, phone, payload size)

Dependencies:
- Implemented in baseline: core.types.Vault, core.vault, core.leak_guard.LeakGuardViolation
- Pending W1 modules: core.tokenizer, core.redactor, core.leak_guard.verify_payload, core.prompt
"""

import logging
import pickle
import re
import traceback
from typing import List, Tuple
import pytest

from config import MAX_PAYLOAD_CHARS, PROMPT_VERSION, SPEC_UNITS
from core.types import Vault, VaultEntry
from core.vault import create_vault, clear_vault
from core.leak_guard import verify_payload, LeakGuardViolation
from core.tokenizer import tokenize_text
from core.tokenizer_numbers import tokenize_numbers
from core.tokenizer_dates import tokenize_dates
from core.redactor import redact_text
from core.redactor_contact import redact_contacts
from core.redactor_address import redact_addresses
from core.prompt import build_system_prompt, build_user_message


def _assert_leak_guard_rejects(payload: str, description: str = "") -> None:
    """Assert verify_payload rejects an adversarial payload.
    
    Accepts either (is_valid=False, violations=[...]) or raising LeakGuardViolation.
    """
    try:
        is_valid, violations = verify_payload(payload)
        assert not is_valid, f"LeakGuard failed to reject payload ({description}): {payload[:60]!r}"
        assert len(violations) > 0, f"LeakGuard returned False but empty violations ({description})"
    except LeakGuardViolation:
        pass  # Raising LeakGuardViolation is also valid per PLAN 3.5


def _assert_leak_guard_accepts(payload: str, description: str = "") -> None:
    """Assert verify_payload accepts a properly sanitized/masked payload."""
    is_valid, violations = verify_payload(payload)
    assert is_valid, f"LeakGuard rejected valid payload ({description}): {violations}"
    assert len(violations) == 0


# =============================================================================
# 1. Unicode Digit Attacks
# =============================================================================

class TestUnicodeDigitAttacks:
    """Adversarial attacks using non-ASCII Unicode numerals to evade \\d regex."""

    def test_arabic_indic_digits_rejected_by_leak_guard(self):
        """Attacker uses Arabic-Indic digits (٠١٢٣٤٥٦٧٨٩) to smuggle money/quantities."""
        # ١٢٣.٤٥ = 123.45, ٥٠٠ = 500
        payload = "Item: Consulting Services, Amount: ١٢٣.٤٥ USD, Qty: ٥٠٠"
        _assert_leak_guard_rejects(payload, "Arabic-Indic digits unmasked in payload")

    def test_arabic_indic_digits_tokenized_or_blocked(self):
        """Tokenizer must either mask Arabic-Indic numerals into <N_k> or reject them."""
        raw_text = "Subtotal: ١٢٣.٤٥ Total: ٥٠٠"
        vault = create_vault()
        masked_text, populated_vault = tokenize_text(raw_text, vault=vault)
        # Raw Arabic-Indic digits must not remain in masked text
        assert "١٢٣.٤٥" not in masked_text
        assert "٥٠٠" not in masked_text
        assert "<N_" in masked_text

    def test_extended_arabic_indic_persian_digits_rejected(self):
        """Attacker uses Eastern Arabic-Indic / Persian digits (۱۲۳۴۵۶۷۸۹۰)."""
        # ۱۲۳.۴۵ = 123.45
        payload = "Invoice Total: ۱۲۳.۴۵"
        _assert_leak_guard_rejects(payload, "Extended Arabic-Indic / Persian digits")

    def test_fullwidth_digits_rejected_by_leak_guard(self):
        """Attacker uses Fullwidth ASCII numerals (０１２３４５６７８９, U+FF10-U+FF19)."""
        payload = "Vendor: Tokyo Wholesale\nGrand Total: １２３．４５\nCard: ４１１１２２２２３３３３４４４４"
        _assert_leak_guard_rejects(payload, "Fullwidth digits unmasked in payload")

    def test_fullwidth_digits_tokenized_by_tokenizer(self):
        """Tokenizer must mask fullwidth numerals into <N_k> tokens."""
        raw_text = "Item Price: １２３．４５, Total: ５０００"
        vault = create_vault()
        masked_text, populated_vault = tokenize_text(raw_text, vault=vault)
        assert "１２３．４５" not in masked_text
        assert "５０００" not in masked_text
        assert "<N_" in masked_text

    def test_devanagari_and_other_scripts_rejected(self):
        """Attacker uses Devanagari numerals (१२३४५६७८९०) to bypass ASCII checks."""
        payload = "Amount: १२३.४५ INR"
        _assert_leak_guard_rejects(payload, "Devanagari digits in egress payload")


# =============================================================================
# 2. Whitespace and Invisible Character Attacks
# =============================================================================

class TestWhitespaceAndInvisibleCharAttacks:
    """Attacks inserting whitespace or zero-width/invisible characters between digits."""

    def test_digits_separated_by_ascii_spaces(self):
        """Attacker spreads digits with ASCII spaces to evade \\d{4,} or money regex."""
        # '1 2 3 . 4 5' or '1  0 0 0 0 . 0 0'
        payload = "Total Due: 1 2 3 . 4 5"
        _assert_leak_guard_rejects(payload, "Spaced digits evasion")

    def test_zero_width_space_evasion(self):
        """Attacker injects Zero-Width Space (U+200B) between digits."""
        # 1\u200b2\u200b3\u200b.\u200b4\u200b5
        obfuscated_money = "1\u200b2\u200b3\u200b.\u200b4\u200b5"
        payload = f"Total: {obfuscated_money}"
        _assert_leak_guard_rejects(payload, "Zero-width space between digits")

    def test_zero_width_joiner_and_non_joiner_evasion(self):
        """Attacker injects ZWNJ (U+200C) and ZWJ (U+200D) to break pattern matching."""
        obfuscated_digits = "9\u200c9\u200d9\u200c.\u200d9\u200c9"
        payload = f"Subtotal: {obfuscated_digits}"
        _assert_leak_guard_rejects(payload, "ZWNJ and ZWJ between digits")

    def test_non_breaking_space_thousands_separator(self):
        """Non-breaking space (U+00A0) used in European currency formats or evasion."""
        # 1\u00a0234,56
        raw_text = "Grand Total: 1\u00a0234,56 EUR"
        _assert_leak_guard_rejects(raw_text, "NBSP formatted money in raw payload")

    def test_thin_space_and_narrow_nbsp_handling(self):
        """Thin space (U+2009) and Narrow NBSP (U+202F) in digit strings."""
        payload = "Amount: 1\u202f234\u2009.\u200956"
        _assert_leak_guard_rejects(payload, "Thin space / narrow NBSP in digits")

    def test_byte_order_mark_and_word_joiner(self):
        """BOM (U+FEFF) and Word Joiner (U+2060) embedded inside numbers."""
        payload = "Price: \ufeff4500\u2060.00"
        _assert_leak_guard_rejects(payload, "BOM and Word Joiner obfuscation")

    def test_tab_and_newline_split_digits(self):
        """Attacker splits a number across tab or newline in a single item line."""
        payload = "Item Total: 12\t34.56"
        _assert_leak_guard_rejects(payload, "Tab separated digits")


# =============================================================================
# 3. PII Injected into Item Names (Description Injection)
# =============================================================================

class TestPIIInjectionInItemNames:
    """Attacks injecting person names, street addresses, contacts into product descriptions."""

    def test_item_name_with_customer_name_and_street_address(self):
        """Item description: 'Invoice for John Doe, 123 Main St'."""
        text = "Item 1: Invoice for Customer: John Doe, 123 Main St, Apt 4B, Springfield, IL 62701"
        sanitized_text, events = redact_text(text)
        # Sensitive address and customer name must be redacted
        assert "123 Main St" not in sanitized_text
        assert "62701" not in sanitized_text
        assert "<ADDR>" in sanitized_text
        # Customer name after 'Customer:' label must be redacted to <PERSON>
        assert "John Doe" not in sanitized_text
        assert "<PERSON>" in sanitized_text

    def test_item_name_with_embedded_email_and_phone(self):
        """Item description containing contact information."""
        text = "Line 1: Special Delivery (contact: jane.doe@enterprise.com / +1-555-867-5309)"
        sanitized_text, events = redact_text(text)
        assert "jane.doe@enterprise.com" not in sanitized_text
        assert "+1-555-867-5309" not in sanitized_text
        assert "<EMAIL>" in sanitized_text
        assert "<PHONE>" in sanitized_text

    def test_item_name_with_credit_card_and_barcode(self):
        """Item description containing card numbers or barcode PII."""
        text = "Deposit paid via Card: 4111-2222-3333-4444 (Barcode: 9780201379624)"
        sanitized_text, events = redact_text(text)
        assert "4111-2222-3333-4444" not in sanitized_text
        assert "9780201379624" not in sanitized_text
        assert "<CARD>" in sanitized_text
        assert "<BARCODE>" in sanitized_text

    def test_leak_guard_rejects_unmasked_pii_in_item_name(self):
        """Egress payload containing unmasked PII in item name must be blocked by Leak Guard."""
        unmasked_payload = "Item: Catering for John Doe, 123 Main St, contact john@test.com"
        _assert_leak_guard_rejects(unmasked_payload, "Unmasked PII in item name")

    def test_product_specifications_not_over_redacted(self):
        """Valid product descriptions (e.g. 'Smith's Butter 750ML') must NOT be over-redacted."""
        text = "Item: Smith's Butter 750ML, St. Louis Ribs 5LB, Tape 12-PACK"
        sanitized_text, events = redact_text(text)
        # 'Smith's Butter' and 'St. Louis' are brand/product names, NOT person labels
        assert "Smith's Butter" in sanitized_text or "Butter" in sanitized_text
        # Specs units (750ML, 5LB, 12-PACK) must remain intact per PLAN 3.4
        assert "750ML" in sanitized_text
        assert "5LB" in sanitized_text
        assert "12-PACK" in sanitized_text


# =============================================================================
# 4. Obfuscated and Unusual Dates
# =============================================================================

class TestObfuscatedAndUnusualDates:
    """Attacks injecting non-standard or international date formats."""

    def test_unicode_and_fullwidth_dates(self):
        """Dates with fullwidth or Arabic-Indic numerals: ２０２６年０８月０１日, ٢٠٢٦/٠٨/٠١."""
        vault = create_vault()
        text = "Invoice Date: ２０２６年０８月０１日"
        masked_text, _ = tokenize_text(text, vault=vault)
        # Raw date numerals must be masked to <D_k> or <N_k>
        assert "２０２６" not in masked_text
        assert "０８" not in masked_text
        assert ("<D_" in masked_text or "<N_" in masked_text)

    def test_spaced_and_exotic_date_formats(self):
        """Dates with mixed separators: 08 / 01 / 2026, 2026. 08. 01."""
        vault = create_vault()
        text = "Date: 08 / 01 / 2026 Due: 2026. 08. 01"
        masked_text, _ = tokenize_text(text, vault=vault)
        assert "2026" not in masked_text
        assert "<D_" in masked_text


# =============================================================================
# 5. Vault Security Invariants
# =============================================================================

class TestVaultSecurityInvariants:
    """Verifies that Vault guarantees zero value leakage in RAM, repr, str, and pickle."""

    def test_vault_repr_never_leaks_raw_values(self):
        """repr(vault) must output redacted placeholder, NEVER raw financial values."""
        vault = create_vault()
        vault.add(VaultEntry(token="<N_1>", raw="$12,345.67", kind="money", page=1, bbox=(0, 0, 10, 10), conf=1.0))
        vault.add(VaultEntry(token="<N_2>", raw="4111-2222-3333-4444", kind="id", page=1, bbox=(0, 0, 10, 10), conf=1.0))
        vault.add(VaultEntry(token="<D_1>", raw="08/01/2026", kind="date", page=1, bbox=(0, 0, 10, 10), conf=1.0))

        v_repr = repr(vault)
        # Must strictly redact values
        assert "$12,345.67" not in v_repr
        assert "4111-2222-3333-4444" not in v_repr
        assert "08/01/2026" not in v_repr
        assert "[VALUES REDACTED]" in v_repr
        assert v_repr == "<Vault count=3 [VALUES REDACTED]>"

    def test_vault_str_never_leaks_raw_values(self):
        """str(vault) must output redacted placeholder, NEVER raw financial values."""
        vault = create_vault()
        vault.add(VaultEntry(token="<N_1>", raw="$999,999.00", kind="money", page=1, bbox=(0, 0, 1, 1), conf=1.0))
        v_str = str(vault)
        assert "$999,999.00" not in v_str
        assert "999,999" not in v_str
        assert v_str == "<Vault count=1 [VALUES REDACTED]>"

    def test_vault_pickle_prohibited(self):
        """Vault must raise TypeError when pickled to prevent disk/serialization leaks."""
        vault = create_vault()
        vault.add(VaultEntry(token="<N_1>", raw="$50.00", kind="money", page=1, bbox=(0, 0, 1, 1), conf=1.0))
        with pytest.raises(TypeError, match="Vault cannot be pickled"):
            pickle.dumps(vault)

    def test_vault_clear_lifecycle_wipes_all_entries(self):
        """vault.clear() and clear_vault(vault) must completely wipe entries from memory."""
        vault = create_vault()
        vault.add(VaultEntry(token="<N_1>", raw="$100.00", kind="money", page=1, bbox=(0, 0, 1, 1), conf=1.0))
        vault.add(VaultEntry(token="<D_1>", raw="2026-08-01", kind="date", page=1, bbox=(0, 0, 1, 1), conf=1.0))
        assert len(vault) == 2

        clear_vault(vault)
        assert len(vault) == 0
        assert "<N_1>" not in vault
        assert vault.get("<N_1>") is None
        assert repr(vault) == "<Vault count=0 [VALUES REDACTED]>"

    def test_vault_iteration_yields_token_names_only(self):
        """Iterating vault yields token strings, not raw entry objects with secrets."""
        vault = create_vault()
        vault.add(VaultEntry(token="<N_1>", raw="$100.00", kind="money", page=1, bbox=(0, 0, 1, 1), conf=1.0))
        vault.add(VaultEntry(token="<D_1>", raw="2026-08-01", kind="date", page=1, bbox=(0, 0, 1, 1), conf=1.0))

        keys = list(vault)
        assert keys == ["<N_1>", "<D_1>"]
        for k in keys:
            assert re.match(r"^<[A-Z]+_\d+>$", k)


# =============================================================================
# 6. Exception and Traceback Leak Invariants
# =============================================================================

class TestExceptionAndTracebackLeakInvariants:
    """Verifies that exceptions and formatted tracebacks NEVER contain raw data."""

    def test_leak_guard_violation_exception_message_clean(self):
        """LeakGuardViolation must only report rule_name and line_no, NEVER the raw violating text."""
        exc = LeakGuardViolation(rule_name="raw_money_detected", line_no=42)
        exc_str = str(exc)
        assert "rule 'raw_money_detected' failed at line 42" in exc_str
        # Ensure constructor doesn't even accept raw text argument
        assert hasattr(exc, "rule_name")
        assert hasattr(exc, "line_no")
        assert not hasattr(exc, "offending_text")

    def test_traceback_formatting_does_not_leak_raw_payload(self):
        """Formatted tracebacks of LeakGuardViolation do not expose raw secrets."""
        sensitive_money = "$12,345,678.99"
        try:
            raise LeakGuardViolation("money_pattern", line_no=12)
        except LeakGuardViolation:
            tb = traceback.format_exc()
            assert sensitive_money not in tb
            assert "LeakGuard violation: rule 'money_pattern' failed at line 12" in tb


# =============================================================================
# 7. Logging Leak Invariants
# =============================================================================

class TestLoggingLeakInvariants:
    """Verifies that logging during processing never emits raw digits or PII."""

    def test_logging_never_emits_raw_digits_or_pii(self, caplog):
        """Run leak guard check on sensitive payload; assert log records contain no secrets."""
        logger = logging.getLogger("core")
        caplog.set_level(logging.DEBUG)

        sensitive_text = "TOTAL: $99,888.77 Card: 4111-2222-3333-4444 Email: secret@client.com"
        _assert_leak_guard_rejects(sensitive_text, "Sensitive log test")

        captured_text = caplog.text
        assert "$99,888.77" not in captured_text
        assert "99,888" not in captured_text
        assert "4111-2222-3333-4444" not in captured_text
        assert "secret@client.com" not in captured_text


# =============================================================================
# 8. System Prompt and User Message Invariants
# =============================================================================

class TestPromptSecurityInvariants:
    """Verifies that system prompt and few-shot examples contain ZERO real financial digits."""

    def test_system_prompt_contains_zero_raw_financial_digits(self):
        """System prompt must only reference tokens (<N_k>, <D_k>), never real amounts."""
        prompt = build_system_prompt()
        assert prompt, "System prompt must not be empty"

        # Search for raw money or decimal numbers like $12.50 or 12.34
        # (Exclude version string like 2026-08-v1 or schema version)
        money_matches = re.findall(r"\$\s*\d+(?:\.\d+)?", prompt)
        assert len(money_matches) == 0, f"System prompt contains raw money patterns: {money_matches}"

        raw_decimal_matches = re.findall(r"\b\d+\.\d{2}\b", prompt)
        assert len(raw_decimal_matches) == 0, f"System prompt contains raw decimals: {raw_decimal_matches}"

        # Must instruct LLM on token references
        assert "<N_" in prompt
        assert "<D_" in prompt

    def test_user_message_wrapper_injects_no_raw_digits(self):
        """build_user_message must not introduce hardcoded numbers or PII."""
        masked_input = "Invoice Header\nDate: <D_1>\nItem 1: Widget, Qty: <N_1>, Total: <N_2>"
        user_msg = build_user_message(masked_input)

        # Template should contain the masked input without introducing raw digits
        assert masked_input in user_msg
        # No unmasked money introduced by template wrapper
        money_matches = re.findall(r"\$\s*\d+", user_msg)
        assert len(money_matches) == 0


# =============================================================================
# 9. Leak Guard Pre-send Gate Attacks
# =============================================================================

class TestLeakGuardPreSendGateAttacks:
    """Rigorous tests attacking the Leak Guard pre-send egress gate."""

    @pytest.mark.parametrize("money_str", [
        "$33.99",
        "33.99",
        "1,234.56",
        "1.234,56",
        "(12.50)",
        "12.50-",
        "12.50 CR",
        "-12.50",
        "33.99T",
        "USD 1500.00",
        "100.00$",
    ])
    def test_leak_guard_rejects_money_patterns(self, money_str: str):
        """All variations of raw money strings must trigger LeakGuard rejection."""
        payload = f"Line Item: Office Supplies, Total: {money_str}"
        _assert_leak_guard_rejects(payload, f"Money pattern: {money_str}")

    @pytest.mark.parametrize("digit_seq", [
        "1234",
        "987654",
        "00001",
        "1234567890",
    ])
    def test_leak_guard_rejects_consecutive_digits_not_in_specs(self, digit_seq: str):
        """Consecutive 4+ digits not matching protected specification patterns must be rejected."""
        payload = f"Description: Serial {digit_seq} in box"
        _assert_leak_guard_rejects(payload, f"Consecutive digits: {digit_seq}")

    @pytest.mark.parametrize("pii_snippet", [
        "john.doe@acme-corp.com",
        "http://intranet.company.local/invoice/123",
        "https://secret.portal.com",
        "+1 (800) 555-0199",
        "0912345678",
        "4111-2222-3333-4444",
        "4111 2222 3333 4444",
        "Visa ending 6411",
    ])
    def test_leak_guard_rejects_raw_pii_and_contacts(self, pii_snippet: str):
        """Unmasked email, URL, phone, and card numbers must be rejected."""
        payload = f"Vendor info: {pii_snippet}"
        _assert_leak_guard_rejects(payload, f"PII snippet: {pii_snippet}")

    def test_leak_guard_rejects_oversized_payload(self):
        """Payload exceeding MAX_PAYLOAD_CHARS must be rejected."""
        oversized = "A" * (MAX_PAYLOAD_CHARS + 1)
        _assert_leak_guard_rejects(oversized, "Oversized payload")

    def test_leak_guard_violation_never_contains_raw_snippet(self):
        """PLAN 3.5 invariant: Never logs or prints the offending raw text in summary/violations."""
        raw_secret = "$98,765.43"
        payload = f"Invoice line total: {raw_secret}"
        try:
            is_valid, violations = verify_payload(payload)
            assert not is_valid
            for v in violations:
                assert raw_secret not in v, f"Violation summary leaked secret: {v}"
                assert "98,765" not in v
        except LeakGuardViolation as exc:
            assert raw_secret not in str(exc)
            assert "98,765" not in str(exc)

    def test_leak_guard_accepts_clean_tokenized_payload(self):
        """Leak Guard must accept payloads containing only valid tokens and protected specs."""
        clean_payload = (
            "INVOICE\n"
            "Vendor: Acme Supply Co.\n"
            "Date: <D_1>\n"
            "Invoice No: <ID_1>\n"
            "Address: <ADDR>\n"
            "Cashier: <PERSON>\n"
            "Contact: <EMAIL> <PHONE>\n"
            "Line 1: Whole Milk 750ML, Qty: <N_1>, Price: <N_2>, Total: <N_3>\n"
            "Line 2: Paper Towels 12-PACK, Qty: <N_4>, Price: <N_5>, Total: <N_6>\n"
            "Discount: <N_7:neg>\n"
            "Subtotal: <N_8>\n"
            "Tax: <N_9>\n"
            "Grand Total: <N_10>\n"
        )
        _assert_leak_guard_accepts(clean_payload, "Fully tokenized and sanitized payload")
