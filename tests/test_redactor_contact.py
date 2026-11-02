"""Tests for Contact PII Redactor module (PLAN 3.2).

INVARIANTS:
1. Tests must NEVER access real invoice files.
2. Must verify redaction of emails, URLs, US/VN/int'l phones, card numbers, barcodes.
3. Must verify product specifications are NOT masked (e.g. 750ML, 12OZ, 12-PACK).
4. Output replacements must use angle brackets: <EMAIL>, <URL>, <PHONE>, <CARD>, <BARCODE>.
"""

import pytest
from core.redactor_contact import redact_contacts


class TestEmailRedaction:
    """Test suite for email redaction (<EMAIL>)."""

    def test_basic_email(self):
        text = "Contact us at support@pizza4ps.com for inquiries."
        redacted, events = redact_contacts(text)
        assert redacted == "Contact us at <EMAIL> for inquiries."
        assert len(events) == 1
        assert events[0]["type"] == "email"
        assert events[0]["token"] == "<EMAIL>"
        assert events[0]["raw"] == "support@pizza4ps.com"
        assert text[events[0]["start"]:events[0]["end"]] == "support@pizza4ps.com"

    def test_complex_email_with_tag_and_subdomain(self):
        text = "Please reach out to john.doe+billing@sub.finance.company.co.uk immediately."
        redacted, events = redact_contacts(text)
        assert redacted == "Please reach out to <EMAIL> immediately."
        assert len(events) == 1
        assert events[0]["token"] == "<EMAIL>"
        assert events[0]["raw"] == "john.doe+billing@sub.finance.company.co.uk"

    def test_angle_bracketed_email(self):
        text = "Sender: <notifications@system.vn>"
        redacted, events = redact_contacts(text)
        assert redacted == "Sender: <EMAIL>"
        assert len(events) == 1
        assert events[0]["token"] == "<EMAIL>"

    def test_email_with_trailing_punctuation(self):
        text = "For billing questions, email billing@vendor.org."
        redacted, events = redact_contacts(text)
        assert redacted == "For billing questions, email <EMAIL>."
        assert len(events) == 1

    def test_multiple_emails(self):
        text = "Primary: contact@a.com, Secondary: alt@b.vn"
        redacted, events = redact_contacts(text)
        assert redacted == "Primary: <EMAIL>, Secondary: <EMAIL>"
        assert len(events) == 2


class TestUrlRedaction:
    """Test suite for URL and domain redaction (<URL>)."""

    def test_https_and_http_urls(self):
        text = "Visit https://pizza4ps.com/menu or http://order.store.com:8080/checkout?id=123."
        redacted, events = redact_contacts(text)
        assert redacted == "Visit <URL> or <URL>."
        assert len(events) == 2
        assert all(e["type"] == "url" for e in events)
        assert all(e["token"] == "<URL>" for e in events)

    def test_ftp_url(self):
        text = "Download report from ftp://files.vendor.com/invoices/2026/08."
        redacted, events = redact_contacts(text)
        assert redacted == "Download report from <URL>."
        assert len(events) == 1

    def test_www_url(self):
        text = "Order online at www.pizza4ps.vn/delivery today!"
        redacted, events = redact_contacts(text)
        assert redacted == "Order online at <URL> today!"
        assert len(events) == 1

    def test_bare_domain(self):
        text = "Check domain pizza4ps.com or sub.service.vn for status."
        redacted, events = redact_contacts(text)
        assert redacted == "Check domain <URL> or <URL> for status."
        assert len(events) == 2

    def test_url_in_parentheses(self):
        text = "Official website (https://www.company.com/portal) is active."
        redacted, events = redact_contacts(text)
        assert redacted == "Official website (<URL>) is active."
        assert len(events) == 1


class TestUsPhoneRedaction:
    """Test suite for US phone numbers (<PHONE>)."""

    @pytest.mark.parametrize("phone_sample", [
        "(123) 456-7890",
        "123-456-7890",
        "123.456.7890",
        "123 456 7890",
        "+1 (123) 456-7890",
        "+1-123-456-7890",
        "+1.123.456.7890",
        "+1 123 456 7890",
        "1-800-555-0199",
        "(800) 555-0199",
        "800-555-0199",
        "(123) 456-7890 ext. 1234",
        "123-456-7890 x42",
    ])
    def test_us_phone_formats(self, phone_sample):
        text = f"Call our hotline at {phone_sample} for help."
        redacted, events = redact_contacts(text)
        assert redacted == "Call our hotline at <PHONE> for help."
        assert len(events) == 1
        assert events[0]["type"] == "phone"
        assert events[0]["token"] == "<PHONE>"


