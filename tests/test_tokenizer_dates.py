"""Unit tests for core.tokenizer_dates module.

Tests cover:
- Valid date formats (ISO, US, European, Alphanumeric, Ordinals, 2-digit & 4-digit years)
- Invalid calendar dates (out of range months/days, nonexistent leap days)
- Negative tests: Money amounts, quantities, specs, phone numbers, IPs, IDs MUST NOT be swallowed
- Vault entry validation (kind='date', token, raw, page, bbox, conf, neg_hint)
- Sequential deterministic indexing (start_index, multiple dates, repeated dates)
- Realistic mixed document snippets
"""

import pytest
from core.types import Vault
from core.tokenizer_dates import tokenize_dates


# ---------------------------------------------------------------------------
# 1. Empty and trivial text tests
# ---------------------------------------------------------------------------

def test_empty_text():
    vault = Vault()
    masked, tokens = tokenize_dates("", vault)
    assert masked == ""
    assert tokens == []
    assert len(vault) == 0


def test_no_dates_in_text():
    vault = Vault()
    text = "Whole Milk 1 Gallon Price 3.99 Subtotal 3.99"
    masked, tokens = tokenize_dates(text, vault)
    assert masked == text
    assert tokens == []
    assert len(vault) == 0


# ---------------------------------------------------------------------------
# 2. Valid numeric date formats (4-digit year)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw_date", [
    "08/01/2026",
    "8/1/2026",
    "12/31/2025",
    "01/08/2026",
    "31/12/2025",
    "01.08.2026",
    "1.8.2026",
    "31.12.2025",
    "08.01.2026",
    "2026-08-01",
    "2026-8-1",
    "2026/08/01",
    "2026.08.01",
    "01-08-2026",
    "08-01-2026",
    "31-12-2025",
    "2024-02-29",  # Valid leap year
])
def test_valid_numeric_dates_4y(raw_date):
    vault = Vault()
    text = f"Invoice Date: {raw_date}"
    masked, tokens = tokenize_dates(text, vault)
    assert masked == "Invoice Date: <D_1>"
    assert tokens == ["<D_1>"]
    assert len(vault) == 1
    entry = vault.get("<D_1>")
    assert entry is not None
    assert entry.raw == raw_date
    assert entry.kind == "date"
    assert entry.page == 1
    assert entry.neg_hint is False


# ---------------------------------------------------------------------------
# 3. Valid numeric date formats (2-digit year)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw_date", [
    "08/01/26",
    "8/1/26",
    "01/08/26",
    "31/12/25",
    "01.08.26",
    "31.12.25",
    "01-08-26",
    "08-01-26",
    "31-12-25",
])
def test_valid_numeric_dates_2y(raw_date):
    vault = Vault()
    text = f"Date: {raw_date}"
    masked, tokens = tokenize_dates(text, vault)
    assert masked == "Date: <D_1>"
    assert tokens == ["<D_1>"]
    assert len(vault) == 1
    entry = vault.get("<D_1>")
    assert entry is not None
    assert entry.raw == raw_date
    assert entry.kind == "date"


# ---------------------------------------------------------------------------
# 4. Valid alphanumeric month formats
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw_date", [
    "Aug 01, 2026",
    "August 1, 2026",
    "Aug 1, 2026",
    "August 01, 2026",
    "Aug. 01, 2026",
    "Sept. 15, 2025",
    "Sep. 15, 2025",
    "Aug 01 2026",
    "August 1 2026",
    "Aug 1st, 2026",
    "August 2nd, 2026",
    "3rd March 2024",
    "July 4th, 2026",
    "01 Aug 2026",
    "1 August 2026",
    "1st August 2026",
    "01-Aug-2026",
    "01-Aug-26",
    "1-Aug-26",
    "1-August-2026",
    "01.Aug.2026",
    "01.Aug.26",
    "01-Aug.-2026",
    "Aug-01-2026",
    "Aug-01-26",
    "2026-Aug-01",
    "2026-August-01",
    "Aug 01, 26",
    "Aug 01, '26",
    "August 1, 26",
    "August 2026",
    "Aug 2026",
    "January 2025",
])
def test_valid_alphanumeric_dates(raw_date):
    vault = Vault()
    text = f"Date: {raw_date}"
    masked, tokens = tokenize_dates(text, vault)
    assert masked == "Date: <D_1>"
    assert tokens == ["<D_1>"]
    assert len(vault) == 1
    entry = vault.get("<D_1>")
    assert entry is not None
    assert entry.raw == raw_date
    assert entry.kind == "date"


