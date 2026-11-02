"""Adversarial tests for financial math and money handling.

Covers PLAN 5.2, 5.4, 5.5 money math attack vectors:
1. Float sneaking in (Decimal type assertion & precision contamination).
2. Rounding edges (0.005, 0.009, 0.015 unit price x fractional qty discrepancies).
3. Negative formats ((12.50), trailing minus 12.50-, CR 12.50 CR, double negative --12.50).
4. Locale inversion (1.234,56 vs 1,234.56, mixed batch, ambiguous 1,234).
5. Zero & negative quantities, zero grand total, division by zero safety.
6. Credit memo valid negative grand total vs regular invoice rejection.
"""

from decimal import Decimal, InvalidOperation, DivisionByZero
from typing import List, Optional
import pytest

from config import (
    TIER1_BASE_TOLERANCE,
    TIER1_QTY_FACTOR,
    TIER2_BASE_TOLERANCE,
    TIER2_LINE_FACTOR,
    TIER3_TOLERANCE,
    TIER4_TOLERANCE,
)
from models.schema import (
    CanonicalInvoice,
    CanonicalLineItem,
    CanonicalCharge,
    DocType,
    InvoiceStatus,
    LineItemKind,
)
from core.types import Provenance
from core.numparse import parse_number, detect_document_locale, AmbiguousNumberError
from core.validator_lines import validate_tier1_lines, validate_tier2_subtotal
from core.validator_totals import (
    validate_tier3_grand_total,
    validate_tier4_utility_total,
    validate_dates_and_metadata,
)


def _make_dummy_provenance() -> Provenance:
    return Provenance(page=1, bbox=(10.0, 20.0, 30.0, 40.0), ocr_conf=0.99, source="pdf_text")


# =====================================================================
# 1. Float Sneaking In & Precision Contamination Attacks
# =====================================================================

class TestFloatSneakingAttacks:
    """Attacks attempting to introduce float types or precision errors into money math."""

    def test_canonical_line_item_decimal_type_enforcement(self):
        """Monetary and quantity fields in CanonicalLineItem must be Decimal instances."""
        line = CanonicalLineItem(
            item_name="Ribeye Steak",
            qty=Decimal("2.50"),
            unit_price=Decimal("19.99"),
            line_total=Decimal("49.98"),
        )
        assert isinstance(line.qty, Decimal), "qty must be Decimal"
        assert isinstance(line.unit_price, Decimal), "unit_price must be Decimal"
        assert isinstance(line.line_total, Decimal), "line_total must be Decimal"
        assert not isinstance(line.qty, float)
        assert not isinstance(line.unit_price, float)
        assert not isinstance(line.line_total, float)

    def test_float_precision_drift_demonstration(self):
        """Demonstrate binary floating-point drift vs exact Decimal financial math."""
        # Classic float representation flaw: 0.1 + 0.2 != 0.3
        float_sum = 0.1 + 0.2
        assert float_sum != 0.3, "Float must exhibit binary representation drift"
        assert f"{float_sum:.17f}" == "0.30000000000000004"

        # Decimal exact representation
        dec_sum = Decimal("0.1") + Decimal("0.2")
        assert dec_sum == Decimal("0.3"), "Decimal addition must remain exact"

        # Accumulation over 100 small items ($0.07 each)
        float_accum = sum(0.07 for _ in range(100))
        assert float_accum != 7.00, "Float accumulation introduces epsilon drift"

        dec_accum = sum(Decimal("0.07") for _ in range(100))
        assert dec_accum == Decimal("7.00"), "Decimal accumulation must equal 7.00 exactly"

    def test_jsonl_serialization_preserves_decimals_as_strings(self):
        """to_jsonl_dict must serialize all Decimal values as exact strings, never floats."""
        invoice = CanonicalInvoice(
            source_file="test_inv.pdf",
            source_sha256="abc123hash",
            doc_type=DocType.GOODS_INVOICE,
            subtotal=Decimal("123.40"),  # Trailing zero must not be truncated to 123.4
            tax=Decimal("10.00"),
            grand_total=Decimal("133.40"),
            line_items=[
                CanonicalLineItem(
                    item_name="Item A",
                    qty=Decimal("1.500"),
                    unit_price=Decimal("82.266"),
                    line_total=Decimal("123.40"),
                )
            ],
            charges=[
                CanonicalCharge(description="Service Fee", amount=Decimal("5.50"))
            ],
        )

        jsonl_dict = invoice.to_jsonl_dict()

        # Check document-level totals
        assert jsonl_dict["subtotal"] == "123.40"
        assert isinstance(jsonl_dict["subtotal"], str)
        assert jsonl_dict["tax"] == "10.00"
        assert isinstance(jsonl_dict["tax"], str)
        assert jsonl_dict["grand_total"] == "133.40"
        assert isinstance(jsonl_dict["grand_total"], str)

        # Check line item fields
        line_dict = jsonl_dict["line_items"][0]
        assert line_dict["qty"] == "1.500"
        assert isinstance(line_dict["qty"], str)
        assert line_dict["unit_price"] == "82.266"
        assert isinstance(line_dict["unit_price"], str)
        assert line_dict["line_total"] == "123.40"
        assert isinstance(line_dict["line_total"], str)

        # Check charges
        charge_dict = jsonl_dict["charges"][0]
        assert charge_dict["amount"] == "5.50"
        assert isinstance(charge_dict["amount"], str)

    def test_parse_number_contract_returns_strictly_decimal(self):
        """parse_number must return Decimal type, never float or int."""
        parsed = parse_number("123.45")
        assert isinstance(parsed, Decimal), "parse_number must return Decimal"
        assert type(parsed) is Decimal
        assert not isinstance(parsed, float)
        assert not isinstance(parsed, int)


