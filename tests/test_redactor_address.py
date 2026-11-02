"""Unit tests for core/redactor_address.py.

PLAN 3.2: Redact physical addresses and person names following key labels.
Must NOT redact item/vendor names (e.g., 'Smith Butter', 'St. Louis Ribs').
Invariants:
- Never read real invoice files.
- Uses replacement tags <ADDR> and <PERSON>.
"""

import pytest
from core.redactor_address import redact_addresses


class TestAddressRedaction:
    """Tests for physical address redaction (street, suite, state/zip, PO Box)."""

    @pytest.mark.parametrize(
        "address_input",
        [
            "123 Main St",
            "123 Main St.",
            "456 Elm Street",
            "789 Oak Ave",
            "101 Pine Avenue",
            "202 Maple Blvd",
            "303 Cedar Boulevard",
            "404 Walnut Rd",
            "505 Birch Road",
            "606 Spruce Way",
            "707 Ash Dr",
            "808 Willow Drive",
            "909 Magnolia Lane",
            "111 Palm Ln",
            "123 5th Ave",
            "456 42nd St",
            "123 1st Street",
            "123 N. Main St.",
            "456 South Elm Avenue",
            "789 E Washington Blvd",
            "100 W 42nd St",
            "456 Elm St NW",
            "101 Martin Luther King Jr Blvd",
        ],
    )
    def test_street_address_patterns(self, address_input: str):
        """Street address formats should be replaced with <ADDR>."""
        redacted, meta = redact_addresses(address_input)
        assert redacted == "<ADDR>"
        assert len(meta) == 1
        assert meta[0]["token"] == "<ADDR>"
        assert meta[0]["type"] == "address"
        assert meta[0]["raw"] == address_input

    @pytest.mark.parametrize(
        "address_input",
        [
            "123 Main St, Suite 400",
            "123 Main St, Ste 100",
            "123 Main St, Floor 2",
            "123 Main St, Unit 4B",
            "123 Main St, Apt 3A",
            "123 Main St, Austin, TX 78701",
            "123 Main St Austin TX 78701",
            "123 Main St, Suite 400, Austin, TX 78701",
            "500 Oracle Parkway, Redwood City, CA 94065",
            "100 St. Louis Ave",  # St. Louis is part of street name, ending with Ave
        ],
    )
    def test_combined_street_address(self, address_input: str):
        """Combined street addresses with unit/city/state/zip should redact as single <ADDR>."""
        redacted, meta = redact_addresses(address_input)
        assert redacted == "<ADDR>"
        assert len(meta) == 1
        assert meta[0]["token"] == "<ADDR>"
        assert meta[0]["type"] == "address"
        assert meta[0]["raw"] == address_input

    @pytest.mark.parametrize(
        "zip_input",
        [
            "Austin, TX 78701",
            "Austin TX 78701",
            "San Francisco, CA 94103",
            "New York, NY 10001-1234",
            "TX 75001-1234",
            "CA 94103",
            "FL 33101",
            "WA 98101-1000",
        ],
    )
    def test_standalone_state_and_zip(self, zip_input: str):
        """City/State/Zip and State/Zip formats should be replaced with <ADDR>."""
        redacted, meta = redact_addresses(zip_input)
        assert redacted == "<ADDR>"
        assert len(meta) == 1
        assert meta[0]["token"] == "<ADDR>"
        assert meta[0]["type"] == "address"
        assert meta[0]["raw"] == zip_input

    @pytest.mark.parametrize(
        "suite_input",
        [
            "Suite 400",
            "Suite 101-A",
            "Ste. 200",
            "Ste 5B",
            "Floor 3",
            "3rd Floor",
            "Fl. 2",
            "Unit 5",
            "Unit B",
            "Unit 12B",
            "Apt 12B",
            "Apt. 4",
        ],
    )
    def test_standalone_suite_floor_unit(self, suite_input: str):
        """Standalone suite, floor, and unit specifiers should be replaced with <ADDR>."""
        redacted, meta = redact_addresses(suite_input)
        assert redacted == "<ADDR>"
        assert len(meta) == 1
        assert meta[0]["token"] == "<ADDR>"
        assert meta[0]["type"] == "address"
        assert meta[0]["raw"] == suite_input

    @pytest.mark.parametrize(
        "pobox_input",
        [
            "PO Box 1234",
            "P.O. Box 5678",
            "Post Office Box 789",
            "PO Box 999, Dallas, TX 75201",
            "P.O. Box 456, Austin, TX 78701-1234",
        ],
    )
    def test_po_box_addresses(self, pobox_input: str):
        """PO Box formats should be replaced with <ADDR>."""
        redacted, meta = redact_addresses(pobox_input)
        assert redacted == "<ADDR>"
        assert len(meta) == 1
        assert meta[0]["token"] == "<ADDR>"
        assert meta[0]["type"] == "address"
        assert meta[0]["raw"] == pobox_input

    def test_address_with_context_label(self):
        """Labels preceding address should be preserved."""
        text = "Billing Address: 123 Main St, Suite 400, Austin, TX 78701"
        redacted, meta = redact_addresses(text)
        assert redacted == "Billing Address: <ADDR>"
        assert len(meta) == 1
        assert meta[0]["raw"] == "123 Main St, Suite 400, Austin, TX 78701"

        text2 = "SHIP TO: 456 Elm Ave\nDallas, TX 75201"
        redacted2, meta2 = redact_addresses(text2)
        assert redacted2 == "SHIP TO: <ADDR>\n<ADDR>"
        assert len(meta2) == 2


