"""Tests for core/rehydrator.py.

PLAN 5.1, 5.3:
Test cases:
- Token ma (ghost / unknown tokens)
- Token trùng (duplicate tokens in numeric fields)
- Token bỏ rơi (orphan money tokens coverage)
- Số thật trong ref (real numeric characters in _ref fields)
- Ngày mơ hồ (ambiguous dates vs unambiguous dates)
- Low confidence flagging (< 0.90)
- Provenance propagation
- Number parsing (locales, negative formats, tax flags)
"""

from decimal import Decimal
import pytest

from core.types import Vault, VaultEntry, Provenance
from models.schema import (
    LLMInvoice,
    LLMLineItem,
    LLMCharge,
    LLMSummary,
    CanonicalInvoice,
    DocType,
    LineItemKind,
    Category,
)
from core.rehydrator import (
    verify_llm_tokens,
    rehydrate_invoice,
    TokenVerificationError,
    _parse_decimal,
    _parse_date,
)


def create_vault_entry(
    token: str,
    raw: str,
    kind: str = "number",
    conf: float = 0.99,
    page: int = 1,
    bbox: tuple = (10.0, 20.0, 50.0, 30.0),
    neg_hint: bool = False,
) -> VaultEntry:
    return VaultEntry(
        token=token,
        raw=raw,
        kind=kind,
        page=page,
        bbox=bbox,
        conf=conf,
        neg_hint=neg_hint,
    )


def test_happy_path_verification():
    vault = Vault()
    vault.add(create_vault_entry("<ID_1>", "INV-2026-001", kind="id"))
    vault.add(create_vault_entry("<D_1>", "2026-08-01", kind="date"))
    vault.add(create_vault_entry("<N_1>", "2", kind="number"))
    vault.add(create_vault_entry("<N_2>", "15.00", kind="money"))
    vault.add(create_vault_entry("<N_3>", "30.00", kind="money"))
    vault.add(create_vault_entry("<N_4>", "30.00", kind="money"))

    llm_invoice = LLMInvoice(
        vendor_name="Acme Corp",
        invoice_no_ref="<ID_1>",
        invoice_date_ref="<D_1>",
        line_items=[
            LLMLineItem(
                item_name="Widget",
                qty_ref="<N_1>",
                unit_price_ref="<N_2>",
                line_total_ref="<N_3>",
            )
        ],
        summary=LLMSummary(
            grand_total_ref="<N_4>",
        ),
    )

    is_valid, issues = verify_llm_tokens(llm_invoice, vault)
    assert is_valid is True
    assert issues == []


def test_ghost_token_unknown_token():
    """Token ma: Token không có trong vault phải bị đánh dấu 'unknown_token'."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "100.00", kind="money"))

    # <N_999> does not exist in vault
    llm_invoice = LLMInvoice(
        summary=LLMSummary(
            subtotal_ref="<N_1>",
            grand_total_ref="<N_999>",
        )
    )

    is_valid, issues = verify_llm_tokens(llm_invoice, vault)
    assert is_valid is False
    assert "unknown_token" in issues

    # When rehydrated, 'unknown_token' appears in review_reasons
    canonical = rehydrate_invoice(llm_invoice, vault, "test.pdf", "dummy_sha")
    assert "unknown_token" in canonical.review_reasons
    assert canonical.grand_total is None
    assert canonical.grand_total_prov is None


def test_duplicate_token_in_numeric_fields():
    """Trùng token: Mỗi token chỉ được dùng 1 lần trong các trường số."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "50.00", kind="money"))

    # Reuse <N_1> in both subtotal and grand_total
    llm_invoice = LLMInvoice(
        summary=LLMSummary(
            subtotal_ref="<N_1>",
            grand_total_ref="<N_1>",
        )
    )

    is_valid, issues = verify_llm_tokens(llm_invoice, vault)
    assert is_valid is False
    assert "duplicate_token" in issues