# =====================================================================
# 2. Rounding Edge Attacks: 0.005, 0.009, 0.015 Discrepancies
# =====================================================================

class TestRoundingBoundaryAttacks:
    """Attacks testing mathematical tolerance thresholds: 0.005, 0.009, 0.015 differences."""

    def test_tier1_pure_formula_boundaries_at_unit_qty(self):
        """Test the pure Tier 1 formula contract: tolerance = 0.01 + 0.005 * |qty|.

        At qty = 1:
        tolerance = 0.01 + 0.005 * 1.0 = 0.015.
        - 0.005 discrepancy: ALLOWED (<= 0.015)
        - 0.009 discrepancy: ALLOWED (<= 0.015)
        - 0.015 discrepancy: ALLOWED (exact boundary == 0.015)
        - 0.0151 / 0.016 discrepancy: REJECTED (> 0.015)
        """
        qty = Decimal("1.00")
        tolerance = TIER1_BASE_TOLERANCE + TIER1_QTY_FACTOR * abs(qty)
        assert tolerance == Decimal("0.015")

        # Discrepancy 0.005
        diff_005 = Decimal("0.005")
        assert diff_005 <= tolerance, "0.005 discrepancy must be within tolerance"

        # Discrepancy 0.009
        diff_009 = Decimal("0.009")
        assert diff_009 <= tolerance, "0.009 discrepancy must be within tolerance"

        # Discrepancy 0.015 (exact boundary)
        diff_015 = Decimal("0.015")
        assert diff_015 <= tolerance, "0.015 discrepancy must be accepted at boundary"

        # Discrepancy 0.016 (breach)
        diff_016 = Decimal("0.016")
        assert diff_016 > tolerance, "0.016 discrepancy must breach tolerance"

    def test_tier1_line_validation_boundary_0005_allowed(self):
        """Tier 1: Line with 0.005 rounding discrepancy must pass."""
        # unit_price = 10.00, qty = 1.00 -> calculated = 10.00, line_total = 10.005 (or 10.01)
        line = CanonicalLineItem(
            item_name="Item 0005",
            qty=Decimal("1.00"),
            unit_price=Decimal("10.00"),
            line_total=Decimal("10.005"),
        )
        passed, errors, checkable, uncheckable = validate_tier1_lines([line])
        assert passed is True
        assert len(errors) == 0
        assert checkable == 1

    def test_tier1_line_validation_boundary_0009_allowed(self):
        """Tier 1: Line with 0.009 rounding discrepancy must pass."""
        line = CanonicalLineItem(
            item_name="Item 0009",
            qty=Decimal("1.00"),
            unit_price=Decimal("10.00"),
            line_total=Decimal("10.009"),
        )
        passed, errors, checkable, uncheckable = validate_tier1_lines([line])
        assert passed is True
        assert len(errors) == 0
        assert checkable == 1

    def test_tier1_line_validation_boundary_0015_allowed(self):
        """Tier 1: Line with exactly 0.015 rounding discrepancy must pass at boundary."""
        line = CanonicalLineItem(
            item_name="Item 0015",
            qty=Decimal("1.00"),
            unit_price=Decimal("10.00"),
            line_total=Decimal("10.015"),
        )
        passed, errors, checkable, uncheckable = validate_tier1_lines([line])
        assert passed is True
        assert len(errors) == 0
        assert checkable == 1

    def test_tier1_line_validation_boundary_0016_rejected(self):
        """Tier 1: Line with 0.016 discrepancy exceeds 0.015 boundary and must fail."""
        line = CanonicalLineItem(
            item_name="Item 0016",
            qty=Decimal("1.00"),
            unit_price=Decimal("10.00"),
            line_total=Decimal("10.016"),
        )
        passed, errors, checkable, uncheckable = validate_tier1_lines([line])
        assert passed is False
        assert len(errors) >= 1
        assert "math" in errors[0].lower() or "line" in errors[0].lower() or "exceed" in errors[0].lower()

    def test_tier1_fractional_weight_goods_scaling(self):
        """Weighted items (e.g. 1.25 lb @ $3.99/lb): tolerance scales with qty."""
        # 1.25 * 3.99 = 4.9875.
        # Tolerance: 0.01 + 0.005 * 1.25 = 0.01625.
        # line_total printed as 4.99 -> diff = |4.9875 - 4.99| = 0.0025 <= 0.01625 (PASS)
        # line_total printed as 4.98 -> diff = |4.9875 - 4.98| = 0.0075 <= 0.01625 (PASS)
        # line_total adversarial 5.01 -> diff = |4.9875 - 5.01| = 0.0225 > 0.01625 (FAIL)
        line_valid = CanonicalLineItem(
            item_name="Bulk Cheese",
            qty=Decimal("1.25"),
            unit_price=Decimal("3.99"),
            line_total=Decimal("4.99"),
        )
        passed, errors, _, _ = validate_tier1_lines([line_valid])
        assert passed is True

        line_attack = CanonicalLineItem(
            item_name="Bulk Cheese Tampered",
            qty=Decimal("1.25"),
            unit_price=Decimal("3.99"),
            line_total=Decimal("5.01"),
        )
        passed, errors, _, _ = validate_tier1_lines([line_attack])
        assert passed is False
        assert len(errors) >= 1

    def test_tier1_large_quantity_accumulated_rounding_attack(self):
        """Large quantity (qty = 500): tolerance scales up to accommodate unit roundoff."""
        # qty = 500, unit_price = 3.33 -> product = 1665.00
        # tolerance = 0.01 + 0.005 * 500 = 2.51.
        # Discrepancy of 2.50: PASS.
        # Discrepancy of 2.52: FAIL.
        line_pass = CanonicalLineItem(
            item_name="Wholesale Rice",
            qty=Decimal("500"),
            unit_price=Decimal("3.33"),
            line_total=Decimal("1667.50"),  # diff = 2.50 <= 2.51
        )
        passed, _, _, _ = validate_tier1_lines([line_pass])
        assert passed is True

        line_fail = CanonicalLineItem(
            item_name="Wholesale Rice Tampered",
            qty=Decimal("500"),
            unit_price=Decimal("3.33"),
            line_total=Decimal("1667.52"),  # diff = 2.52 > 2.51
        )
        passed, errors, _, _ = validate_tier1_lines([line_fail])
        assert passed is False

    def test_tier2_subtotal_tolerance_boundary(self):
        """Tier 2: |sum(line_total) - subtotal| <= 0.02 + 0.005 * line_count."""
        # 10 lines of 10.00 = 100.00. Tolerance = 0.02 + 0.005 * 10 = 0.07.
        lines = [
            CanonicalLineItem(item_name=f"Item {i}", line_total=Decimal("10.00"))
            for i in range(10)
        ]

        # Subtotal 100.07 -> diff 0.07 <= 0.07 -> PASS
        inv_pass = CanonicalInvoice(
            source_file="f.pdf", source_sha256="h",
            subtotal=Decimal("100.07"), line_items=lines
        )
        is_consistent, errors = validate_tier2_subtotal(inv_pass)
        assert is_consistent is True

        # Subtotal 100.08 -> diff 0.08 > 0.07 -> FAIL
        inv_fail = CanonicalInvoice(
            source_file="f.pdf", source_sha256="h",
            subtotal=Decimal("100.08"), line_items=lines
        )
        is_consistent, errors = validate_tier2_subtotal(inv_fail)
        assert is_consistent is False
        assert len(errors) >= 1

    def test_tier3_grand_total_strict_002_boundary(self):
        """Tier 3: |subtotal + tax + shipping + tip + fees - discount - grand_total| <= 0.02."""
        # subtotal 100, tax 10 -> expected 110.00. Tolerance is fixed at 0.02.
        # grand_total = 110.02 -> diff 0.02 -> PASS
        inv_pass = CanonicalInvoice(
            source_file="f.pdf", source_sha256="h",
            subtotal=Decimal("100.00"), tax=Decimal("10.00"), grand_total=Decimal("110.02")
        )
        passed, errors = validate_tier3_grand_total(inv_pass)
        assert passed is True

        # grand_total = 110.03 -> diff 0.03 > 0.02 -> FAIL
        inv_fail = CanonicalInvoice(
            source_file="f.pdf", source_sha256="h",
            subtotal=Decimal("100.00"), tax=Decimal("10.00"), grand_total=Decimal("110.03")
        )
        passed, errors = validate_tier3_grand_total(inv_fail)
        assert passed is False
        assert len(errors) >= 1


