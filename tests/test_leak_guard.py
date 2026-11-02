"""Unit and attack tests for core/leak_guard.py.

Verifies:
1. Pre-egress gate blocks all sensitive leaks:
   - Raw money strings in various formats
   - Consecutive 4+ digits (excluding valid specifications under PLAN 3.4)
   - Emails, phone numbers, credit card numbers, URLs
   - Payload size exceeding MAX_PAYLOAD_CHARS
2. Valid tokens (<N_k>, <D_k>, <ID_k>, <ADDR>, etc.) and valid specs (750ML, 6X32 OZ, 12-PACK) are allowed
3. CRUCIAL INVARIANT: No sensitive values are ever exposed in violations, exceptions, or logs
4. Multi-line location tracking and strict/non-strict behavior
"""

import logging
import pytest
from config import MAX_PAYLOAD_CHARS
from core.leak_guard import (
    verify_payload,
    LeakGuardViolation,
    RULE_MAX_PAYLOAD,
    RULE_RAW_MONEY,
    RULE_CONSECUTIVE_DIGITS,
    RULE_EMAIL,
    RULE_PHONE,
    RULE_CARD,
    RULE_URL,
)


class TestLeakGuardValidPayloads:
    """Tests for payloads that must pass verification."""

    def test_clean_masked_payload_passes(self):
        payload = (
            "Invoice <ID_1> Date <D_1>\n"
            "Vendor: Acme Supplies\n"
            "Line 1: Widget A <N_1> <N_2> <N_3>\n"
            "Line 2: Widget B <N_4> <N_5> <N_6>\n"
            "Subtotal: <N_7>\n"
            "Tax: <N_8>\n"
            "Total: <N_9>\n"
        )
        is_valid, violations = verify_payload(payload)
        assert is_valid is True
        assert violations == []

    def test_all_standard_redactor_tokens_pass(self):
        payload = (
            "Address: <ADDR>\n"
            "Customer Phone: <PHONE>\n"
            "Contact Email: <EMAIL>\n"
            "Website: <URL>\n"
            "Payment Card: <CARD>\n"
            "Cashier: <PERSON>\n"
            "Barcode: <BARCODE>\n"
        )
        is_valid, violations = verify_payload(payload)
        assert is_valid is True
        assert violations == []

    def test_tokens_with_modifiers_and_large_indices_pass(self):
        payload = (
            "Discount: <N_100:neg>\n"
            "Tax adjustment: <N_205:tax>\n"
            "Large index token: <N_9999>\n"
            "Large date token: <D_2026>\n"
            "Large ID token: <ID_50000>\n"
        )
        is_valid, violations = verify_payload(payload)
        assert is_valid is True
        assert violations == []

    @pytest.mark.parametrize("spec", [
        "750ML", "5LB", "12OZ", "500G", "1000ML", "2500KG",
        "A4", "A3",
        "12-PACK", "6-CT", "10-INCH", "1000-CT", "24-PK",
        "6X32 OZ", "12x1 L", "24/12 OZ", "4x1000 ML", "2x500 G"
    ])
    def test_valid_specifications_pass(self, spec):
        payload = f"Item specification: {spec} quantity <N_1>"
        is_valid, violations = verify_payload(payload)
        assert is_valid is True, f"Valid spec '{spec}' was incorrectly rejected: {violations}"
        assert violations == []

    def test_benign_text_with_single_digits_passes(self):
        payload = (
            "Page 1 of 2\n"
            "Table 1: Goods Delivered\n"
            "Item 1: Milk <N_1>\n"
            "Item 2: Bread <N_2>\n"
            "Version 1.0 release notes\n"
        )
        is_valid, violations = verify_payload(payload)
        assert is_valid is True
        assert violations == []

    def test_empty_string_passes(self):
        is_valid, violations = verify_payload("")
        assert is_valid is True
        assert violations == []


class TestLeakGuardMoneyInjection:
    """Tests injecting numbers in money formats across many styles."""

    @pytest.mark.parametrize("money_str", [
        "$33.99",
        "33.99",
        "1,234.56",
        "1.234,56",
        "(12.50)",
        "12.50-",
        "12.50 CR",
        "12.50 DR",
        "-12.50",
        "33.99T",
        "12.50F",
        "1.25 lb",
        "2 @ 3.50",
        "3 x 4.00",
        "$50",
        "50.00$",
        "100 EUR",
        "€ 25.50",
        "50,000 VND",
        "50.000đ",
        "1,000,000",
        "10,000",
        "0.99",
        "12,50",
    ])
    def test_detects_money_patterns(self, money_str):
        payload = f"Description: Fresh Produce, Total: {money_str}"
        is_valid, violations = verify_payload(payload)
        assert is_valid is False, f"Failed to reject money leak: {money_str}"
        assert any(RULE_RAW_MONEY in v for v in violations)