def test_duplicate_token_with_neg_modifier():
    """Trùng token: <N_1> và <N_1:neg> là cùng một token và bị coi là trùng nếu dùng nhiều lần."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "10.00", kind="money"))

    llm_invoice = LLMInvoice(
        summary=LLMSummary(
            subtotal_ref="<N_1>",
            discount_ref="<N_1:neg>",
        )
    )

    is_valid, issues = verify_llm_tokens(llm_invoice, vault)
    assert is_valid is False
    assert "duplicate_token" in issues


def test_duplicate_token_numeric_and_unassigned():
    """Trùng token: Token đã dùng ở trường số không được nằm trong unassigned."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "50.00", kind="money"))

    llm_invoice = LLMInvoice(
        summary=LLMSummary(
            grand_total_ref="<N_1>",
        ),
        unassigned=["<N_1>"],
    )

    is_valid, issues = verify_llm_tokens(llm_invoice, vault)
    assert is_valid is False
    assert "duplicate_token" in issues


def test_orphan_money_tokens_coverage():
    """Bỏ rơi token: Mọi token kiểu tiền trong vault phải nằm trong trường số hoặc unassigned."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "10.00", kind="money"))
    vault.add(create_vault_entry("<N_2>", "20.00", kind="money"))  # Orphan!
    vault.add(create_vault_entry("<N_3>", "5", kind="number"))  # Not money, can be omitted

    llm_invoice = LLMInvoice(
        summary=LLMSummary(
            grand_total_ref="<N_1>",
        )
    )

    is_valid, issues = verify_llm_tokens(llm_invoice, vault)
    assert is_valid is False
    assert "orphan_money_tokens" in issues

    # If unassigned lists <N_2>, coverage passes
    llm_invoice_covered = LLMInvoice(
        summary=LLMSummary(
            grand_total_ref="<N_1>",
        ),
        unassigned=["<N_2>"],
    )
    is_valid2, issues2 = verify_llm_tokens(llm_invoice_covered, vault)
    assert is_valid2 is True
    assert "orphan_money_tokens" not in issues2


@pytest.mark.parametrize(
    "bad_ref",
    [
        "123.45",
        "$50.00",
        "100",
        "<N_12.50>",
        "10.00 CR",
        "(25.00)",
    ],
)
def test_real_number_in_summary_ref_raises_verification_error(bad_ref):
    """Số thật trong ref: Ném TokenVerificationError khi trường _ref chứa số thật."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "100.00", kind="money"))

    # Bypass Pydantic field validator via model_construct to simulate invalid output
    bad_summary = LLMSummary.model_construct(
        subtotal_ref="<N_1>",
        grand_total_ref=bad_ref,
    )
    llm_invoice = LLMInvoice.model_construct(summary=bad_summary)

    with pytest.raises(TokenVerificationError):
        verify_llm_tokens(llm_invoice, vault)

    with pytest.raises(TokenVerificationError):
        rehydrate_invoice(llm_invoice, vault, "file.pdf", "dummy_hash")


def test_real_number_in_extra_refs_raises_error():
    """Số thật trong ref: extra_refs chứa số thật phải ném TokenVerificationError."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "10.00", kind="money"))

    llm_invoice = LLMInvoice(
        line_items=[
            LLMLineItem(
                item_name="Item A",
                extra_refs={"ordered": "5.00"},  # Real number in extra_refs
            )
        ],
        summary=LLMSummary(grand_total_ref="<N_1>"),
    )

    with pytest.raises(TokenVerificationError):
        verify_llm_tokens(llm_invoice, vault)


def test_real_number_in_unassigned_raises_error():
    """Số thật trong unassigned phải ném TokenVerificationError."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "10.00", kind="money"))

    llm_invoice = LLMInvoice(
        summary=LLMSummary(grand_total_ref="<N_1>"),
        unassigned=["12.50"],
    )

    with pytest.raises(TokenVerificationError):
        verify_llm_tokens(llm_invoice, vault)