# =====================================================================
# 3. Negative Number Formats Attacks
# =====================================================================

class TestNegativeFormatAttacks:
    """Attacks targeting negative representations: (12.50), 12.50-, 12.50 CR, --12.50."""

    @pytest.mark.parametrize("raw_input,expected", [
        ("(12.50)", Decimal("-12.50")),
        ("( 12.50 )", Decimal("-12.50")),
        ("($12.50)", Decimal("-12.50")),
        ("($1,234.56)", Decimal("-1234.56")),
        (" (45.00) ", Decimal("-45.00")),
    ])
    def test_parentheses_negative_parsing(self, raw_input: str, expected: Decimal):
        """Parenthesized numbers must parse into negative Decimal."""
        assert parse_number(raw_input) == expected

    @pytest.mark.parametrize("raw_input,expected", [
        ("12.50-", Decimal("-12.50")),
        ("12.50 -", Decimal("-12.50")),
        ("$12.50-", Decimal("-12.50")),
        ("1,234.56-", Decimal("-1234.56")),
        ("99.99 -", Decimal("-99.99")),
    ])
    def test_trailing_minus_negative_parsing(self, raw_input: str, expected: Decimal):
        """Trailing minus sign must parse into negative Decimal."""
        assert parse_number(raw_input) == expected

    @pytest.mark.parametrize("raw_input,expected", [
        ("12.50 CR", Decimal("-12.50")),
        ("12.50CR", Decimal("-12.50")),
        ("12.50 cr", Decimal("-12.50")),
        ("$12.50 CR", Decimal("-12.50")),
        ("1,234.56 CR", Decimal("-1234.56")),
    ])
    def test_credit_suffix_cr_negative_parsing(self, raw_input: str, expected: Decimal):
        """Accounting credit 'CR' suffix must parse into negative Decimal."""
        assert parse_number(raw_input) == expected

    @pytest.mark.parametrize("malformed_input", [
        "--12.50",       # Double leading minus
        "-12.50-",       # Leading and trailing minus
        "-(12.50)",      # Leading minus with parentheses
        "(12.50)-",      # Parentheses with trailing minus
        "(12.50) CR",    # Parentheses with CR
        "-12.50 CR",     # Leading minus with CR
        "12.50--",       # Double trailing minus
        "12.50 CR CR",   # Repeated CR
    ])
    def test_adversarial_double_negative_rejected(self, malformed_input: str):
        """Adversarial double negatives must be rejected with ValueError, NOT silently become positive."""
        with pytest.raises(ValueError):
            parse_number(malformed_input)

    def test_neg_hint_vault_flag_interaction(self):
        """neg_hint=True from vault must yield negative Decimal without double negation."""
        # Unsigned number with neg_hint
        assert parse_number("12.50", neg_hint=True) == Decimal("-12.50")

        # Explicitly negative number with neg_hint must remain negative, not become positive
        assert parse_number("-12.50", neg_hint=True) == Decimal("-12.50")
        assert parse_number("(12.50)", neg_hint=True) == Decimal("-12.50")
        assert parse_number("12.50-", neg_hint=True) == Decimal("-12.50")
        assert parse_number("12.50 CR", neg_hint=True) == Decimal("-12.50")

    def test_discount_subtraction_adversarial_sign_flip(self):
        """Tier 3: Discounts reduce grand_total; negative discount attack must not add."""
        # subtotal = 100, discount = 10, tax = 0 -> grand_total = 90.00
        inv_normal = CanonicalInvoice(
            source_file="f.pdf", source_sha256="h",
            subtotal=Decimal("100.00"), discount=Decimal("10.00"), grand_total=Decimal("90.00")
        )
        passed, _ = validate_tier3_grand_total(inv_normal)
        assert passed is True

        # Adversarial attack: grand_total = 110.00 attempting to treat discount as positive addition
        inv_add_attack = CanonicalInvoice(
            source_file="f.pdf", source_sha256="h",
            subtotal=Decimal("100.00"), discount=Decimal("10.00"), grand_total=Decimal("110.00")
        )
        passed, errors = validate_tier3_grand_total(inv_add_attack)
        assert passed is False


