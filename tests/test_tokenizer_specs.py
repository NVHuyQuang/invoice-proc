"""Unit tests for product specification protection (PLAN 3.4).

Tests cover:
- Positive specification formats (attached, multiplier/division, hyphenated, paper sizes)
- Negative examples (separated transaction quantities MUST NOT be preserved)
- Case insensitivity and decimal specifications
- Round-trip unprotection and interaction with tokenization placeholders
- Dynamic SPEC_UNITS handling from config
"""

import pytest
import config
from core.tokenizer_specs import protect_specs, unprotect_specs


class TestPositiveSpecs:
    """Positive test cases required by PLAN 3.4 and prompt."""

    def test_attached_specs_from_plan(self):
        """Test primary attached positive examples: 750ML, 5LB, 12OZ, A4, 500G."""
        cases = ["750ML", "5LB", "12OZ", "A4", "500G"]
        for case in cases:
            protected, specs = protect_specs(case)
            assert len(specs) == 1, f"Expected 1 spec for {case}, got {len(specs)}"
            assert specs[0]["raw"] == case
            assert unprotect_specs(protected, specs) == case

    def test_multiplier_specs_from_plan(self):
        """Test multiplier and pack division positive examples: 6X32 OZ, 12x1 L, 24/12 OZ."""
        cases = ["6X32 OZ", "12x1 L", "24/12 OZ"]
        for case in cases:
            protected, specs = protect_specs(case)
            assert len(specs) == 1, f"Expected 1 spec for {case}, got {len(specs)}"
            assert specs[0]["raw"] == case
            assert specs[0]["kind"] == "multiplier"
            assert unprotect_specs(protected, specs) == case

    def test_hyphenated_specs_from_plan(self):
        """Test hyphenated positive examples: 12-PACK, 6-CT, 10-INCH."""
        cases = ["12-PACK", "6-CT", "10-INCH"]
        for case in cases:
            protected, specs = protect_specs(case)
            assert len(specs) == 1, f"Expected 1 spec for {case}, got {len(specs)}"
            assert specs[0]["raw"] == case
            assert specs[0]["kind"] == "hyphenated"
            assert unprotect_specs(protected, specs) == case

    def test_case_insensitivity(self):
        """Units and spec patterns should match regardless of casing."""
        cases = [
            ("750ml", "750ml"),
            ("750mL", "750mL"),
            ("5lb", "5lb"),
            ("12oz", "12oz"),
            ("500g", "500g"),
            ("a4", "a4"),
            ("6x32 oz", "6x32 oz"),
            ("12x1 l", "12x1 l"),
            ("12-pack", "12-pack"),
            ("6-ct", "6-ct"),
            ("10-inch", "10-inch"),
        ]
        for text, expected_raw in cases:
            protected, specs = protect_specs(text)
            assert len(specs) == 1, f"Expected 1 spec for {text}"
            assert specs[0]["raw"] == expected_raw
            assert unprotect_specs(protected, specs) == text

    def test_decimal_quantities_in_specs(self):
        """Decimal values in attached, multiplier, and hyphenated specs."""
        cases = ["1.5L", "0.75L", "2.5KG", "0.5LB", "12x1.5 L", "6x0.75 L", "0.5-GAL"]
        for case in cases:
            protected, specs = protect_specs(case)
            assert len(specs) == 1, f"Expected 1 spec for {case}"
            assert specs[0]["raw"] == case
            assert unprotect_specs(protected, specs) == case

    def test_fluid_ounces(self):
        """FL OZ unit variations (with space, hyphen, or concatenated)."""
        cases = ["12FL OZ", "12FLOZ", "6X32 FL OZ", "24/12 FL OZ", "12-FL-OZ"]
        for case in cases:
            protected, specs = protect_specs(case)
            assert len(specs) == 1, f"Expected 1 spec for {case}"
            assert specs[0]["raw"] == case
            assert unprotect_specs(protected, specs) == case

    def test_dimensions_multi_axis(self):
        """Multi-dimensional specs like 10x12 INCH, 2x3x4 INCH."""
        cases = ["10x12 INCH", "2x3x4 INCH", "10X12X14 INCH"]
        for case in cases:
            protected, specs = protect_specs(case)
            assert len(specs) == 1, f"Expected 1 spec for {case}"
            assert specs[0]["raw"] == case
            assert specs[0]["kind"] == "multiplier"
            assert unprotect_specs(protected, specs) == case

    def test_all_config_spec_units_attached(self):
        """Verify attached specs work for single-word units in SPEC_UNITS (excluding counting units EA, CS, CASE, BOX)."""
        disallowed_attached = {"FL OZ", "EA", "CS", "CASE", "BOX"}
        for unit in config.SPEC_UNITS:
            if unit in disallowed_attached:
                continue
            text = f"10{unit}"
            protected, specs = protect_specs(text)
            assert len(specs) == 1, f"Expected spec for {text}"
            assert specs[0]["raw"] == text
            assert unprotect_specs(protected, specs) == text

    def test_all_config_spec_units_hyphenated(self):
        """Verify hyphenated specs work for units in SPEC_UNITS."""
        for unit in config.SPEC_UNITS:
            if unit == "FL OZ":
                text = "12-FL-OZ"
            else:
                text = f"12-{unit}"
            protected, specs = protect_specs(text)
            assert len(specs) == 1, f"Expected spec for {text}"
            assert specs[0]["raw"] == text
            assert unprotect_specs(protected, specs) == text

    def test_paper_sizes(self):
        """Paper sizes A0..A9, B0..B9."""
        cases = ["A3", "A4", "A5", "B4", "B5", "a4", "b5"]
        for case in cases:
            protected, specs = protect_specs(case)
            assert len(specs) == 1, f"Expected spec for {case}"
            assert specs[0]["raw"] == case
            assert specs[0]["kind"] == "paper_size"
            assert unprotect_specs(protected, specs) == case


