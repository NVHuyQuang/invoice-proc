"""Unit tests for core.tokenizer_numbers.

PLAN 3.3: Number and identifier tokenization test suite.
Verifies:
- Masking digit-bearing strings into deterministic sequential tokens <N_k> or <ID_k>.
- Negative hints (<N_k:neg>) for parenthesized, leading minus, trailing minus, and CR formats.
- Money formats ($33.99, 1,234.56, 1.234,56, EUR, VND, etc.).
- Quantities (1.25 lb, 2 @ 3.50, 3 x 4.00).
- Tax flags (33.99T, 33.99TX).
- Alphanumeric identifiers (INV-2026-0831, PO#12345, etc.).
- VaultEntry recording (raw, kind, page, bbox, conf, neg_hint).
- Preservation of existing tokens (<D_k>, <SPEC_k>, __SPEC_k__).
- Determinism across repeated runs.
"""

import pytest
from core.types import Vault, VaultEntry
from core.tokenizer_numbers import tokenize_numbers


def test_basic_single_integer():
    vault = Vault()
    text = "Quantity is 5 items."
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Quantity is <N_1> items."
    assert tokens == ["<N_1>"]
    assert len(vault) == 1
    entry = vault.get("<N_1>")
    assert entry is not None
    assert entry.raw == "5"
    assert entry.kind == "number"
    assert entry.neg_hint is False
    assert entry.page == 1


def test_basic_decimal_numbers():
    vault = Vault()
    text = "Values: 1.25 and 3.50 and 33.99"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Values: <N_1> and <N_2> and <N_3>"
    assert tokens == ["<N_1>", "<N_2>", "<N_3>"]
    assert len(vault) == 3
    assert vault["<N_1>"].raw == "1.25"
    assert vault["<N_2>"].raw == "3.50"
    assert vault["<N_3>"].raw == "33.99"
    assert all(not vault[t].neg_hint for t in tokens)


def test_money_dollar_format():
    vault = Vault()
    text = "Price is $33.99, discounted from $50.00"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Price is <N_1>, discounted from <N_2>"
    assert tokens == ["<N_1>", "<N_2>"]
    assert vault["<N_1>"].raw == "$33.99"
    assert vault["<N_1>"].kind == "money"
    assert vault["<N_1>"].neg_hint is False
    assert vault["<N_2>"].raw == "$50.00"
    assert vault["<N_2>"].kind == "money"


def test_money_other_currencies():
    vault = Vault()
    text = "Totals: €12.50, £45.00, ¥1000, 500,000₫, 500.000 đ, 100 USD"
    masked, tokens = tokenize_numbers(text, vault)

    assert tokens == ["<N_1>", "<N_2>", "<N_3>", "<N_4>", "<N_5>", "<N_6>"]
    assert vault["<N_1>"].raw == "€12.50"
    assert vault["<N_1>"].kind == "money"
    assert vault["<N_2>"].raw == "£45.00"
    assert vault["<N_2>"].kind == "money"
    assert vault["<N_3>"].raw == "¥1000"
    assert vault["<N_3>"].kind == "money"
    assert vault["<N_4>"].raw == "500,000₫"
    assert vault["<N_4>"].kind == "money"
    assert vault["<N_5>"].raw == "500.000 đ"
    assert vault["<N_5>"].kind == "money"
    assert vault["<N_6>"].raw == "100 USD"
    assert vault["<N_6>"].kind == "money"


def test_us_thousands_separator():
    vault = Vault()
    text = "Balance: 1,234.56 and 1,000,000.00"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Balance: <N_1> and <N_2>"
    assert tokens == ["<N_1>", "<N_2>"]
    assert vault["<N_1>"].raw == "1,234.56"
    assert vault["<N_2>"].raw == "1,000,000.00"


def test_eu_thousands_separator():
    vault = Vault()
    text = "Montant: 1.234,56 và 1.000.000,00"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Montant: <N_1> và <N_2>"
    assert tokens == ["<N_1>", "<N_2>"]
    assert vault["<N_1>"].raw == "1.234,56"
    assert vault["<N_2>"].raw == "1.000.000,00"


