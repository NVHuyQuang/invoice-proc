"""Tests for core.numparse.

Covers PLAN 5.2 requirements:
- US locale and EU/VN locale parsing
- Parentheses negative, trailing minus, credit notation (CR), leading minus
- Tax flags stripped (T, F, TX, etc.)
- Currency symbols and codes stripped
- Ambiguous numbers (e.g. '1,234') raising AmbiguousNumberError without context
- Resolution of ambiguous numbers with explicit document_locale
- Strictly Decimal return types (never float)
- detect_document_locale function
- Edge cases and invalid input validation
"""

from decimal import Decimal
import pytest

from core.numparse import parse_number, detect_document_locale, AmbiguousNumberError


class TestUSLocaleParsing:
    """Tests for US numeric locale formatting (comma thousand, dot decimal)."""

    def test_standard_us_decimal(self):
        result = parse_number("1,234.56")
        assert result == Decimal("1234.56")
        assert isinstance(result, Decimal)
        assert not isinstance(result, float)

    def test_large_us_number(self):
        result = parse_number("1,234,567.89")
        assert result == Decimal("1234567.89")

    def test_us_with_explicit_locale(self):
        result = parse_number("1,234.56", document_locale="US")
        assert result == Decimal("1234.56")

    def test_simple_decimal_point(self):
        result = parse_number("12.50")
        assert result == Decimal("12.50")

    def test_small_decimal(self):
        result = parse_number("0.05")
        assert result == Decimal("0.05")


class TestEUVNLocaleParsing:
    """Tests for EU/VN numeric locale formatting (dot thousand, comma decimal)."""

    def test_standard_eu_vn_decimal(self):
        result = parse_number("1.234,56")
        assert result == Decimal("1234.56")
        assert isinstance(result, Decimal)
        assert not isinstance(result, float)

    def test_large_eu_vn_number(self):
        result = parse_number("1.234.567,89")
        assert result == Decimal("1234567.89")

    def test_eu_vn_with_explicit_locale(self):
        result = parse_number("1.234,56", document_locale="EU_VN")
        assert result == Decimal("1234.56")

    def test_simple_comma_decimal(self):
        result = parse_number("12,50")
        assert result == Decimal("12.50")

    def test_small_comma_decimal(self):
        result = parse_number("0,05")
        assert result == Decimal("0.05")


class TestNegativeFormats:
    """Tests for various negative number formats."""

    def test_parentheses_negative(self):
        result = parse_number("(12.50)")
        assert result == Decimal("-12.50")

    def test_parentheses_with_spaces(self):
        result = parse_number("( 12.50 )")
        assert result == Decimal("-12.50")

    def test_parentheses_with_currency(self):
        result = parse_number("($12.50)")
        assert result == Decimal("-12.50")

    def test_trailing_minus(self):
        result = parse_number("12.50-")
        assert result == Decimal("-12.50")

    def test_trailing_minus_with_spaces(self):
        result = parse_number("12.50 -")
        assert result == Decimal("-12.50")

    def test_credit_notation_suffix(self):
        result = parse_number("12.50 CR")
        assert result == Decimal("-12.50")

    def test_credit_notation_attached(self):
        result = parse_number("12.50CR")
        assert result == Decimal("-12.50")

    def test_credit_notation_prefix(self):
        result = parse_number("CR 12.50")
        assert result == Decimal("-12.50")

    def test_credit_notation_lowercase(self):
        result = parse_number("12.50 cr")
        assert result == Decimal("-12.50")

    def test_credit_word(self):
        result = parse_number("12.50 CREDIT")
        assert result == Decimal("-12.50")

    def test_leading_minus(self):
        result = parse_number("-12.50")
        assert result == Decimal("-12.50")

    def test_leading_minus_with_currency(self):
        result = parse_number("-$12.50")
        assert result == Decimal("-12.50")

    def test_currency_before_leading_minus(self):
        result = parse_number("$-12.50")
        assert result == Decimal("-12.50")

    def test_unicode_minus(self):
        result = parse_number("\u221212.50")
        assert result == Decimal("-12.50")

    def test_unicode_en_dash(self):
        result = parse_number("\u201312.50")
        assert result == Decimal("-12.50")

    def test_neg_hint_flag(self):
        result = parse_number("12.50", neg_hint=True)
        assert result == Decimal("-12.50")

    def test_neg_hint_with_already_negative(self):
        result = parse_number("-12.50", neg_hint=True)
        assert result == Decimal("-12.50")

    def test_negative_eu_vn_number(self):
        result = parse_number("(1.234,56)")
        assert result == Decimal("-1234.56")


class TestTaxFlags:
    """Tests for tax flags stripping (T, F, TX, etc.)."""

    def test_tax_flag_t_attached(self):
        result = parse_number("33.99T")
        assert result == Decimal("33.99")

    def test_tax_flag_t_spaced(self):
        result = parse_number("33.99 T")
        assert result == Decimal("33.99")

    def test_tax_flag_tx(self):
        result = parse_number("33.99TX")
        assert result == Decimal("33.99")

    def test_tax_flag_f_food(self):
        result = parse_number("33.99F")
        assert result == Decimal("33.99")

    def test_tax_flag_n_nontaxable(self):
        result = parse_number("33.99 N")
        assert result == Decimal("33.99")

    def test_tax_flag_with_trailing_minus(self):
        result = parse_number("33.99T-")
        assert result == Decimal("-33.99")

    def test_tax_flag_with_parentheses(self):
        result = parse_number("(33.99T)")
        assert result == Decimal("-33.99")