# =====================================================================
# 4. Inverted and Ambiguous Locales Attacks
# =====================================================================

class TestLocaleInversionAttacks:
    """Attacks using EU/VN ('1.234,56') vs US ('1,234.56') and ambiguous numbers ('1,234')."""

    def test_us_locale_standard_parsing(self):
        """US locale: comma thousands, dot decimal."""
        assert parse_number("1,234.56", document_locale="US") == Decimal("1234.56")
        assert parse_number("12,345,678.90", document_locale="US") == Decimal("12345678.90")
        assert parse_number("$99.95", document_locale="US") == Decimal("99.95")

    def test_eu_vn_locale_inverted_parsing(self):
        """EU/VN locale: dot thousands, comma decimal."""
        assert parse_number("1.234,56", document_locale="EU_VN") == Decimal("1234.56")
        assert parse_number("12.345.678,90", document_locale="EU_VN") == Decimal("12345678.90")
        assert parse_number("99,95 €", document_locale="EU_VN") == Decimal("99.95")

    def test_document_locale_detection_us_dominant(self):
        """Detect US locale from unambiguous US numbers."""
        sample_us = ["$1,234.56", "$50.00", "3.99", "25.50"]
        assert detect_document_locale(sample_us) == "US"

    def test_document_locale_detection_eu_vn_dominant(self):
        """Detect EU/VN locale from unambiguous EU/VN numbers."""
        sample_eu = ["1.234,56 €", "50,00", "3,99", "12.000,00"]
        assert detect_document_locale(sample_eu) == "EU_VN"

    def test_ambiguous_number_without_locale_raises_error(self):
        """'1,234' has 1 comma and 3 digits: ambiguous without locale, must raise AmbiguousNumberError."""
        with pytest.raises(AmbiguousNumberError):
            parse_number("1,234", document_locale=None)

        with pytest.raises(AmbiguousNumberError):
            parse_number("1.234", document_locale=None)

    def test_ambiguous_number_resolved_by_document_locale(self):
        """'1,234' resolved unambiguously when document_locale context is supplied."""
        # Under US: comma is thousands separator -> 1234
        assert parse_number("1,234", document_locale="US") == Decimal("1234")
        # Under EU_VN: comma is decimal separator -> 1.234
        assert parse_number("1,234", document_locale="EU_VN") == Decimal("1.234")

        # Under US: dot is decimal separator -> 1.234
        assert parse_number("1.234", document_locale="US") == Decimal("1.234")
        # Under EU_VN: dot is thousands separator -> 1234
        assert parse_number("1.234", document_locale="EU_VN") == Decimal("1234")

    def test_conflicting_locales_in_same_document_attack(self):
        """Adversarial batch mixing '1.234,56' and '1,234.56' in same document."""
        # A document cannot have both valid US and EU_VN formats simultaneously
        conflicting_texts = ["1.234,56", "1,234.56"]
        # Locale detection should either identify ambiguity or raise an error
        try:
            detected = detect_document_locale(conflicting_texts)
            # If it defaults, applying that locale to the conflicting format must fail
            if detected == "US":
                with pytest.raises((ValueError, AmbiguousNumberError)):
                    parse_number("1.234,56", document_locale="US")
            elif detected == "EU_VN":
                with pytest.raises((ValueError, AmbiguousNumberError)):
                    parse_number("1,234.56", document_locale="EU_VN")
        except (AmbiguousNumberError, ValueError):
            # Also acceptable to fail early during locale detection
            pass