def test_negative_parentheses_plain():
    vault = Vault()
    text = "Discount: (12.50)"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Discount: <N_1:neg>"
    assert tokens == ["<N_1:neg>"]
    assert vault["<N_1:neg>"].raw == "(12.50)"
    assert vault["<N_1:neg>"].neg_hint is True


def test_negative_parentheses_with_dollar():
    vault = Vault()
    text = "Credit applied: ($12.50) and $(50.00)"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Credit applied: <N_1:neg> and <N_2:neg>"
    assert tokens == ["<N_1:neg>", "<N_2:neg>"]
    assert vault["<N_1:neg>"].raw == "($12.50)"
    assert vault["<N_1:neg>"].neg_hint is True
    assert vault["<N_1:neg>"].kind == "money"
    assert vault["<N_2:neg>"].raw == "$(50.00)"
    assert vault["<N_2:neg>"].neg_hint is True
    assert vault["<N_2:neg>"].kind == "money"


def test_negative_brackets():
    vault = Vault()
    text = "Adjustment: [12.50] and [$25.00]"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Adjustment: <N_1:neg> and <N_2:neg>"
    assert tokens == ["<N_1:neg>", "<N_2:neg>"]
    assert vault["<N_1:neg>"].raw == "[12.50]"
    assert vault["<N_1:neg>"].neg_hint is True
    assert vault["<N_2:neg>"].raw == "[$25.00]"
    assert vault["<N_2:neg>"].neg_hint is True


def test_negative_leading_minus():
    vault = Vault()
    text = "Adjustments: -12.50 and -$33.99 and $-5.00"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Adjustments: <N_1:neg> and <N_2:neg> and <N_3:neg>"
    assert tokens == ["<N_1:neg>", "<N_2:neg>", "<N_3:neg>"]
    assert vault["<N_1:neg>"].raw == "-12.50"
    assert vault["<N_1:neg>"].neg_hint is True
    assert vault["<N_2:neg>"].raw == "-$33.99"
    assert vault["<N_2:neg>"].neg_hint is True
    assert vault["<N_3:neg>"].raw == "$-5.00"
    assert vault["<N_3:neg>"].neg_hint is True


def test_negative_trailing_minus():
    vault = Vault()
    text = "Line items: 12.50- and $33.99- and 1,234.56-"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Line items: <N_1:neg> and <N_2:neg> and <N_3:neg>"
    assert tokens == ["<N_1:neg>", "<N_2:neg>", "<N_3:neg>"]
    assert vault["<N_1:neg>"].raw == "12.50-"
    assert vault["<N_1:neg>"].neg_hint is True
    assert vault["<N_2:neg>"].raw == "$33.99-"
    assert vault["<N_2:neg>"].neg_hint is True
    assert vault["<N_3:neg>"].raw == "1,234.56-"
    assert vault["<N_3:neg>"].neg_hint is True


def test_negative_trailing_cr():
    vault = Vault()
    text = "Balance: 12.50 CR and 12.50CR and $100.00 CR and 50.00 cr"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Balance: <N_1:neg> and <N_2:neg> and <N_3:neg> and <N_4:neg>"
    assert tokens == ["<N_1:neg>", "<N_2:neg>", "<N_3:neg>", "<N_4:neg>"]
    assert vault["<N_1:neg>"].raw == "12.50 CR"
    assert vault["<N_1:neg>"].neg_hint is True
    assert vault["<N_1:neg>"].kind == "money"
    assert vault["<N_2:neg>"].raw == "12.50CR"
    assert vault["<N_2:neg>"].neg_hint is True
    assert vault["<N_3:neg>"].raw == "$100.00 CR"
    assert vault["<N_3:neg>"].neg_hint is True
    assert vault["<N_4:neg>"].raw == "50.00 cr"
    assert vault["<N_4:neg>"].neg_hint is True


def test_tax_flag_formats():
    vault = Vault()
    text = "Taxable items: 33.99T, 10.50 T, 25.00TX, $100.00T"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Taxable items: <N_1>, <N_2>, <N_3>, <N_4>"
    assert tokens == ["<N_1>", "<N_2>", "<N_3>", "<N_4>"]
    assert vault["<N_1>"].raw == "33.99T"
    assert vault["<N_1>"].neg_hint is False
    assert vault["<N_2>"].raw == "10.50 T"
    assert vault["<N_3>"].raw == "25.00TX"
    assert vault["<N_4>"].raw == "$100.00T"