class TestCurrencyHandling:
    """Tests for stripping currency symbols and ISO codes."""

    def test_usd_symbol(self):
        result = parse_number("$12.50")
        assert result == Decimal("12.50")

    def test_usd_symbol_with_space(self):
        result = parse_number("$ 12.50")
        assert result == Decimal("12.50")

    def test_usd_code_suffix(self):
        result = parse_number("12.50 USD")
        assert result == Decimal("12.50")

    def test_usd_code_prefix(self):
        result = parse_number("USD 12.50")
        assert result == Decimal("12.50")

    def test_euro_symbol(self):
        result = parse_number("1.234,56 €")
        assert result == Decimal("1234.56")

    def test_euro_code(self):
        result = parse_number("1.234,56 EUR")
        assert result == Decimal("1234.56")

    def test_gbp_symbol(self):
        result = parse_number("£12.50")
        assert result == Decimal("12.50")

    def test_vnd_symbol(self):
        result = parse_number("50.000 ₫", document_locale="EU_VN")
        assert result == Decimal("50000")

    def test_vnd_code(self):
        result = parse_number("50.000 VND", document_locale="EU_VN")
        assert result == Decimal("50000")


class TestAmbiguityDetection:
    """Tests for ambiguity detection and resolution."""

    def test_ambiguous_thousands_comma_without_locale(self):
        with pytest.raises(AmbiguousNumberError):
            parse_number("1,234")

    def test_ambiguous_with_currency_without_locale(self):
        with pytest.raises(AmbiguousNumberError):
            parse_number("$1,234")

    def test_ambiguous_larger_thousands_without_locale(self):
        with pytest.raises(AmbiguousNumberError):
            parse_number("123,456")

    def test_ambiguous_parenthesized_without_locale(self):
        with pytest.raises(AmbiguousNumberError):
            parse_number("(1,234)")

    def test_ambiguous_resolved_as_us(self):
        result = parse_number("1,234", document_locale="US")
        assert result == Decimal("1234")

    def test_ambiguous_resolved_as_eu_vn(self):
        result = parse_number("1,234", document_locale="EU_VN")
        assert result == Decimal("1.234")

    def test_unambiguous_multiple_commas(self):
        result = parse_number("1,234,567")
        assert result == Decimal("1234567")

    def test_unambiguous_multiple_dots(self):
        result = parse_number("1.234.567")
        assert result == Decimal("1234567")

    def test_single_dot_three_decimals_us(self):
        result = parse_number("1.234", document_locale="US")
        assert result == Decimal("1.234")

    def test_single_dot_three_digits_eu_vn(self):
        result = parse_number("1.234", document_locale="EU_VN")
        assert result == Decimal("1234")


class TestDetectDocumentLocale:
    """Tests for document-wide numeric locale detection."""

    def test_detect_eu_vn_with_thousands_dot_comma(self):
        texts = ["Item 1", "1.234,56", "Total", "5.678,90"]
        assert detect_document_locale(texts) == "EU_VN"

    def test_detect_us_with_thousands_comma_dot(self):
        texts = ["Item 1", "1,234.56", "Total", "5,678.90"]
        assert detect_document_locale(texts) == "US"

    def test_detect_eu_vn_with_currency_signal(self):
        texts = ["Total", "50.000 VND", "Phí", "10.000 ₫"]
        assert detect_document_locale(texts) == "EU_VN"

    def test_detect_eu_vn_with_euro_and_comma_decimal(self):
        texts = ["Dinner", "12,50 €", "Wine", "25,00 €"]
        assert detect_document_locale(texts) == "EU_VN"

    def test_detect_default_us_for_empty_list(self):
        assert detect_document_locale([]) == "US"

    def test_detect_default_us_for_standard_receipt(self):
        texts = ["$10.00", "$25.50", "$35.50"]
        assert detect_document_locale(texts) == "US"


class TestEdgeCasesAndValidation:
    """Tests for edge cases, error conditions, and zero values."""

    def test_zero_integer(self):
        result = parse_number("0")
        assert result == Decimal("0")

    def test_zero_decimal(self):
        result = parse_number("0.00")
        assert result == Decimal("0.00")

    def test_negative_zero(self):
        result = parse_number("(0.00)")
        assert result == Decimal("0.00")

    def test_credit_zero(self):
        result = parse_number("0.00 CR")
        assert result == Decimal("0.00")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_number("")

    def test_whitespace_only_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_number("   ")

    def test_none_input_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_number(None)  # type: ignore[arg-type]

    def test_non_string_input_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_number(123)  # type: ignore[arg-type]

    def test_non_numeric_text_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_number("INVALID")

    def test_bare_currency_symbol_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_number("$")

    def test_invalid_locale_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_number("10.00", document_locale="UNKNOWN")

    def test_invalid_comma_grouping_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_number("1,23,45")

    def test_strictly_decimal_never_float(self):
        for raw in ["12.50", "1,234.56", "(100.00)", "33.99T", "0"]:
            res = parse_number(raw)
            assert isinstance(res, Decimal)
            assert not isinstance(res, float)
