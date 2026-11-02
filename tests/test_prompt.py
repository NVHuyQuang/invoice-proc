"""Tests for core/prompt.py.

Verifies:
1. Strict invariant: Prompt contains ZERO real financial digits outside token syntax.
2. Few-shot examples validity against LLMInvoice schema.
3. Prompt binding with PROMPT_VERSION and Category from config.py.
4. Snapshot test for deterministic prompt generation.
"""

import hashlib
import json
import re
from typing import List, Set

import pytest

import config
from config import PROMPT_VERSION, Category
from core.prompt import (
    build_system_prompt,
    build_user_message,
    FEW_SHOT_EXAMPLES,
)
from models.schema import DocType, LineItemKind, LLMInvoice, TOKEN_REF_PATTERN


# Pattern to identify valid tokens in prompt text
TOKEN_REGEX = re.compile(r"<(?:N|D|ID)_\d+(?::neg)?>")
TOKEN_PARAM_PLACEHOLDER_REGEX = re.compile(r"<(?:N|D|ID)_k(?::neg)?>")


def test_prompt_version_contract():
    """Verify prompt module strictly binds PROMPT_VERSION from config."""
    import core.prompt as prompt_mod

    assert hasattr(prompt_mod, "PROMPT_VERSION"), "core.prompt must expose PROMPT_VERSION"
    assert prompt_mod.PROMPT_VERSION == PROMPT_VERSION
    assert getattr(build_system_prompt, "prompt_version", None) == PROMPT_VERSION
    assert isinstance(PROMPT_VERSION, str)
    assert len(PROMPT_VERSION.strip()) > 0


def test_system_prompt_contains_zero_digits_outside_tokens():
    """BẤT BIẾN: Prompt tuyệt đối KHÔNG chứa bất kỳ chữ số tài chính nào.

    Every digit in build_system_prompt() must be part of a valid token (<N_k>, <D_k>, <ID_k>, <N_k:neg>).
    """
    prompt = build_system_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 0

    # Strip all valid tokens
    stripped = TOKEN_REGEX.sub("", prompt)

    # Any remaining digits constitute a strict invariant violation
    remaining_digits = re.findall(r"\d", stripped)
    assert not remaining_digits, (
        f"Prompt invariant violated! Found digits outside token references: {remaining_digits}\n"
        f"Context around leaks: {[line for line in stripped.splitlines() if any(c.isdigit() for c in line)]}"
    )


def test_user_message_contains_zero_digits_outside_tokens():
    """Verify build_user_message template contains no digits outside tokens."""
    empty_msg = build_user_message("")
    stripped = TOKEN_REGEX.sub("", empty_msg)
    assert not re.findall(r"\d", stripped)

    sample_doc = "ITEM | QTY <N_1> | PRICE <N_2> | TOTAL <N_3>"
    rendered = build_user_message(sample_doc)
    stripped_rendered = TOKEN_REGEX.sub("", rendered)
    assert not re.findall(r"\d", stripped_rendered)


def test_all_tokens_conform_to_schema_pattern():
    """Verify all token instances in prompt match TOKEN_REF_PATTERN."""
    prompt = build_system_prompt()
    tokens = TOKEN_REGEX.findall(prompt)
    assert len(tokens) > 0, "Prompt must contain token references"

    for tok in tokens:
        assert TOKEN_REF_PATTERN.match(tok), f"Token {tok} does not match TOKEN_REF_PATTERN"


def test_few_shot_examples_count_and_types():
    """Verify exactly 3 required few-shot types are present in FEW_SHOT_EXAMPLES."""
    assert len(FEW_SHOT_EXAMPLES) == 3

    titles = [ex["title"] for ex in FEW_SHOT_EXAMPLES]
    # 1. Standard goods invoice
    assert any("HÀNG HÓA" in t for t in titles)
    # 2. Utility bill (Con Edison)
    assert any("CON EDISON" in t for t in titles)
    # 3. Discount and negative values
    assert any("CHIẾT KHẤU" in t or "DISCOUNT" in t for t in titles)


def test_few_shot_one_goods_invoice_validates_schema():
    """Few-shot 1: Standard goods invoice with line items, subtotal, tax, grand total."""
    ex1 = FEW_SHOT_EXAMPLES[0]["output"]
    validated = LLMInvoice.model_validate(ex1)

    assert validated.doc_type == DocType.GOODS_INVOICE
    assert validated.category == Category.FOOD_INGREDIENTS
    assert validated.vendor_name == "ACME WHOLESALE FOODS"
    assert validated.invoice_no_ref == "<ID_1>"
    assert validated.invoice_date_ref == "<D_1>"
    assert validated.due_date_ref == "<D_2>"
    assert len(validated.line_items) == 2
    assert validated.charges == []
    assert validated.summary.subtotal_ref == "<N_7>"
    assert validated.summary.tax_ref == "<N_8>"
    assert validated.summary.grand_total_ref == "<N_9>"
    assert validated.summary.amount_due_ref == "<N_10>"

    for item in validated.line_items:
        assert item.kind == LineItemKind.GOODS
        assert item.qty_ref is not None
        assert item.unit_price_ref is not None
        assert item.line_total_ref is not None