def test_quantity_with_unit():
    vault = Vault()
    text = "Ordered 1.25 lb apples, 10 pcs boxes, 0.5 kg beef"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Ordered <N_1> lb apples, <N_2> pcs boxes, <N_3> kg beef"
    assert tokens == ["<N_1>", "<N_2>", "<N_3>"]
    assert vault["<N_1>"].raw == "1.25"
    assert vault["<N_2>"].raw == "10"
    assert vault["<N_3>"].raw == "0.5"


def test_quantity_at_price():
    vault = Vault()
    text = "Item line: 2 @ 3.50"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Item line: <N_1> @ <N_2>"
    assert tokens == ["<N_1>", "<N_2>"]
    assert vault["<N_1>"].raw == "2"
    assert vault["<N_2>"].raw == "3.50"


def test_quantity_x_price():
    vault = Vault()
    text = "Item line: 3 x 4.00"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Item line: <N_1> x <N_2>"
    assert tokens == ["<N_1>", "<N_2>"]
    assert vault["<N_1>"].raw == "3"
    assert vault["<N_2>"].raw == "4.00"


def test_alphanumeric_id_standard():
    vault = Vault()
    text = "Invoice Number: INV-2026-0831"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Invoice Number: <ID_1>"
    assert tokens == ["<ID_1>"]
    assert len(vault) == 1
    entry = vault.get("<ID_1>")
    assert entry is not None
    assert entry.raw == "INV-2026-0831"
    assert entry.kind == "id"
    assert entry.neg_hint is False


def test_alphanumeric_id_variations():
    vault = Vault()
    text = "Refs: PO#12345, ACCT_9876, ORD/2026/01, AB1234, 1234-XYZ, REF:9876"
    masked, tokens = tokenize_numbers(text, vault)

    assert tokens == ["<ID_1>", "<ID_2>", "<ID_3>", "<ID_4>", "<ID_5>", "<ID_6>"]
    assert vault["<ID_1>"].raw == "PO#12345"
    assert vault["<ID_1>"].kind == "id"
    assert vault["<ID_2>"].raw == "ACCT_9876"
    assert vault["<ID_3>"].raw == "ORD/2026/01"
    assert vault["<ID_4>"].raw == "AB1234"
    assert vault["<ID_5>"].raw == "1234-XYZ"
    assert vault["<ID_6>"].raw == "REF:9876"


def test_mixed_id_and_numbers_sequence():
    vault = Vault()
    text = "Invoice INV-2026-0831 dated on line 1 total $100.00"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Invoice <ID_1> dated on line <N_2> total <N_3>"
    assert tokens == ["<ID_1>", "<N_2>", "<N_3>"]
    assert vault["<ID_1>"].raw == "INV-2026-0831"
    assert vault["<N_2>"].raw == "1"
    assert vault["<N_3>"].raw == "$100.00"


def test_preserve_existing_tokens():
    vault = Vault()
    text = "Date <D_1> for INV-2026-0831 with placeholder __SPEC_0__ and <SPEC_1> total $50.00"
    masked, tokens = tokenize_numbers(text, vault)

    assert "<D_1>" in masked
    assert "__SPEC_0__" in masked
    assert "<SPEC_1>" in masked
    assert tokens == ["<ID_1>", "<N_2>"]
    assert "<D_1>" not in vault
    assert "__SPEC_0__" not in vault
    assert "<SPEC_1>" not in vault
    assert vault["<ID_1>"].raw == "INV-2026-0831"
    assert vault["<N_2>"].raw == "$50.00"


def test_subtraction_operator_not_negative():
    vault = Vault()
    text = "Formula: 100.00 - 10.00 = 90.00"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Formula: <N_1> - <N_2> = <N_3>"
    assert tokens == ["<N_1>", "<N_2>", "<N_3>"]
    assert all(not vault[t].neg_hint for t in tokens)


def test_punctuation_boundaries():
    vault = Vault()
    text = "Total is $33.99. Subtotal is $100.00; Tax is $8.00! Items: 2, 3, 4."
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Total is <N_1>. Subtotal is <N_2>; Tax is <N_3>! Items: <N_4>, <N_5>, <N_6>."
    assert vault["<N_1>"].raw == "$33.99"
    assert vault["<N_2>"].raw == "$100.00"
    assert vault["<N_3>"].raw == "$8.00"
    assert vault["<N_4>"].raw == "2"
    assert vault["<N_5>"].raw == "3"
    assert vault["<N_6>"].raw == "4"