class TestLeakGuardConsecutiveDigits:
    """Tests injecting >= 4 consecutive digits."""

    @pytest.mark.parametrize("digit_str", [
        "1234",
        "12345",
        "999999",
        "2026",
        "INV-2026-0831",
    ])
    def test_detects_consecutive_digits(self, digit_str):
        payload = f"Order reference: {digit_str}"
        is_valid, violations = verify_payload(payload)
        assert is_valid is False, f"Failed to reject consecutive digits: {digit_str}"
        assert any(RULE_CONSECUTIVE_DIGITS in v for v in violations)

    @pytest.mark.parametrize("invalid_spec", [
        "1000 lb",   # space-separated: quantity + unit, not a spec
        "1000 ea",   # space-separated: quantity + unit, not a spec
        "1000 case", # space-separated: quantity + unit, not a spec
        "2000 items",# items not in SPEC_UNITS
        "A4000",     # not a paper size (4 digits)
    ])
    def test_unprotected_invalid_specs_with_4_digits_fail(self, invalid_spec):
        payload = f"Line Item: {invalid_spec}"
        is_valid, violations = verify_payload(payload)
        assert is_valid is False, f"Should reject invalid spec: {invalid_spec}"
        assert any(RULE_CONSECUTIVE_DIGITS in v for v in violations)


class TestLeakGuardPII:
    """Tests detecting email, phone, card, and URL patterns."""

    @pytest.mark.parametrize("email", [
        "user@example.com",
        "john.doe+tax@billing.company.org",
        "contact@invoice-service.vn",
        "accounts_payable@sub.domain.co.uk",
    ])
    def test_detects_email_patterns(self, email):
        payload = f"Billing inquiries to: {email}"
        is_valid, violations = verify_payload(payload)
        assert is_valid is False
        assert any(RULE_EMAIL in v for v in violations)

    @pytest.mark.parametrize("phone", [
        "(555) 123-4567",
        "555-123-4567",
        "555.123.4567",
        "555 123 4567",
        "+1 (555) 123-4567",
        "+1-800-555-0199",
        "0901234567",
        "090-123-4567",
        "+84 901 234 567",
        "028 3822 1234",
        "+44 20 7946 0958",
        "Tel: 123-456-7890",
        "Phone: (123) 456-7890",
    ])
    def test_detects_phone_patterns(self, phone):
        payload = f"For support call {phone} immediately"
        is_valid, violations = verify_payload(payload)
        assert is_valid is False
        assert any(RULE_PHONE in v for v in violations)

    @pytest.mark.parametrize("card", [
        "4111 2222 3333 4444",
        "4111-2222-3333-4444",
        "4111222233334444",
        "3782 822463 10005",
        "**** 1234",
        "****1234",
        "xxxx 1234",
        "XXXX-1234",
        "Visa ending 6411",
        "Mastercard ending in 1234",
        "Amex ending 9012",
        "Card ending 4321",
    ])
    def test_detects_card_patterns(self, card):
        payload = f"Paid with credit card: {card}"
        is_valid, violations = verify_payload(payload)
        assert is_valid is False
        assert any(RULE_CARD in v for v in violations)

    @pytest.mark.parametrize("url", [
        "https://portal.vendor.com/invoice/pay",
        "http://invoicing.org/doc?id=123",
        "www.restaurant-supply.com",
        "billing.portal.vn",
        "company.com/receipts",
    ])
    def test_detects_url_patterns(self, url):
        payload = f"Pay online at {url}"
        is_valid, violations = verify_payload(payload)
        assert is_valid is False
        assert any(RULE_URL in v for v in violations)


class TestLeakGuardPayloadSize:
    """Tests payload size boundary."""

    def test_payload_exceeding_max_chars_is_rejected(self):
        oversized = "a" * (MAX_PAYLOAD_CHARS + 1)
        is_valid, violations = verify_payload(oversized)
        assert is_valid is False
        assert any(RULE_MAX_PAYLOAD in v for v in violations)

    def test_payload_within_max_chars_passes(self):
        within_limit = "word " * 1000
        assert len(within_limit) <= MAX_PAYLOAD_CHARS
        is_valid, violations = verify_payload(within_limit)
        assert is_valid is True
        assert violations == []