def test_ambiguous_date_detection():
    """Ngày mơ hồ: Ngày như 03/04/2026 đánh dấu 'ambiguous_date' và parse theo locale mặc định."""
    vault = Vault()
    vault.add(create_vault_entry("<D_1>", "03/04/2026", kind="date"))
    vault.add(create_vault_entry("<N_1>", "100.00", kind="money"))

    llm_invoice = LLMInvoice(
        invoice_date_ref="<D_1>",
        summary=LLMSummary(grand_total_ref="<N_1>"),
    )

    canonical = rehydrate_invoice(llm_invoice, vault, "inv.pdf", "hash123")
    assert "ambiguous_date" in canonical.review_reasons
    # DEFAULT_DATE_LOCALE is "MM/DD", so Month=03, Day=04
    assert canonical.invoice_date == "2026-03-04"


def test_unambiguous_dates():
    """Ngày không mơ hồ: 08/25/2026, 25/08/2026, 2026-08-01, Aug 15, 2026 không bị gắn cờ."""
    vault = Vault()
    vault.add(create_vault_entry("<D_1>", "08/25/2026", kind="date"))
    vault.add(create_vault_entry("<D_2>", "25/08/2026", kind="date"))
    vault.add(create_vault_entry("<D_3>", "2026-08-01", kind="date"))
    vault.add(create_vault_entry("<D_4>", "August 15, 2026", kind="date"))
    vault.add(create_vault_entry("<D_5>", "05/05/2026", kind="date"))
    vault.add(create_vault_entry("<N_1>", "10.00", kind="money"))

    for d_token, expected_iso in [
        ("<D_1>", "2026-08-25"),
        ("<D_2>", "2026-08-25"),
        ("<D_3>", "2026-08-01"),
        ("<D_4>", "2026-08-15"),
        ("<D_5>", "2026-05-05"),
    ]:
        llm_invoice = LLMInvoice(
            invoice_date_ref=d_token,
            summary=LLMSummary(grand_total_ref="<N_1>"),
        )
        canonical = rehydrate_invoice(llm_invoice, vault, "inv.pdf", "hash123")
        assert "ambiguous_date" not in canonical.review_reasons
        assert canonical.invoice_date == expected_iso


def test_low_confidence_flag():
    """Gắn cờ low_conf nếu conf < 0.90."""
    vault = Vault()
    # 0.85 < 0.90
    vault.add(create_vault_entry("<N_1>", "50.00", kind="money", conf=0.85))

    llm_invoice = LLMInvoice(
        summary=LLMSummary(grand_total_ref="<N_1>"),
    )

    canonical = rehydrate_invoice(llm_invoice, vault, "inv.pdf", "hash123")
    assert "low_conf" in canonical.review_reasons

    # conf >= 0.90 should not flag low_conf
    vault_high = Vault()
    vault_high.add(create_vault_entry("<N_1>", "50.00", kind="money", conf=0.92))
    canonical_high = rehydrate_invoice(llm_invoice, vault_high, "inv.pdf", "hash123")
    assert "low_conf" not in canonical_high.review_reasons


def test_provenance_propagation():
    """Gắn Provenance từ vault vào CanonicalInvoice."""
    vault = Vault()
    vault.add(create_vault_entry("<ID_1>", "INV-999", kind="id", conf=1.0, page=1, bbox=(1, 2, 3, 4)))
    vault.add(create_vault_entry("<D_1>", "2026-08-01", kind="date", conf=0.95, page=1, bbox=(5, 6, 7, 8)))
    vault.add(create_vault_entry("<N_1>", "2.5", kind="number", conf=0.98, page=2, bbox=(9, 10, 11, 12)))
    vault.add(create_vault_entry("<N_2>", "10.00", kind="money", conf=0.97, page=2, bbox=(13, 14, 15, 16)))
    vault.add(create_vault_entry("<N_3>", "25.00", kind="money", conf=0.96, page=2, bbox=(17, 18, 19, 20)))
    vault.add(create_vault_entry("<N_4>", "25.00", kind="money", conf=0.99, page=2, bbox=(21, 22, 23, 24)))

    llm_invoice = LLMInvoice(
        invoice_no_ref="<ID_1>",
        invoice_date_ref="<D_1>",
        line_items=[
            LLMLineItem(
                item_name="Steak",
                qty_ref="<N_1>",
                unit_price_ref="<N_2>",
                line_total_ref="<N_3>",
            )
        ],
        summary=LLMSummary(grand_total_ref="<N_4>"),
    )

    canonical = rehydrate_invoice(llm_invoice, vault, "doc.pdf", "sha999")

    assert canonical.invoice_no == "INV-999"
    assert canonical.invoice_no_prov == Provenance(page=1, bbox=(1, 2, 3, 4), ocr_conf=1.0, source="pdf_text")

    assert canonical.invoice_date == "2026-08-01"
    assert canonical.invoice_date_prov == Provenance(page=1, bbox=(5, 6, 7, 8), ocr_conf=0.95, source="ocr")

    assert len(canonical.line_items) == 1
    item = canonical.line_items[0]
    assert item.qty == Decimal("2.5")
    assert item.qty_prov is not None
    assert item.qty_prov.page == 2
    assert item.unit_price == Decimal("10.00")
    assert item.line_total == Decimal("25.00")
    assert item.checkable is True

    assert canonical.grand_total == Decimal("25.00")
    assert canonical.grand_total_prov is not None
    assert canonical.grand_total_prov.bbox == (21, 22, 23, 24)