# =====================================================================
# 5. Quantity & Total Edge Cases: Zero, Negative, Division by Zero
# =====================================================================

class TestZeroAndNegativeQuantityAttacks:
    """Attacks with zero quantity, negative quantities, zero totals, and division by zero."""

    def test_division_by_zero_safety_zero_quantity(self):
        """Line items with qty=0 must not trigger DivisionByZero or ZeroDivisionError."""
        # Free promotional item or warranty line: qty=0, unit_price=0, line_total=0
        line_free = CanonicalLineItem(
            item_name="Free Sample",
            qty=Decimal("0"),
            unit_price=Decimal("0.00"),
            line_total=Decimal("0.00"),
        )
        passed, errors, checkable, _ = validate_tier1_lines([line_free])
        assert passed is True
        assert len(errors) == 0

    def test_division_by_zero_safety_missing_unit_price_zero_qty(self):
        """When unit_price is None and qty is 0, validator must handle uncheckable line safely."""
        line_uncheckable = CanonicalLineItem(
            item_name="Service Credit Note",
            qty=Decimal("0"),
            unit_price=None,
            line_total=Decimal("0.00"),
        )
        # Must not raise ZeroDivisionError trying to compute unit_price = line_total / qty
        passed, errors, checkable, uncheckable = validate_tier1_lines([line_uncheckable])
        assert uncheckable == 1
        assert len(errors) == 0

    def test_negative_quantity_with_positive_line_total_attack(self):
        """qty = -2 with unit_price = 10.00 and line_total = +20.00 is math error."""
        line_attack = CanonicalLineItem(
            item_name="Returned Goods Math Tamper",
            qty=Decimal("-2"),
            unit_price=Decimal("10.00"),
            line_total=Decimal("20.00"),  # (-2 * 10) = -20 != +20
        )
        passed, errors, checkable, _ = validate_tier1_lines([line_attack])
        assert passed is False
        assert len(errors) >= 1

    def test_negative_quantity_with_negative_line_total_valid_return(self):
        """Valid return: qty = -2, unit_price = 10.00, line_total = -20.00 must pass."""
        line_return = CanonicalLineItem(
            item_name="Returned Milk",
            qty=Decimal("-2"),
            unit_price=Decimal("10.00"),
            line_total=Decimal("-20.00"),
        )
        passed, errors, checkable, _ = validate_tier1_lines([line_return])
        assert passed is True
        assert len(errors) == 0

    def test_both_negative_qty_and_negative_price_attack(self):
        """qty = -2 and unit_price = -10.00 results in +20.00 math product.

        If line_total is set to -20.00, math check must fail.
        """
        line_double_neg = CanonicalLineItem(
            item_name="Adversarial Double Neg Line",
            qty=Decimal("-2"),
            unit_price=Decimal("-10.00"),
            line_total=Decimal("-20.00"),  # (-2 * -10 = +20 != -20)
        )
        passed, errors, checkable, _ = validate_tier1_lines([line_double_neg])
        assert passed is False
        assert len(errors) >= 1

    def test_zero_grand_total_regular_invoice_flags_review(self):
        """Regular GOODS_INVOICE with grand_total = 0.00 must be flagged for review."""
        inv_zero = CanonicalInvoice(
            source_file="zero.pdf",
            source_sha256="h00",
            doc_type=DocType.GOODS_INVOICE,
            subtotal=Decimal("0.00"),
            grand_total=Decimal("0.00"),
            invoice_date="2026-08-01",
            due_date="2026-08-15",
        )
        reasons = validate_dates_and_metadata(inv_zero, target_month="2026-08")
        assert any("grand_total" in r.lower() or "zero" in r.lower() or "> 0" in r for r in reasons), (
            f"Expected zero grand_total warning, got: {reasons}"
        )

    def test_negative_grand_total_regular_invoice_rejected(self):
        """Regular GOODS_INVOICE with negative grand_total must be flagged as an error."""
        inv_neg = CanonicalInvoice(
            source_file="neg.pdf",
            source_sha256="hneg",
            doc_type=DocType.GOODS_INVOICE,
            subtotal=Decimal("-50.00"),
            grand_total=Decimal("-50.00"),
            invoice_date="2026-08-01",
            due_date="2026-08-15",
        )
        reasons = validate_dates_and_metadata(inv_neg, target_month="2026-08")
        assert any("negative" in r.lower() or "grand_total" in r.lower() or "< 0" in r or "> 0" in r for r in reasons), (
            f"Expected negative grand_total error for GOODS_INVOICE, got: {reasons}"
        )