def test_few_shot_two_utility_bill_validates_schema():
    """Few-shot 2: Utility bill (Con Edison) with charges, payments, previous balance, no qty*price."""
    ex2 = FEW_SHOT_EXAMPLES[1]["output"]
    validated = LLMInvoice.model_validate(ex2)

    assert validated.doc_type == DocType.UTILITY_BILL
    assert validated.category == Category.UTILITIES
    assert "CON EDISON" in (validated.vendor_name or "")
    assert validated.invoice_no_ref == "<ID_11>"
    assert validated.invoice_date_ref == "<D_3>"
    assert validated.due_date_ref == "<D_4>"
    assert validated.line_items == []  # No qty*price items
    assert len(validated.charges) > 0
    assert validated.summary.subtotal_ref is None
    assert validated.summary.amount_due_ref == "<N_20>"

    # Check for previous balance, payment received (negative), and unassigned
    charge_descs = [c.description for c in validated.charges]
    assert any("Previous Balance" in d for d in charge_descs)
    assert any("Payment Received" in d for d in charge_descs)

    neg_charge = next(c for c in validated.charges if "Payment Received" in c.description)
    assert neg_charge.amount_ref == "<N_12:neg>"
    assert "<N_13>" in validated.unassigned


def test_few_shot_three_discount_and_negatives_validates_schema():
    """Few-shot 3: Invoice with discount line item and negative token values."""
    ex3 = FEW_SHOT_EXAMPLES[2]["output"]
    validated = LLMInvoice.model_validate(ex3)

    assert validated.doc_type == DocType.GOODS_INVOICE
    assert validated.category == Category.PACKAGING
    assert len(validated.line_items) == 2

    # Check discount line item
    discount_line = next(item for item in validated.line_items if item.kind == LineItemKind.DISCOUNT)
    assert discount_line.line_total_ref == "<N_24:neg>"
    assert discount_line.qty_ref is None
    assert discount_line.unit_price_ref is None

    # Check summary discount
    assert validated.summary.discount_ref == "<N_26:neg>"
    assert validated.summary.subtotal_ref == "<N_25>"
    assert validated.summary.grand_total_ref == "<N_29>"
    assert validated.summary.amount_due_ref == "<N_30>"
    assert "<N_31>" in validated.unassigned


def test_few_shot_token_uniqueness_per_example():
    """Verify no token is reused within numeric fields of any single few-shot example."""
    for idx, ex in enumerate(FEW_SHOT_EXAMPLES):
        output = ex["output"]
        tokens_seen: List[str] = []

        # Header refs
        for ref_field in ["invoice_no_ref", "invoice_date_ref", "due_date_ref"]:
            val = output.get(ref_field)
            if val:
                tokens_seen.append(val)

        # Line items
        for item in output.get("line_items", []):
            for ref_field in ["qty_ref", "unit_price_ref", "line_total_ref"]:
                val = item.get(ref_field)
                if val:
                    tokens_seen.append(val)

        # Charges
        for charge in output.get("charges", []):
            val = charge.get("amount_ref")
            if val:
                tokens_seen.append(val)

        # Summary
        summary = output.get("summary", {})
        for ref_field in [
            "subtotal_ref", "tax_ref", "discount_ref", "shipping_ref",
            "tip_ref", "grand_total_ref", "amount_due_ref"
        ]:
            val = summary.get(ref_field)
            if val:
                tokens_seen.append(val)
        for fee_ref in summary.get("fees_ref", []):
            tokens_seen.append(fee_ref)

        # Unassigned
        for tok in output.get("unassigned", []):
            tokens_seen.append(tok)

        # Check uniqueness
        duplicates = [tok for tok in tokens_seen if tokens_seen.count(tok) > 1]
        assert not duplicates, (
            f"Few-shot example {idx} ({ex['title']}) reuses tokens: {set(duplicates)}"
        )


def test_closed_category_enum_in_prompt():
    """Verify all closed Category enum values from config.py are explicitly listed."""
    prompt = build_system_prompt()
    for cat in Category:
        assert f'"{cat.value}"' in prompt, f"Category '{cat.value}' missing from system prompt"


def test_snapshot_system_prompt():
    """Snapshot test ensuring system prompt content is deterministic and stable."""
    prompt = build_system_prompt()
    # Compute sha256 fingerprint of the prompt
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    # Verify structural sections are all present
    assert "Bạn là trợ lý AI chuyên gia trích xuất cấu trúc dữ liệu hóa đơn tài chính." in prompt
    assert "BẤT BIẾN BẮT BUỘC:" in prompt
    assert "PHÂN LOẠI CHI PHÍ (category):" in prompt
    assert "LOẠI TÀI LIỆU (doc_type):" in prompt
    assert "QUY TẮC CẤU TRÚC HÓA ĐƠN:" in prompt
    assert "ĐỊNH DẠNG ĐẦU RA:" in prompt
    assert "VÍ DỤ MẪU (FEW-SHOT EXAMPLES):" in prompt
    assert "ACME WHOLESALE FOODS" in prompt
    assert "CON EDISON OF NEW YORK" in prompt
    assert "METRO PACKAGING SOLUTIONS" in prompt

    # Verify deterministic reproducibility: two successive calls produce identical text
    assert prompt == build_system_prompt()
    assert hashlib.sha256(build_system_prompt().encode("utf-8")).hexdigest() == prompt_hash


def test_build_user_message_structure():
    """Verify user message properly frames masked document text with delimiters."""
    doc_text = "DUMMY_MASKED_PAYLOAD_CONTENT"
    msg = build_user_message(doc_text)

    assert "--- BẮT ĐẦU VĂN BẢN ---" in msg
    assert "--- KẾT THÚC VĂN BẢN ---" in msg
    assert doc_text in msg
    assert "LLMInvoice" in msg