def test_parentheses_around_text_not_negative():
    vault = Vault()
    text = "Check note (see page 2) for details"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Check note (see page <N_1>) for details"
    assert tokens == ["<N_1>"]
    assert vault["<N_1>"].raw == "2"
    assert vault["<N_1>"].neg_hint is False


def test_parentheses_around_id_not_negative():
    vault = Vault()
    text = "Refer to (INV-2026-0831) on file"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Refer to (<ID_1>) on file"
    assert tokens == ["<ID_1>"]
    assert vault["<ID_1>"].raw == "INV-2026-0831"
    assert vault["<ID_1>"].neg_hint is False


def test_deterministic_stability():
    text = (
        "INV-2026-0831 line 1: 2 @ 3.50 = 7.00, discount (1.50), "
        "tax 33.99T, subtotal $1,234.56, fee 12.50 CR, net 12.50-"
    )
    vault1 = Vault()
    masked1, tokens1 = tokenize_numbers(text, vault1)

    vault2 = Vault()
    masked2, tokens2 = tokenize_numbers(text, vault2)

    assert masked1 == masked2
    assert tokens1 == tokens2
    assert len(vault1) == len(vault2)
    for t1, t2 in zip(tokens1, tokens2):
        assert vault1[t1].token == vault2[t2].token
        assert vault1[t1].raw == vault2[t2].raw
        assert vault1[t1].kind == vault2[t2].kind
        assert vault1[t1].neg_hint == vault2[t2].neg_hint


def test_start_index_continuity():
    vault = Vault()
    text = "Values: 10, 20, 30"
    masked, tokens = tokenize_numbers(text, vault, start_index=15)

    assert masked == "Values: <N_15>, <N_16>, <N_17>"
    assert tokens == ["<N_15>", "<N_16>", "<N_17>"]
    assert "<N_15>" in vault
    assert "<N_16>" in vault
    assert "<N_17>" in vault


def test_multi_page_tokenization():
    vault = Vault()
    page1_text = "Page 1: Subtotal $100.00"
    p1_masked, p1_tokens = tokenize_numbers(page1_text, vault, start_index=1, page=1)

    next_idx = 1 + len(p1_tokens)
    page2_text = "Page 2: Grand Total $100.00"
    p2_masked, p2_tokens = tokenize_numbers(page2_text, vault, start_index=next_idx, page=2)

    assert p1_tokens == ["<N_1>", "<N_2>"]
    assert p2_tokens == ["<N_3>", "<N_4>"]
    assert len(vault) == 4
    assert vault["<N_2>"].page == 1
    assert vault["<N_4>"].page == 2


def test_empty_and_no_digit_text():
    vault = Vault()
    masked, tokens = tokenize_numbers("", vault)
    assert masked == ""
    assert tokens == []
    assert len(vault) == 0

    text_no_digits = "Smith's Organic Butter - Fresh Daily Delivery"
    masked2, tokens2 = tokenize_numbers(text_no_digits, vault)
    assert masked2 == text_no_digits
    assert tokens2 == []
    assert len(vault) == 0


def test_zero_and_decimals_under_one():
    vault = Vault()
    text = "Values: 0, 0.00, .99, ,50, $.99, (0.00)"
    masked, tokens = tokenize_numbers(text, vault)

    assert tokens == ["<N_1>", "<N_2>", "<N_3>", "<N_4>", "<N_5>", "<N_6:neg>"]
    assert vault["<N_1>"].raw == "0"
    assert vault["<N_2>"].raw == "0.00"
    assert vault["<N_3>"].raw == ".99"
    assert vault["<N_4>"].raw == ",50"
    assert vault["<N_5>"].raw == "$.99"
    assert vault["<N_5>"].kind == "money"
    assert vault["<N_6:neg>"].raw == "(0.00)"
    assert vault["<N_6:neg>"].neg_hint is True


def test_hyphenated_number():
    vault = Vault()
    text = "Tracking: 555-123-4567"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Tracking: <N_1>"
    assert tokens == ["<N_1>"]
    assert vault["<N_1>"].raw == "555-123-4567"
    assert vault["<N_1>"].neg_hint is False