class TestPersonRedaction:
    """Tests for person names following labels: Server, Cashier, Cust(omer), Guest, Member, Name on card."""

    @pytest.mark.parametrize(
        "person_input,expected_output,expected_name",
        [
            ("Server: John Doe", "Server: <PERSON>", "John Doe"),
            ("Server: John", "Server: <PERSON>", "John"),
            ("SERVER: ALICE", "SERVER: <PERSON>", "ALICE"),
            ("server: Michael", "server: <PERSON>", "Michael"),
            ("Server Name: Jane Doe", "Server Name: <PERSON>", "Jane Doe"),
            ("Cashier: Jane Smith", "Cashier: <PERSON>", "Jane Smith"),
            ("Cashier: Jane", "Cashier: <PERSON>", "Jane"),
            ("CASHIER: BOB", "CASHIER: <PERSON>", "BOB"),
            ("Cashier Name: Sarah", "Cashier Name: <PERSON>", "Sarah"),
            ("Customer: Alice Wonderland", "Customer: <PERSON>", "Alice Wonderland"),
            ("Customer Name: Bob Builder", "Customer Name: <PERSON>", "Bob Builder"),
            ("Cust: Robert Johnson", "Cust: <PERSON>", "Robert Johnson"),
            ("Cust Name: Charlie", "Cust Name: <PERSON>", "Charlie"),
            ("Guest: Charlie Brown", "Guest: <PERSON>", "Charlie Brown"),
            ("Guest Name: Lucy van Pelt", "Guest Name: <PERSON>", "Lucy van Pelt"),
            ("Member: David Beckham", "Member: <PERSON>", "David Beckham"),
            ("Member Name: Victoria", "Member Name: <PERSON>", "Victoria"),
            ("Name on card: EMILY BLUNT", "Name on card: <PERSON>", "EMILY BLUNT"),
            ("Name on Card: John Doe", "Name on Card: <PERSON>", "John Doe"),
            ("NAME ON CARD: JANE DOE", "NAME ON CARD: <PERSON>", "JANE DOE"),
            ("Cardholder: Robert Smith", "Cardholder: <PERSON>", "Robert Smith"),
            ("Cardholder Name: Alice Brown", "Cardholder Name: <PERSON>", "Alice Brown"),
            ("Cashier #12 Alice Cooper", "Cashier #12 <PERSON>", "Alice Cooper"),
            ("Server: 104 Bob Smith", "Server: 104 <PERSON>", "Bob Smith"),
            ("Server: Mr. Anderson", "Server: <PERSON>", "Mr. Anderson"),
            ("Guest: Dr. Watson", "Guest: <PERSON>", "Dr. Watson"),
        ],
    )
    def test_person_name_patterns(
        self, person_input: str, expected_output: str, expected_name: str
    ):
        """Person names after recognized labels must be replaced with <PERSON>."""
        redacted, meta = redact_addresses(person_input)
        assert redacted == expected_output
        assert len(meta) == 1
        assert meta[0]["token"] == "<PERSON>"
        assert meta[0]["type"] == "person"
        assert meta[0]["raw"] == expected_name

    def test_person_name_with_trailing_receipt_metadata(self):
        """Receipt metadata (Table, Guests, Check, Order) on the same line must not be swallowed."""
        text = "Server: John Doe    Table: 14    Guests: 2"
        redacted, meta = redact_addresses(text)
        assert redacted == "Server: <PERSON>    Table: 14    Guests: 2"
        assert len(meta) == 1
        assert meta[0]["raw"] == "John Doe"

        text2 = "Cashier: Jane Smith | Check: 1002 | Station: 3"
        redacted2, meta2 = redact_addresses(text2)
        assert redacted2 == "Cashier: <PERSON> | Check: 1002 | Station: 3"
        assert len(meta2) == 1
        assert meta2[0]["raw"] == "Jane Smith"

    def test_person_name_with_secondary_label_on_same_line(self):
        """Person names followed by secondary labels like Total: $50 on the same line."""
        text = "Server: Alice Smith Total: $50"
        redacted, meta = redact_addresses(text)
        assert redacted == "Server: <PERSON> Total: $50"
        assert len(meta) == 1
        assert meta[0]["raw"] == "Alice Smith"

        text2 = "Cashier: Bob Jones Subtotal: $45.00 Tax: $3.50"
        redacted2, meta2 = redact_addresses(text2)
        assert redacted2 == "Cashier: <PERSON> Subtotal: $45.00 Tax: $3.50"
        assert len(meta2) == 1
        assert meta2[0]["raw"] == "Bob Jones"