class TestNegativeSpecs:
    """Negative test cases: separated quantities and non-spec numbers MUST NOT be preserved."""

    def test_mandatory_negative_examples(self):
        """BẮT BUỘC KHÔNG ĐƯỢC GIỮ: 2 lb, 3 ea, 1 case (transaction quantities)."""
        mandatories = ["2 lb", "3 ea", "1 case"]
        for neg in mandatories:
            protected, specs = protect_specs(neg)
            assert len(specs) == 0, f"Negative example {neg!r} must NOT be preserved, got specs: {specs}"
            assert protected == neg

    def test_separated_quantities_with_units(self):
        """Separated number + unit are transaction quantities and must not be protected."""
        separated = [
            "5 kg", "100 ct", "12 oz", "10 box", "4 gal",
            "2 pack", "5 pk", "24 cs", "1 doz", "3 set",
            "10 bag", "20 btl", "6 can", "2 piece", "1 pair"
        ]
        for text in separated:
            protected, specs = protect_specs(text)
            assert len(specs) == 0, f"Separated quantity {text!r} must not be preserved, got: {specs}"
            assert protected == text

    def test_pricing_and_arithmetic(self):
        """Unit price expressions and arithmetic MUST NOT match specs."""
        cases = ["3 x 4.00", "2 @ 3.50", "10 + 20", "5 - 2", "12 * 4"]
        for text in cases:
            protected, specs = protect_specs(text)
            assert len(specs) == 0, f"Pricing/arithmetic {text!r} must not be preserved, got: {specs}"
            assert protected == text

    def test_money_formats(self):
        """Currency and money values must not be matched as specs."""
        money_cases = [
            "$33.99", "33.99", "1,234.56", "(12.50)",
            "12.50-", "12.50 CR", "-12.50", "33.99T"
        ]
        for text in money_cases:
            protected, specs = protect_specs(text)
            assert len(specs) == 0, f"Money format {text!r} must not be preserved, got: {specs}"
            assert protected == text

    def test_dates(self):
        """Date formats must not be matched as specs."""
        dates = ["24/12/2026", "12-10-2026", "01/08/2026", "2026-08-31", "08/01/2026"]
        for date_str in dates:
            protected, specs = protect_specs(date_str)
            assert len(specs) == 0, f"Date {date_str!r} must not be preserved as spec, got: {specs}"
            assert protected == date_str

    def test_identifiers_and_skus(self):
        """Alphanumeric IDs and codes must not be partially swallowed by spec tokenizer."""
        identifiers = ["INV-2026-0831", "PO-9988", "ITEM #4", "REF-12345", "SKU100"]
        for ident in identifiers:
            protected, specs = protect_specs(ident)
            assert len(specs) == 0, f"Identifier {ident!r} must not be preserved as spec, got: {specs}"
            assert protected == ident

    def test_unrelated_words_and_substrings(self):
        """Words containing unit letters but not matching SPEC_UNITS must not match."""
        cases = ["100 apple", "100LIGHTS", "500GRAMS", "B2B", "MP3", "4K", "100M", "100m"]
        for case in cases:
            protected, specs = protect_specs(case)
            assert len(specs) == 0, f"Word {case!r} must not be preserved as spec, got: {specs}"
            assert protected == case

    def test_long_ids_not_matched_as_specs(self):
        """Long invoice or account IDs like 12345678-CT or 98765432-PK must not match specs."""
        cases = ["12345678-CT", "98765432-PK", "12345-BOX", "87654321-CS"]
        for case in cases:
            protected, specs = protect_specs(case)
            assert len(specs) == 0, f"Long ID {case!r} must not be preserved as spec, got: {specs}"
            assert protected == case

    def test_hyphen_with_spaces_not_spec(self):
        """Hyphens with spaces must not match specs (e.g. '10 - CASE', '12 - PACK')."""
        cases = ["10 - CASE", "12 - PACK", "6 - CT", "10 - INCH"]
        for case in cases:
            protected, specs = protect_specs(case)
            assert len(specs) == 0, f"Spaced hyphen {case!r} must not be preserved as spec, got: {specs}"
            assert protected == case

    def test_attached_counting_units_not_spec(self):
        """Counting units EA, CS, CASE, BOX attached to numbers must not be preserved as specs."""
        cases = [
            "3EA", "1CS", "1CASE", "5BOX",
            "3ea", "1cs", "1case", "5box",
            "10EA", "10CS", "10CASE", "10BOX"
        ]
        for case in cases:
            protected, specs = protect_specs(case)
            assert len(specs) == 0, f"Attached counting unit {case!r} must not be preserved as spec, got: {specs}"
            assert protected == case