class TestVnPhoneRedaction:
    """Test suite for Vietnamese phone numbers (<PHONE>)."""

    @pytest.mark.parametrize("phone_sample", [
        # Mobile formats (03x, 05x, 07x, 08x, 09x)
        "0901234567",
        "090 123 4567",
        "090-123-4567",
        "090.123.4567",
        "0901 234 567",
        "0908 12 34 56",
        "038 999 8888",
        # Landlines (024 Hanoi, 028 HCMC, 0236 Da Nang)
        "028 3823 9999",
        "028-3823-9999",
        "028.3823.9999",
        "02838239999",
        "(028) 3823 9999",
        "024 3823 9999",
        "(024) 3823 9999",
        "0236 382 9999",
        # Country code (+84, (+84), 0084, (84), 84)
        "+84 90 123 4567",
        "+84-90-123-4567",
        "+84901234567",
        "(+84) 901234567",
        "(+84) 28 3823 9999",
        "0084 90 123 4567",
        "(84) 901234567",
        # Hotlines / Toll-free
        "1900 6066",
        "1900-6066",
        "1900.6066",
        "19006066",
        "1800 1234",
        "1800-1234",
        "18001234",
    ])
    def test_vn_phone_formats(self, phone_sample):
        text = f"Liên hệ: {phone_sample} để được hỗ trợ."
        redacted, events = redact_contacts(text)
        assert redacted == "Liên hệ: <PHONE> để được hỗ trợ."
        assert len(events) == 1
        assert events[0]["type"] == "phone"
        assert events[0]["token"] == "<PHONE>"


class TestInternationalAndLabeledPhone:
    """Test suite for international and labeled phones (<PHONE>)."""

    @pytest.mark.parametrize("phone_sample", [
        "+44 20 7946 0958",
        "+81 3 1234 5678",
        "+33 1 42 68 55 55",
        "+65 6789 0123",
        "+49 30 1234567",
    ])
    def test_international_phone_formats(self, phone_sample):
        text = f"International office: {phone_sample}"
        redacted, events = redact_contacts(text)
        assert redacted == "International office: <PHONE>"
        assert len(events) == 1
        assert events[0]["token"] == "<PHONE>"

    @pytest.mark.parametrize("label, phone", [
        ("Tel:", "(028) 3823 9999"),
        ("Phone:", "555-0199"),
        ("Hotline:", "1900 6066"),
        ("SĐT:", "0901234567"),
        ("Điện thoại:", "028 3823 9999"),
        ("Fax:", "+1-555-555-5555"),
    ])
    def test_labeled_phone_numbers(self, label, phone):
        text = f"{label} {phone}"
        redacted, events = redact_contacts(text)
        assert redacted == f"{label} <PHONE>"
        assert len(events) == 1
        assert events[0]["token"] == "<PHONE>"


class TestCardRedaction:
    """Test suite for card numbers (<CARD>)."""

    @pytest.mark.parametrize("card_sample, expected_replacement", [
        ("**** 1234", "<CARD>"),
        ("****1234", "<CARD>"),
        ("xxxx1234", "<CARD>"),
        ("XXXX1234", "<CARD>"),
        ("Visa ending 6411", "<CARD>"),
        ("Visa ending in 6411", "<CARD>"),
        ("Mastercard ending 1234", "<CARD>"),
        ("MasterCard ending in 5678", "<CARD>"),
        ("MC ending 1234", "<CARD>"),
        ("Card ending 1234", "<CARD>"),
        ("ending 6411", "<CARD>"),
        ("ending in 6411", "<CARD>"),
        ("AMEX ending: 9876", "<CARD>"),
        ("**** **** **** 1234", "<CARD>"),
        ("****-****-****-1234", "<CARD>"),
        ("xxxx xxxx xxxx 1234", "<CARD>"),
        ("xxxx-xxxx-xxxx-1234", "<CARD>"),
        ("XXXX-XXXX-XXXX-1234", "<CARD>"),
        ("************1234", "<CARD>"),
        ("xxxxxxxxxxxx1234", "<CARD>"),
        ("4111-2222-3333-4444", "<CARD>"),
        ("4111 2222 3333 4444", "<CARD>"),
        ("4111 **** **** 1234", "<CARD>"),
    ])
    def test_card_formats(self, card_sample, expected_replacement):
        text = f"Payment method: {card_sample}"
        redacted, events = redact_contacts(text)
        assert redacted == f"Payment method: {expected_replacement}"
        assert len(events) == 1
        assert events[0]["type"] == "card"
        assert events[0]["token"] == "<CARD>"