# =====================================================================
# 6. Credit Memo Special Rules
# =====================================================================

class TestCreditMemoAttacks:
    """Credit memo validation: negative grand total is VALID, unlike regular invoices."""

    def test_credit_memo_negative_grand_total_allowed_in_metadata(self):
        """DocType.CREDIT_MEMO with grand_total < 0 must NOT trigger metadata rejection."""
        credit_memo = CanonicalInvoice(
            source_file="credit_memo.pdf",
            source_sha256="c01",
            doc_type=DocType.CREDIT_MEMO,
            subtotal=Decimal("-150.00"),
            tax=Decimal("0.00"),
            grand_total=Decimal("-150.00"),
            invoice_date="2026-08-05",
            due_date="2026-08-05",
        )
        reasons = validate_dates_and_metadata(credit_memo, target_month="2026-08")
        # Must not complain about negative grand total
        assert not any("grand_total" in r.lower() and ("negative" in r.lower() or "> 0" in r) for r in reasons), (
            f"Credit memo must not be rejected for negative grand_total, got: {reasons}"
        )

    def test_credit_memo_negative_math_tier3_consistency(self):
        """Credit memo with all negative components must pass Tier 3 math."""
        # subtotal = -200.00, tax = -16.00, discount = 0, grand_total = -216.00
        # formula: subtotal + tax - discount - grand_total = -200 + (-16) - 0 - (-216) = 0 <= 0.02
        credit_memo = CanonicalInvoice(
            source_file="credit_memo_math.pdf",
            source_sha256="c02",
            doc_type=DocType.CREDIT_MEMO,
            subtotal=Decimal("-200.00"),
            tax=Decimal("-16.00"),
            grand_total=Decimal("-216.00"),
        )
        passed, errors = validate_tier3_grand_total(credit_memo)
        assert passed is True
        assert len(errors) == 0

    def test_credit_memo_tampered_math_rejected(self):
        """Credit memo with corrupted negative balance must still fail Tier 3 math check."""
        # subtotal = -200, tax = 0, grand_total = -150 -> diff = |-200 - (-150)| = 50.00 > 0.02
        tampered_memo = CanonicalInvoice(
            source_file="tampered_memo.pdf",
            source_sha256="c03",
            doc_type=DocType.CREDIT_MEMO,
            subtotal=Decimal("-200.00"),
            tax=Decimal("0.00"),
            grand_total=Decimal("-150.00"),
        )
        passed, errors = validate_tier3_grand_total(tampered_memo)
        assert passed is False
        assert len(errors) >= 1

    def test_credit_memo_vs_goods_invoice_sign_divergence(self):
        """A negative grand total fails for GOODS_INVOICE but passes for CREDIT_MEMO."""
        inv_goods = CanonicalInvoice(
            source_file="test.pdf",
            source_sha256="same_hash",
            doc_type=DocType.GOODS_INVOICE,
            subtotal=Decimal("-100.00"),
            grand_total=Decimal("-100.00"),
            invoice_date="2026-08-10",
            due_date="2026-08-20",
        )
        inv_credit = CanonicalInvoice(
            source_file="test.pdf",
            source_sha256="same_hash",
            doc_type=DocType.CREDIT_MEMO,
            subtotal=Decimal("-100.00"),
            grand_total=Decimal("-100.00"),
            invoice_date="2026-08-10",
            due_date="2026-08-20",
        )

        reasons_goods = validate_dates_and_metadata(inv_goods, target_month="2026-08")
        reasons_credit = validate_dates_and_metadata(inv_credit, target_month="2026-08")

        # GOODS_INVOICE must fail negative total check
        goods_neg_flag = any("grand_total" in r.lower() or "negative" in r.lower() or "> 0" in r for r in reasons_goods)
        # CREDIT_MEMO must pass negative total check
        credit_neg_flag = any("grand_total" in r.lower() or "negative" in r.lower() or "> 0" in r for r in reasons_credit)

        assert goods_neg_flag is True, f"GOODS_INVOICE must reject negative grand_total, reasons: {reasons_goods}"
        assert credit_neg_flag is False, f"CREDIT_MEMO must accept negative grand_total, reasons: {reasons_credit}"