class TestLeakGuardPrivacyInvariant:
    """HARD INVARIANT: No raw sensitive strings or numbers are leaked in logs, exceptions, or violation strings."""

    @pytest.mark.parametrize("secret", [
        "$99999.99",
        "secret_user@supersecret.org",
        "0987654321",
        "4111999988887777",
        "https://secret-vault.internal.net/keys",
    ])
    def test_violation_strings_do_not_contain_secret(self, secret):
        payload = f"Vendor: Secret Corp\nSecret data: {secret}\nEnd"
        is_valid, violations = verify_payload(payload)
        assert is_valid is False

        # Invariant check: Secret MUST NOT appear in any violation message
        for violation in violations:
            assert secret not in violation, f"Secret leaked in violation string: {violation}"

    @pytest.mark.parametrize("secret", [
        "$8888.88",
        "leak_test@hidden.com",
        "Visa ending 9999",
        "1234567890",
    ])
    def test_exception_does_not_contain_secret(self, secret):
        payload = f"Line 1: {secret}"
        with pytest.raises(LeakGuardViolation) as exc_info:
            verify_payload(payload, strict=True)

        exc_msg = str(exc_info.value)
        exc_repr = repr(exc_info.value)

        # Invariant check: Secret MUST NOT appear in exception message or repr
        assert secret not in exc_msg, f"Secret leaked in exception str: {exc_msg}"
        assert secret not in exc_repr, f"Secret leaked in exception repr: {exc_repr}"
        assert exc_info.value.rule_name is not None
        assert exc_info.value.line_no == 1

    def test_logs_do_not_contain_secret(self, caplog):
        caplog.set_level(logging.DEBUG)
        secret = "$7777.77"
        payload = f"Line 1: Item\nLine 2: {secret}\nLine 3: End"

        is_valid, violations = verify_payload(payload)
        assert is_valid is False

        # Invariant check: Secret MUST NOT appear anywhere in log records
        for record in caplog.records:
            assert secret not in record.getMessage(), f"Secret leaked in log message: {record.getMessage()}"


class TestLeakGuardLineTrackingAndStrict:
    """Tests line number accuracy and strict/non-strict behavior."""

    def test_accurate_line_numbers_in_multiline_payload(self):
        payload = (
            "Line 1: Valid <N_1>\n"
            "Line 2: Valid <D_1>\n"
            "Line 3: Leaked email user@test.com\n"
            "Line 4: Valid <ID_1>\n"
            "Line 5: Leaked money $45.00\n"
        )
        is_valid, violations = verify_payload(payload)
        assert is_valid is False
        assert len(violations) == 2
        assert any("line 3" in v.lower() for v in violations)
        assert any("line 5" in v.lower() for v in violations)

    def test_strict_mode_raises_on_first_violation(self):
        payload = (
            "Line 1: Valid text\n"
            "Line 2: Leaked money 99.99\n"
            "Line 3: Leaked email test@abc.com\n"
        )
        with pytest.raises(LeakGuardViolation) as exc_info:
            verify_payload(payload, strict=True)

        assert exc_info.value.rule_name == RULE_RAW_MONEY
        assert exc_info.value.line_no == 2

    def test_strict_mode_does_not_raise_when_valid(self):
        payload = "Valid payload <N_1> <D_1>"
        is_valid, violations = verify_payload(payload, strict=True)
        assert is_valid is True
        assert violations == []

    def test_invalid_type_raises_type_error(self):
        with pytest.raises(TypeError):
            verify_payload(None)  # type: ignore

        with pytest.raises(TypeError):
            verify_payload(12345)  # type: ignore


class TestLeakGuardAdversarialEvasion:
    """Tests adversarial attempts to bypass leak guard."""

    def test_fullwidth_digits_are_caught(self):
        # １２３４ is fullwidth 1234
        payload = "Total １２３４"
        is_valid, violations = verify_payload(payload)
        assert is_valid is False
        assert any(RULE_CONSECUTIVE_DIGITS in v for v in violations)

    def test_zero_width_space_separated_digits_are_caught(self):
        # 1\u200b2\u200b3\u200b4 -> zero-width space injected between digits
        payload = "Order 1\u200b2\u200b3\u200b4 confirmed"
        is_valid, violations = verify_payload(payload)
        assert is_valid is False
        assert any(RULE_CONSECUTIVE_DIGITS in v for v in violations)

    def test_fake_token_with_embedded_money_is_caught(self):
        # Fake token attempting to smuggle 33.99
        payload = "Item <N_33.99>"
        is_valid, violations = verify_payload(payload)
        assert is_valid is False
        assert any(RULE_RAW_MONEY in v for v in violations)

    def test_fake_token_with_embedded_phone_is_caught(self):
        # Fake token attempting to smuggle phone
        payload = "Support <N_555-123-4567>"
        is_valid, violations = verify_payload(payload)
        assert is_valid is False
        assert any(RULE_PHONE in v for v in violations)