class TestBarcodeRedaction:
    """Test suite for barcodes (<BARCODE>)."""

    def test_standalone_numeric_barcodes(self):
        # 12 digits (UPC-A), 13 digits (EAN-13), 14 digits (ITF-14)
        for barcode in ["012345678905", "8938505021234", "10012345678902"]:
            text = f"Item tag: {barcode}"
            redacted, events = redact_contacts(text)
            assert redacted == "Item tag: <BARCODE>"
            assert len(events) == 1
            assert events[0]["type"] == "barcode"
            assert events[0]["token"] == "<BARCODE>"

    @pytest.mark.parametrize("prefix, barcode", [
        ("Barcode:", "8938505021234"),
        ("Barcode:", "ABC-12345678"),
        ("UPC:", "012345678905"),
        ("EAN:", "8938505021234"),
        ("JAN:", "4901234567894"),
        ("Mã vạch:", "8935001700018"),
    ])
    def test_labeled_barcodes(self, prefix, barcode):
        text = f"{prefix} {barcode}"
        redacted, events = redact_contacts(text)
        assert redacted == f"{prefix} <BARCODE>"
        assert len(events) == 1
        assert events[0]["token"] == "<BARCODE>"


class TestProductSpecsPreservation:
    """Critical test suite: Product specifications must NEVER be redacted (PLAN 3.4)."""

    @pytest.mark.parametrize("spec", [
        # Attached units
        "750ML", "5LB", "12OZ", "500G", "10KG", "2L", "250ML", "1.5L",
        # Paper sizes
        "A4", "A3", "B5",
        # Multiplied forms
        "6X32 OZ", "6x32OZ", "12x1 L", "24/12 OZ", "24 / 12 OZ",
        # Hyphenated package forms
        "12-PACK", "6-CT", "10-INCH", "24-PK", "12-CAN", "6-BTL", "4-BOX", "2-PAIR", "3-SET",
        # Distinct unit quantities
        "2 lb", "3 ea", "1 case",
    ])
    def test_specs_are_not_redacted(self, spec):
        text = f"Order line: 2x Item description {spec} at regular price"
        redacted, events = redact_contacts(text)
        assert redacted == text
        assert len(events) == 0

    def test_specs_coexisting_with_contacts(self):
        text = "Item 1: Heineken Beer 12-PACK 750ML - Support: hotline 1900 6066 or visit https://beer.vn"
        redacted, events = redact_contacts(text)
        assert redacted == "Item 1: Heineken Beer 12-PACK 750ML - Support: hotline <PHONE> or visit <URL>"
        assert len(events) == 2
        tokens = [e["token"] for e in events]
        assert "<PHONE>" in tokens
        assert "<URL>" in tokens
        assert "12-PACK" in redacted
        assert "750ML" in redacted


class TestPreserveDatesAndNumbers:
    """Test that dates, monetary values, and invoice identifiers are not altered."""

    def test_dates_untouched(self):
        for date_str in ["2026-08-31", "08/01/2026", "31.08.2026", "01-Aug-2026", "Aug 01, 2026"]:
            text = f"Invoice Date: {date_str} Due Date: {date_str}"
            redacted, events = redact_contacts(text)
            assert redacted == text
            assert len(events) == 0

    def test_money_and_invoice_ids_untouched(self):
        text = "INV-2026-0831 PO-998877 Subtotal: $1,234.56 Tax: 10.00 Total: $1,244.56"
        redacted, events = redact_contacts(text)
        assert redacted == text
        assert len(events) == 0


class TestMetadataAndEdgeCases:
    """Test metadata accuracy, empty strings, and idempotency."""

    def test_empty_string(self):
        redacted, events = redact_contacts("")
        assert redacted == ""
        assert events == []

    def test_whitespace_string(self):
        redacted, events = redact_contacts("   \n\t  ")
        assert redacted == "   \n\t  "
        assert events == []

    def test_already_tokenized_tags_protected(self):
        text = "Line with <EMAIL> and <PHONE> and <ADDR> and <N_1>"
        redacted, events = redact_contacts(text)
        assert redacted == text
        assert events == []

    def test_metadata_character_offsets(self):
        text = "Contact john@pizza4ps.com or call 090 123 4567. Website: https://pizza4ps.com. Item: Wine 750ML 12-PACK, Barcode: 8938505021234, Paid by Visa ending 6411."
        redacted, events = redact_contacts(text)
        assert len(events) == 5
        for event in events:
            # Verify exact character slice
            assert text[event["start"]:event["end"]] == event["raw"]