def test_number_parsing_variations():
    """Kiểm tra các biến thể định dạng số: âm ngoặc, trừ sau, CR, thuế T/F, locale US vs EU."""
    # Parenthesized negative
    assert _parse_decimal("(12.50)") == Decimal("-12.50")
    # Trailing minus
    assert _parse_decimal("12.50-") == Decimal("-12.50")
    # Leading minus
    assert _parse_decimal("-12.50") == Decimal("-12.50")
    # CR
    assert _parse_decimal("12.50 CR") == Decimal("-12.50")
    assert _parse_decimal("12.50CR") == Decimal("-12.50")
    # Currency symbols and codes
    assert _parse_decimal("$12.50") == Decimal("12.50")
    assert _parse_decimal("12.50 USD") == Decimal("12.50")
    assert _parse_decimal("€ 1,234.56") == Decimal("1234.56")
    # Tax flags
    assert _parse_decimal("33.99T") == Decimal("33.99")
    assert _parse_decimal("33.99 F") == Decimal("33.99")
    # neg_hint
    assert _parse_decimal("15.00", neg_hint=True) == Decimal("-15.00")
    # Locales
    assert _parse_decimal("1,234.56") == Decimal("1234.56")
    assert _parse_decimal("1.234,56") == Decimal("1234.56")
    assert _parse_decimal("12,50") == Decimal("12.50")
    assert _parse_decimal("1,234", locale="US") == Decimal("1234")


def test_rehydrate_charges_and_fees():
    """Rehydrate utility charges và summary fees."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "120.50", kind="money"))
    vault.add(create_vault_entry("<N_2>", "15.00", kind="money"))
    vault.add(create_vault_entry("<N_3>", "5.00", kind="money"))
    vault.add(create_vault_entry("<N_4>", "140.50", kind="money"))

    llm_invoice = LLMInvoice(
        doc_type=DocType.UTILITY_BILL,
        charges=[
            LLMCharge(description="Electricity Delivery", amount_ref="<N_1>"),
            LLMCharge(description="Clean Energy Surcharge", amount_ref="<N_2>"),
        ],
        summary=LLMSummary(
            fees_ref=["<N_3>"],
            amount_due_ref="<N_4>",
        ),
    )

    canonical = rehydrate_invoice(llm_invoice, vault, "util.pdf", "sha_util")

    assert canonical.doc_type == DocType.UTILITY_BILL
    assert len(canonical.charges) == 2
    assert canonical.charges[0].amount == Decimal("120.50")
    assert canonical.charges[1].amount == Decimal("15.00")
    assert canonical.fees == [Decimal("5.00")]
    assert canonical.amount_due == Decimal("140.50")
    assert canonical.review_reasons == []


def test_vault_invariants_no_repr_leak():
    """Invariants: __repr__ và __str__ của Vault không bao giờ lộ raw values."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "$999,999.99", kind="money"))
    assert "$999,999.99" not in repr(vault)
    assert "$999,999.99" not in str(vault)