class TestNegativeCases:
    """Tests ensuring item names, vendor names, and numerical values are NEVER masked."""

    @pytest.mark.parametrize(
        "item_text",
        [
            "Smith Butter",
            "Smith's Butter",
            "Smith & Nephew 500ml",
            "John's Pizza Large",
            "St. Louis Ribs",
            "St. Louis Style BBQ Ribs",
            "1 St. Louis Ribs $18.99",
            "2 St. Louis BBQ Ribs",
            "1x St. Louis Pork Ribs",
            "Bourbon Street Chicken",
            "1 Bourbon Street Chicken 14.50",
            "Wall Street Journal",
            "4th Street Burger",
            "5th Avenue Salad",
            "Dr. Pepper 12oz Can",
            "Dr. Pepper 2L",
            "St. Germain Elderflower Liqueur",
            "St. Paul Summer Sausage",
            "St. Clair Potato Salad",
            "Laneige Lip Sleeping Mask",
        ],
    )
    def test_item_and_vendor_names_not_redacted(self, item_text: str):
        """Item and vendor names must NEVER be redacted as <ADDR> or <PERSON>."""
        redacted, meta = redact_addresses(item_text)
        assert redacted == item_text
        assert len(meta) == 0

    @pytest.mark.parametrize(
        "unit_text",
        [
            "Unit Price: $12.00",
            "Unit Price",
            "Unit Cost: 5.50",
            "Per Unit: $3.50",
            "Per Unit",
            "10 Units @ 2.50",
            "Unit of Measure: EA",
            "Unit: Box",
            "Unit: KG",
        ],
    )
    def test_invoice_unit_metrics_not_redacted(self, unit_text: str):
        """Invoice pricing/measurement units must not be confused with apartment/suite Unit."""
        redacted, meta = redact_addresses(unit_text)
        assert redacted == unit_text
        assert len(meta) == 0

    @pytest.mark.parametrize(
        "non_person_text",
        [
            "Server: 12",
            "Server: #104",
            "Cashier: 5",
            "Cashier: #42",
            "Guest: 2",
            "Guest Count: 4",
            "Guests: 3",
            "Member: 12345",
            "Member: 99887766",
            "Member: Gold",
            "Member: VIP",
            "Member: Platinum",
            "Customer: Walk-in",
            "Customer: Walkin",
            "Server: None",
            "Cashier: N/A",
            "Server: Unknown",
        ],
    )
    def test_non_person_identifiers_not_redacted(self, non_person_text: str):
        """Numerical IDs, guest counts, and status keywords must not be redacted as <PERSON>."""
        redacted, meta = redact_addresses(non_person_text)
        assert redacted == non_person_text
        assert len(meta) == 0