class TestComplexSentencesAndRoundTrip:
    """Integration of positive and negative tokens within realistic invoice lines."""

    def test_mixed_line_with_positives_and_negatives(self):
        """Ensure specs are protected while transaction quantities remain unprotected."""
        text = "2 cases of HEINEKEN 6X32 OZ CANS and 1 BTL 750ML WINE at $45.00 each"
        protected, specs = protect_specs(text)

        # 2 cases -> negative (separated quantity)
        # 6X32 OZ -> positive spec
        # 1 BTL -> negative (separated quantity)
        # 750ML -> positive spec
        assert len(specs) == 2
        raw_specs = [s["raw"] for s in specs]
        assert "6X32 OZ" in raw_specs
        assert "750ML" in raw_specs

        # Verify placeholders contain NO digits
        for s in specs:
            assert not any(c.isdigit() for c in s["placeholder"])

        # Simulate number tokenization on the remaining numbers
        # Use regex so earlier replacements don't collide
        import re
        simulated_tokenized = re.sub(r"\b2\b", "<N_1>", protected)
        simulated_tokenized = re.sub(r"\b1\b", "<N_2>", simulated_tokenized)
        simulated_tokenized = re.sub(r"45\.00", "<N_3>", simulated_tokenized)

        # Unprotect should restore specs while keeping number tokens intact
        restored = unprotect_specs(simulated_tokenized, specs)
        assert "<N_1> cases of HEINEKEN 6X32 OZ CANS and <N_2> BTL 750ML WINE at $<N_3> each" == restored

    def test_mandatory_positives_and_negatives_sentence(self):
        """Test sentence containing ALL examples cited in prompt and PLAN 3.4."""
        text = "Order: 2 lb beef, 3 ea eggs, 1 case milk, 750ML wine, 5LB flour, 12OZ sauce, A4 paper, 500G butter, 6X32 OZ beer, 12x1 L oil, 24/12 OZ soda, 12-PACK cola, 6-CT mugs, 10-INCH pizza."
        protected, specs = protect_specs(text)

        raw_specs = [s["raw"] for s in specs]

        # Positives that MUST be protected
        expected_positives = [
            "750ML", "5LB", "12OZ", "A4", "500G",
            "6X32 OZ", "12x1 L", "24/12 OZ",
            "12-PACK", "6-CT", "10-INCH"
        ]
        for exp in expected_positives:
            assert exp in raw_specs, f"Expected {exp} to be in detected specs, got {raw_specs}"

        # Negatives that MUST NOT be protected
        assert "2 lb" not in raw_specs
        assert "3 ea" not in raw_specs
        assert "1 case" not in raw_specs

        # Restoring should produce the exact original string
        restored = unprotect_specs(protected, specs)
        assert restored == text

    def test_multiple_identical_specs(self):
        """Text with repeated specifications."""
        text = "Item 750ML red wine and item 750ML white wine"
        protected, specs = protect_specs(text)
        assert len(specs) == 2
        assert specs[0]["raw"] == "750ML"
        assert specs[1]["raw"] == "750ML"
        assert specs[0]["placeholder"] != specs[1]["placeholder"]
        restored = unprotect_specs(protected, specs)
        assert restored == text

    def test_over_26_specs_placeholder_generation(self):
        """Ensure placeholder naming works beyond 26 tokens (A..Z, AA..ZZ)."""
        specs_input = " ".join([f"{i}LB" for i in range(1, 35)])
        protected, specs = protect_specs(specs_input)
        assert len(specs) == 34
        assert specs[0]["placeholder"] == "__SPEC_A__"
        assert specs[25]["placeholder"] == "__SPEC_Z__"
        assert specs[26]["placeholder"] == "__SPEC_AA__"
        assert specs[27]["placeholder"] == "__SPEC_AB__"

        # Ensure NONE of the placeholders contain digits
        for s in specs:
            assert not any(c.isdigit() for c in s["placeholder"])

        restored = unprotect_specs(protected, specs)
        assert restored == specs_input

    def test_empty_and_none_handling(self):
        """Gracefully handle empty or None inputs."""
        assert protect_specs("") == ("", [])
        assert protect_specs(None) == ("", [])
        assert unprotect_specs("", []) == ""
        assert unprotect_specs(None, []) == ""
        assert unprotect_specs("plain text", []) == "plain text"
        assert unprotect_specs("plain text", None) == "plain text"


class TestDynamicSpecUnits:
    """Verify that SPEC_UNITS is read dynamically from config.py."""

    def test_dynamic_unit_addition(self, monkeypatch):
        """Adding a unit to config.SPEC_UNITS dynamically enables its protection."""
        new_units = config.SPEC_UNITS | {"WIDGETUNIT"}
        monkeypatch.setattr(config, "SPEC_UNITS", new_units)

        text = "500WIDGETUNIT and 10-WIDGETUNIT"
        protected, specs = protect_specs(text)
        assert len(specs) == 2
        assert specs[0]["raw"] == "500WIDGETUNIT"
        assert specs[1]["raw"] == "10-WIDGETUNIT"
        assert unprotect_specs(protected, specs) == text