def test_ambiguous_date_with_custom_locale():
    """Ngày mơ hồ với DD/MM locale: 03/04/2026 thành 2026-04-03."""
    vault = Vault()
    vault.add(create_vault_entry("<D_1>", "03/04/2026", kind="date"))
    vault.add(create_vault_entry("<N_1>", "10.00", kind="money"))

    llm_invoice = LLMInvoice(
        invoice_date_ref="<D_1>",
        summary=LLMSummary(grand_total_ref="<N_1>"),
    )

    canonical = rehydrate_invoice(llm_invoice, vault, "inv.pdf", "sha123", date_locale="DD/MM")
    assert "ambiguous_date" in canonical.review_reasons
    assert canonical.invoice_date == "2026-04-03"


def test_ambiguous_2digit_year_date():
    """Ngày 2 chữ số năm mơ hồ: 03/04/26 thành 2026-03-04."""
    vault = Vault()
    vault.add(create_vault_entry("<D_1>", "03/04/26", kind="date"))
    vault.add(create_vault_entry("<N_1>", "10.00", kind="money"))

    llm_invoice = LLMInvoice(
        invoice_date_ref="<D_1>",
        summary=LLMSummary(grand_total_ref="<N_1>"),
    )

    canonical = rehydrate_invoice(llm_invoice, vault, "inv.pdf", "sha123")
    assert "ambiguous_date" in canonical.review_reasons
    assert canonical.invoice_date == "2026-03-04"


def test_real_number_in_header_refs_raises_error():
    """Số thật trong invoice_no_ref hoặc invoice_date_ref ném TokenVerificationError."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "10.00", kind="money"))

    # Invoice no with real digits bypassing schema validation
    bad_inv_no = LLMInvoice.model_construct(
        invoice_no_ref="INV-2026",
        summary=LLMSummary(grand_total_ref="<N_1>"),
    )
    with pytest.raises(TokenVerificationError):
        verify_llm_tokens(bad_inv_no, vault)

    # Invoice date with real date string
    bad_inv_date = LLMInvoice.model_construct(
        invoice_date_ref="2026-08-01",
        summary=LLMSummary(grand_total_ref="<N_1>"),
    )
    with pytest.raises(TokenVerificationError):
        verify_llm_tokens(bad_inv_date, vault)


def test_line_item_checkable_logic():
    """Kiểm tra checkable của CanonicalLineItem: False nếu thiếu đơn giá hoặc kind không phải GOODS."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "10.00", kind="money"))
    vault.add(create_vault_entry("<N_2>", "-5.00", kind="money", neg_hint=True))
    vault.add(create_vault_entry("<N_3>", "5.00", kind="money"))

    llm_invoice = LLMInvoice(
        line_items=[
            # Goods missing qty and price
            LLMLineItem(
                item_name="Service charge",
                line_total_ref="<N_1>",
                kind=LineItemKind.GOODS,
            ),
            # Discount line
            LLMLineItem(
                item_name="Promo coupon",
                line_total_ref="<N_2>",
                kind=LineItemKind.DISCOUNT,
            ),
        ],
        summary=LLMSummary(grand_total_ref="<N_3>"),
    )

    canonical = rehydrate_invoice(llm_invoice, vault, "inv.pdf", "sha123")
    assert len(canonical.line_items) == 2
    assert canonical.line_items[0].checkable is False
    assert canonical.line_items[1].checkable is False
    assert canonical.line_items[1].line_total == Decimal("-5.00")