def test_vault_metadata_and_clear():
    vault = Vault()
    bbox = (10.0, 20.0, 30.0, 40.0)
    conf = 0.95
    masked, tokens = tokenize_numbers("Total: $12.50", vault, bbox=bbox, conf=conf)

    entry = vault["<N_1>"]
    assert entry.bbox == bbox
    assert entry.conf == conf
    assert len(vault) == 1

    vault.clear()
    assert len(vault) == 0


def test_negative_spaced_leading_minus():
    vault = Vault()
    text = "Adjustments: - 12.50 and - $33.99 and -5.00"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Adjustments: <N_1:neg> and <N_2:neg> and <N_3:neg>"
    assert tokens == ["<N_1:neg>", "<N_2:neg>", "<N_3:neg>"]
    assert vault["<N_1:neg>"].raw == "- 12.50"
    assert vault["<N_1:neg>"].neg_hint is True
    assert vault["<N_2:neg>"].raw == "- $33.99"
    assert vault["<N_2:neg>"].neg_hint is True
    assert vault["<N_3:neg>"].raw == "-5.00"
    assert vault["<N_3:neg>"].neg_hint is True


def test_negative_spaced_trailing_minus():
    vault = Vault()
    text = "Line items: 12.50 - and $33.99 - and 1,234.56 -"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Line items: <N_1:neg> and <N_2:neg> and <N_3:neg>"
    assert tokens == ["<N_1:neg>", "<N_2:neg>", "<N_3:neg>"]
    assert vault["<N_1:neg>"].raw == "12.50 -"
    assert vault["<N_1:neg>"].neg_hint is True
    assert vault["<N_2:neg>"].raw == "$33.99 -"
    assert vault["<N_2:neg>"].neg_hint is True
    assert vault["<N_3:neg>"].raw == "1,234.56 -"
    assert vault["<N_3:neg>"].neg_hint is True


def test_dr_credit_flag():
    vault = Vault()
    text = "Balance: 12.50 DR and 12.50DR and $100.00 DR and 50.00 dr"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Balance: <N_1:neg> and <N_2:neg> and <N_3:neg> and <N_4:neg>"
    assert tokens == ["<N_1:neg>", "<N_2:neg>", "<N_3:neg>", "<N_4:neg>"]
    assert vault["<N_1:neg>"].raw == "12.50 DR"
    assert vault["<N_1:neg>"].neg_hint is True
    assert vault["<N_1:neg>"].kind == "money"
    assert vault["<N_2:neg>"].raw == "12.50DR"
    assert vault["<N_2:neg>"].neg_hint is True
    assert vault["<N_3:neg>"].raw == "$100.00 DR"
    assert vault["<N_3:neg>"].neg_hint is True
    assert vault["<N_4:neg>"].raw == "50.00 dr"
    assert vault["<N_4:neg>"].neg_hint is True


def test_tax_flags_extended():
    vault = Vault()
    text = "Taxable items: 33.99F, 12.50N, 10.00E, 25.00 F, 15.00 N"
    masked, tokens = tokenize_numbers(text, vault)

    assert masked == "Taxable items: <N_1>, <N_2>, <N_3>, <N_4>, <N_5>"
    assert tokens == ["<N_1>", "<N_2>", "<N_3>", "<N_4>", "<N_5>"]
    assert vault["<N_1>"].raw == "33.99F"
    assert vault["<N_1>"].kind == "number"
    assert vault["<N_2>"].raw == "12.50N"
    assert vault["<N_3>"].raw == "10.00E"
    assert vault["<N_4>"].raw == "25.00 F"
    assert vault["<N_5>"].raw == "15.00 N"
    assert all("ID" not in t for t in tokens)


def test_tokenize_text_unicode_nfkc():
    from core.tokenizer import tokenize_text
    vault = Vault()
    text = "Items: 10² units, 1½ lb butter, price $12.50"
    masked, v = tokenize_text(text, vault=vault)

    # 10² becomes 102 under NFKC, 1½ becomes 1 1⁄2 or 11/2 under NFKC
    assert "²" not in masked
    assert "½" not in masked
    assert len(v) >= 3