class TestEdgeCasesAndMetadata:
    """Tests for edge cases, empty input, and metadata integrity."""

    def test_empty_string(self):
        """Empty input string should return empty string and empty metadata."""
        redacted, meta = redact_addresses("")
        assert redacted == ""
        assert meta == []

    def test_no_pii_present(self):
        """Text without addresses or person labels should pass through unchanged."""
        text = "Subtotal: $100.00\nSales Tax: $8.25\nTotal Due: $108.25"
        redacted, meta = redact_addresses(text)
        assert redacted == text
        assert meta == []

    def test_metadata_contract(self):
        """Metadata entries must accurately track type, raw substring, token, and start/end offsets."""
        text = "Server: John Doe\nLocation: 123 Main St, Austin, TX 78701\nCashier: Jane"
        redacted, meta = redact_addresses(text)

        assert len(meta) == 3
        for entry in meta:
            assert entry["type"] in ("address", "person")
            assert entry["token"] in ("<ADDR>", "<PERSON>")
            assert text[entry["start"] : entry["end"]] == entry["raw"]

        assert meta[0]["type"] == "person"
        assert meta[0]["raw"] == "John Doe"
        assert meta[0]["token"] == "<PERSON>"

        assert meta[1]["type"] == "address"
        assert meta[1]["raw"] == "123 Main St, Austin, TX 78701"
        assert meta[1]["token"] == "<ADDR>"

        assert meta[2]["type"] == "person"
        assert meta[2]["raw"] == "Jane"
        assert meta[2]["token"] == "<PERSON>"

        assert redacted == "Server: <PERSON>\nLocation: <ADDR>\nCashier: <PERSON>"

    def test_full_synthetic_receipt(self):
        """A complete synthetic receipt should have addresses and staff/customer names redacted while keeping items intact."""
        synthetic_receipt = (
            "THE CORNER BISTRO\n"
            "123 Main Street, Suite 400\n"
            "Austin, TX 78701\n"
            "Tel: 555-123-4567\n"
            "\n"
            "Server: John Doe    Table: 14\n"
            "Date: 10/24/2026    Time: 18:30\n"
            "--------------------------------\n"
            "1  St. Louis Ribs            $18.99\n"
            "2  Smith Butter 250g          $9.00\n"
            "1  Bourbon Street Chicken     $14.50\n"
            "--------------------------------\n"
            "Subtotal:                    $42.49\n"
            "Tax:                          $3.51\n"
            "Total:                       $46.00\n"
            "\n"
            "Payment: VISA ending 1234\n"
            "Name on card: ALICE SMITH\n"
            "Cashier: Bob K.\n"
            "Thank you for visiting!\n"
        )

        redacted, meta = redact_addresses(synthetic_receipt)

        # Addresses and names are redacted
        assert "<ADDR>" in redacted
        assert "<PERSON>" in redacted
        assert "John Doe" not in redacted
        assert "ALICE SMITH" not in redacted
        assert "Bob K." not in redacted
        assert "123 Main Street, Suite 400" not in redacted
        assert "Austin, TX 78701" not in redacted

        # Items and layout are preserved
        assert "St. Louis Ribs" in redacted
        assert "Smith Butter 250g" in redacted
        assert "Bourbon Street Chicken" in redacted
        assert "Server: <PERSON>    Table: 14" in redacted
        assert "Name on card: <PERSON>" in redacted
        assert "Cashier: <PERSON>" in redacted