# ---------------------------------------------------------------------------
# 5. Invalid dates (Must NOT be recognized as dates)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("invalid_date", [
    "2026-13-01",  # Month 13
    "2026-00-01",  # Month 0
    "2026-01-32",  # Day 32
    "2026-01-00",  # Day 0
    "13/40/2026",  # Month 13, Day 40
    "32/01/2026",  # Day 32
    "00/10/2026",  # Zero month
    "10/00/2026",  # Zero day
    "15/20/2026",  # Both > 12
    "20-25-2026",  # Both > 12
    "2026-02-29",  # 2026 is not a leap year
    "02/29/2026",  # 2026 is not a leap year
    "02/30/2026",  # Feb 30 does not exist
    "02/31/2026",  # Feb 31 does not exist
    "31/04/2026",  # April has 30 days
    "2026-04-31",  # April has 30 days
    "2026-06-31",  # June has 30 days
    "2026-09-31",  # September has 30 days
    "2026-11-31",  # November has 30 days
    "31.02.2026",  # Feb 31
])
def test_invalid_calendar_dates_not_tokenized(invalid_date):
    vault = Vault()
    text = f"Sample: {invalid_date}"
    masked, tokens = tokenize_dates(text, vault)
    assert masked == text
    assert tokens == []
    assert len(vault) == 0


# ---------------------------------------------------------------------------
# 6. Negative tests: Money amounts (MUST NOT be swallowed)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("money_str", [
    "$33.99",
    "$12.50",
    "12.50",
    "33.99",
    "1,234.56",
    "1.234,56",
    "(12.50)",
    "12.50-",
    "12.50 CR",
    "-12.50",
    "33.99T",
    "100.00",
    "0.99",
    "10.50",
    "$10.11.12",
    "10.11.12 USD",
    "12.50 EUR",
    "100.00 VND",
    "USD 10.11.12",
    "$ 08/01/2026",  # Preceded by currency symbol with space -> money, not pure date
])
def test_negative_money_amounts_not_swallowed(money_str):
    vault = Vault()
    text = f"Total: {money_str}"
    masked, tokens = tokenize_dates(text, vault)
    assert masked == text
    assert tokens == []
    assert len(vault) == 0


# ---------------------------------------------------------------------------
# 7. Negative tests: Quantities and Product Specs (MUST NOT be swallowed)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spec_or_qty", [
    "1.25 lb",
    "2.50 kg",
    "2 @ 3.50",
    "3 x 4.00",
    "24/12 OZ",
    "12/1 L",
    "6X32 OZ",
    "750ML",
    "5LB",
    "12OZ",
    "12-PACK",
    "6-CT",
    "10-INCH",
    "1/2",
    "3/4",
    "12/24",
])
def test_negative_quantities_and_specs_not_swallowed(spec_or_qty):
    vault = Vault()
    text = f"Item specification: {spec_or_qty}"
    masked, tokens = tokenize_dates(text, vault)
    assert masked == text
    assert tokens == []
    assert len(vault) == 0


# ---------------------------------------------------------------------------
# 8. Negative tests: Identifiers, Phones, IPs, Times (MUST NOT be swallowed)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tech_str", [
    "INV-2026-0831",
    "PO-12345",
    "INV-2026-08-01",
    "2026-08-01-A",
    "123-456-7890",
    "(123) 456-7890",
    "192.168.1.1",
    "10.20.30.40",
    "10:30:00",
    "12:00 PM",
    "v1.2.3",
    "1.2.3.4",
    "12-34-5678",
    "12345678",
    "2026",  # Standalone 4-digit number
])
def test_negative_identifiers_not_swallowed(tech_str):
    vault = Vault()
    text = f"Reference: {tech_str}"
    masked, tokens = tokenize_dates(text, vault)
    assert masked == text
    assert tokens == []
    assert len(vault) == 0


# ---------------------------------------------------------------------------
# 9. Vault Entry Attributes & Configuration
# ---------------------------------------------------------------------------