def test_rehydrate_invoice_detects_document_locale():
    """Gọi detect_document_locale trên các số trong document để truyền vào _parse_decimal."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "1.234,56", kind="money"))
    vault.add(create_vault_entry("<N_2>", "12,50", kind="money"))
    vault.add(create_vault_entry("<N_3>", "1.247,06", kind="money"))

    llm_invoice = LLMInvoice(
        line_items=[
            LLMLineItem(item_name="Item A", line_total_ref="<N_1>"),
            LLMLineItem(item_name="Item B", line_total_ref="<N_2>"),
        ],
        summary=LLMSummary(grand_total_ref="<N_3>"),
    )

    canonical = rehydrate_invoice(llm_invoice, vault, "inv.pdf", "sha123")
    assert canonical.line_items[0].line_total == Decimal("1234.56")
    assert canonical.line_items[1].line_total == Decimal("12.50")
    assert canonical.grand_total == Decimal("1247.06")


def test_ambiguous_number_propagates_to_review_reasons():
    """AmbiguousNumberError không bị nuốt mà propagate vào review_reasons."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "1,234", kind="number"))
    llm_invoice = LLMInvoice(
        summary=LLMSummary(grand_total_ref="<N_1>"),
    )

    # Calling with ambiguous number where locale cannot be inferred
    from unittest.mock import patch as mock_patch
    with mock_patch("core.rehydrator.detect_document_locale", return_value=None):
        canonical = rehydrate_invoice(llm_invoice, vault, "inv.pdf", "sha123")
        assert "ambiguous_number" in canonical.review_reasons
        assert canonical.grand_total is None


def test_parse_date_2digit_year_aug_28_26():
    """Sửa lỗi chọn năm 2 chữ số (Aug 28, 26 không lấy max nhầm thành 2028). Validate ngày bằng datetime.date."""
    from core.rehydrator import _parse_date

    iso_date, is_ambig = _parse_date("Aug 28, 26")
    assert iso_date == "2026-08-28"
    assert is_ambig is False

    iso_date, is_ambig = _parse_date("28 Aug 26")
    assert iso_date == "2026-08-28"
    assert is_ambig is False

    # Invalid date validation
    invalid_date, _ = _parse_date("Feb 30, 2026")
    assert invalid_date is None

    invalid_date2, _ = _parse_date("02/30/2026")
    assert invalid_date2 is None


def test_charge_amount_parse_failure_adds_review_reason():
    """Khi charge amount parse thất bại: không âm thầm gán Decimal('0') mà thêm lý do vào review_reasons."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "INVALID_NUM", kind="money"))

    llm_invoice = LLMInvoice(
        charges=[
            LLMCharge(description="Service Fee", amount_ref="<N_1>"),
        ],
    )

    canonical = rehydrate_invoice(llm_invoice, vault, "inv.pdf", "sha123")
    assert len(canonical.charges) == 1
    assert canonical.charges[0].amount == Decimal("0")
    assert any("charge" in r.lower() for r in canonical.review_reasons)


def test_duplicate_token_in_invoice_no_if_numeric():
    """Kiểm tra duplicate_token: kiểm tra cả invoice_no_ref nếu nó trỏ vào token kiểu số."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "12345", kind="number"))
    vault.add(create_vault_entry("<N_2>", "50.00", kind="money"))

    # invoice_no_ref points to <N_1>, which is also reused in grand_total_ref
    llm_invoice = LLMInvoice(
        invoice_no_ref="<N_1>",
        summary=LLMSummary(grand_total_ref="<N_1>"),
    )

    is_valid, issues = verify_llm_tokens(llm_invoice, vault)
    assert is_valid is False
    assert "duplicate_token" in issues


def test_orphan_money_tokens_decimal_format_without_currency_symbol():
    """orphan_money_tokens: kiểm tra cả các token số có định dạng tiền thập phân dù không có ký hiệu tiền tệ."""
    vault = Vault()
    vault.add(create_vault_entry("<N_1>", "10.00", kind="money"))
    # Token <N_2> has kind="number" (no currency symbol), but its format is decimal money "45.00"
    vault.add(create_vault_entry("<N_2>", "45.00", kind="number"))
    # Token <N_3> has kind="number" and is an integer quantity "5"
    vault.add(create_vault_entry("<N_3>", "5", kind="number"))

    llm_invoice = LLMInvoice(
        summary=LLMSummary(grand_total_ref="<N_1>"),
    )

    is_valid, issues = verify_llm_tokens(llm_invoice, vault)
    assert is_valid is False
    assert "orphan_money_tokens" in issues