def test_vault_entry_metadata():
    vault = Vault()
    text = "Shipped: 2026-08-15"
    masked, tokens = tokenize_dates(text, vault, start_index=5, page=3)
    assert masked == "Shipped: <D_5>"
    assert tokens == ["<D_5>"]

    entry = vault.get("<D_5>")
    assert entry is not None
    assert entry.token == "<D_5>"
    assert entry.raw == "2026-08-15"
    assert entry.kind == "date"
    assert entry.page == 3
    assert entry.bbox == (0.0, 0.0, 0.0, 0.0)
    assert entry.conf == 1.0
    assert entry.neg_hint is False


def test_sequential_indexing_across_calls():
    vault = Vault()
    text_page_1 = "Invoice Date: 08/01/2026\nDue Date: Aug 15, 2026"
    masked_1, tokens_1 = tokenize_dates(text_page_1, vault, start_index=1, page=1)
    assert masked_1 == "Invoice Date: <D_1>\nDue Date: <D_2>"
    assert tokens_1 == ["<D_1>", "<D_2>"]

    text_page_2 = "Delivery Date: 2026-08-20"
    masked_2, tokens_2 = tokenize_dates(
        text_page_2, vault, start_index=len(tokens_1) + 1, page=2
    )
    assert masked_2 == "Delivery Date: <D_3>"
    assert tokens_2 == ["<D_3>"]

    assert len(vault) == 3
    assert vault["<D_1>"].page == 1
    assert vault["<D_2>"].page == 1
    assert vault["<D_3>"].page == 2


# ---------------------------------------------------------------------------
# 10. Multiple and Repeated Dates
# ---------------------------------------------------------------------------

def test_repeated_identical_dates_get_distinct_tokens():
    vault = Vault()
    text = "Order Date: 08/01/2026 | Invoice Date: 08/01/2026"
    masked, tokens = tokenize_dates(text, vault)
    assert masked == "Order Date: <D_1> | Invoice Date: <D_2>"
    assert tokens == ["<D_1>", "<D_2>"]
    assert len(vault) == 2
    assert vault["<D_1>"].raw == "08/01/2026"
    assert vault["<D_2>"].raw == "08/01/2026"


def test_punctuation_around_dates_preserved():
    vault = Vault()
    text = "Date was (08/01/2026), followed by [2026-08-15]; due: Aug 01, 2026."
    masked, tokens = tokenize_dates(text, vault)
    assert masked == "Date was (<D_1>), followed by [<D_2>]; due: <D_3>."
    assert tokens == ["<D_1>", "<D_2>", "<D_3>"]
    assert len(vault) == 3


# ---------------------------------------------------------------------------
# 11. Realistic mixed document snippet
# ---------------------------------------------------------------------------

def test_realistic_invoice_document():
    vault = Vault()
    doc_text = (
        "ACME SUPPLY CORP\n"
        "INVOICE # INV-2026-0831\n"
        "Date: 08/01/2026\n"
        "Due Date: Aug 15, 2026\n"
        "PO Number: PO-998877\n"
        "Line 1: 24/12 OZ Tomato Sauce @ $33.99 ea | Total: $33.99\n"
        "Line 2: 1.25 lb Cheese @ 12.50 / lb | Total: $15.62\n"
        "Subtotal: $49.61\n"
        "Discount: (12.50)\n"
        "Tax (8.25%): $3.06\n"
        "Total Due: $40.17 USD\n"
        "Paid on 01-Sep-26 via check # 1234.\n"
        "Next statement date: 2026.09.01"
    )

    masked, tokens = tokenize_dates(doc_text, vault)

    # Assert exactly the 4 dates were tokenized
    assert tokens == ["<D_1>", "<D_2>", "<D_3>", "<D_4>"]
    assert len(vault) == 4

    # Check raw values in vault
    assert vault["<D_1>"].raw == "08/01/2026"
    assert vault["<D_2>"].raw == "Aug 15, 2026"
    assert vault["<D_3>"].raw == "01-Sep-26"
    assert vault["<D_4>"].raw == "2026.09.01"

    # Crucially assert that money amounts, specs, IDs, and PO numbers remain in the masked text
    assert "INV-2026-0831" in masked
    assert "PO-998877" in masked
    assert "24/12 OZ" in masked
    assert "$33.99" in masked
    assert "1.25 lb" in masked
    assert "12.50 / lb" in masked
    assert "$15.62" in masked
    assert "$49.61" in masked
    assert "(12.50)" in masked
    assert "$3.06" in masked
    assert "$40.17 USD" in masked
