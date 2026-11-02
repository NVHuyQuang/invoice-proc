"""Prompt construction and few-shot examples module.

PLAN 4.2:
- PROMPT_VERSION constant.
- System prompt and few-shot examples for structured token-only extraction.
- Few-shots cover:
  1. Standard goods invoice with line items.
  2. Utility bill with charges, previous balance, payments, no qty*price.
  3. Receipt with discounts and negative values (<N_k:neg>).
- Invariant: Prompt text contains ZERO real financial digits (only token patterns).
"""

import json
from typing import Optional, Dict, Any, List

from config import PROMPT_VERSION, Category
from models.schema import DocType, LineItemKind

__all__ = [
    "PROMPT_VERSION",
    "build_system_prompt",
    "build_user_message",
    "FEW_SHOT_EXAMPLES",
]


# ---------------------------------------------------------------------------
# Few-shot anonymous examples
# Invariant: ZERO real financial digits outside token syntax <N_k>, <D_k>, <ID_k>.
# ---------------------------------------------------------------------------

FEW_SHOT_GOODS_INVOICE_TEXT = """ACME WHOLESALE FOODS
INVOICE: <ID_1>
DATE: <D_1>
DUE DATE: <D_2>

DESCRIPTION | QTY | UNIT PRICE | TOTAL
Organic Whole Milk | <N_1> | <N_2> | <N_3>
Grade A Eggs Large | <N_4> | <N_5> | <N_6>

SUBTOTAL: <N_7>
TAX: <N_8>
GRAND TOTAL: <N_9>
AMOUNT DUE: <N_10>"""

FEW_SHOT_GOODS_INVOICE_OUTPUT: Dict[str, Any] = {
    "doc_type": DocType.GOODS_INVOICE.value,
    "vendor_name": "ACME WHOLESALE FOODS",
    "invoice_no_ref": "<ID_1>",
    "invoice_date_ref": "<D_1>",
    "due_date_ref": "<D_2>",
    "currency": "$",
    "category": Category.FOOD_INGREDIENTS.value,
    "line_items": [
        {
            "item_name": "Organic Whole Milk",
            "qty_ref": "<N_1>",
            "unit_price_ref": "<N_2>",
            "line_total_ref": "<N_3>",
            "unit": None,
            "extra_refs": {},
            "kind": LineItemKind.GOODS.value,
        },
        {
            "item_name": "Grade A Eggs Large",
            "qty_ref": "<N_4>",
            "unit_price_ref": "<N_5>",
            "line_total_ref": "<N_6>",
            "unit": None,
            "extra_refs": {},
            "kind": LineItemKind.GOODS.value,
        },
    ],
    "charges": [],
    "summary": {
        "subtotal_ref": "<N_7>",
        "tax_ref": "<N_8>",
        "discount_ref": None,
        "shipping_ref": None,
        "tip_ref": None,
        "fees_ref": [],
        "grand_total_ref": "<N_9>",
        "amount_due_ref": "<N_10>",
    },
    "unassigned": [],
}


FEW_SHOT_UTILITY_BILL_TEXT = """CON EDISON OF NEW YORK
ACCOUNT NUMBER: <ID_11>
BILLING DATE: <D_3>
PAYMENT DUE DATE: <D_4>

ACCOUNT SUMMARY:
Previous Balance: <N_11>
Payment Received - Thank You: <N_12:neg>
Balance Forward: <N_13>

CURRENT CHARGES:
Electricity Supply Services: <N_14>
Electricity Delivery Services: <N_15>
Gas Supply Services: <N_16>
Gas Delivery Services: <N_17>
State and Local Taxes: <N_18>

Total Current Charges: <N_19>
Total Amount Due: <N_20>"""

FEW_SHOT_UTILITY_BILL_OUTPUT: Dict[str, Any] = {
    "doc_type": DocType.UTILITY_BILL.value,
    "vendor_name": "CON EDISON OF NEW YORK",
    "invoice_no_ref": "<ID_11>",
    "invoice_date_ref": "<D_3>",
    "due_date_ref": "<D_4>",
    "currency": "$",
    "category": Category.UTILITIES.value,
    "line_items": [],
    "charges": [
        {
            "description": "Previous Balance",
            "amount_ref": "<N_11>",
        },
        {
            "description": "Payment Received - Thank You",
            "amount_ref": "<N_12:neg>",
        },
        {
            "description": "Electricity Supply Services",
            "amount_ref": "<N_14>",
        },
        {
            "description": "Electricity Delivery Services",
            "amount_ref": "<N_15>",
        },
        {
            "description": "Gas Supply Services",
            "amount_ref": "<N_16>",
        },
        {
            "description": "Gas Delivery Services",
            "amount_ref": "<N_17>",
        },
    ],
    "summary": {
        "subtotal_ref": None,
        "tax_ref": "<N_18>",
        "discount_ref": None,
        "shipping_ref": None,
        "tip_ref": None,
        "fees_ref": [],
        "grand_total_ref": "<N_19>",
        "amount_due_ref": "<N_20>",
    },
    "unassigned": ["<N_13>"],
}


FEW_SHOT_DISCOUNT_INVOICE_TEXT = """METRO PACKAGING SOLUTIONS
INVOICE NUMBER: <ID_21>
INVOICE DATE: <D_5>
PAYMENT DUE BY: <D_6>

ITEMS:
Cardboard Shipping Boxes | Qty: <N_21> | Unit Price: <N_22> | Total: <N_23>
Volume Promotional Discount | Total: <N_24:neg>

Subtotal: <N_25>
Early Payment Discount: <N_26:neg>
Shipping and Handling: <N_27>
Sales Tax: <N_28>
Grand Total: <N_29>
Amount Due: <N_30>
Customer Loyalty Points: <N_31>"""

FEW_SHOT_DISCOUNT_INVOICE_OUTPUT: Dict[str, Any] = {
    "doc_type": DocType.GOODS_INVOICE.value,
    "vendor_name": "METRO PACKAGING SOLUTIONS",
    "invoice_no_ref": "<ID_21>",
    "invoice_date_ref": "<D_5>",
    "due_date_ref": "<D_6>",
    "currency": "$",
    "category": Category.PACKAGING.value,
    "line_items": [
        {
            "item_name": "Cardboard Shipping Boxes",
            "qty_ref": "<N_21>",
            "unit_price_ref": "<N_22>",
            "line_total_ref": "<N_23>",
            "unit": None,
            "extra_refs": {},
            "kind": LineItemKind.GOODS.value,
        },
        {
            "item_name": "Volume Promotional Discount",
            "qty_ref": None,
            "unit_price_ref": None,
            "line_total_ref": "<N_24:neg>",
            "unit": None,
            "extra_refs": {},
            "kind": LineItemKind.DISCOUNT.value,
        },
    ],
    "charges": [],
    "summary": {
        "subtotal_ref": "<N_25>",
        "tax_ref": "<N_28>",
        "discount_ref": "<N_26:neg>",
        "shipping_ref": "<N_27>",
        "tip_ref": None,
        "fees_ref": [],
        "grand_total_ref": "<N_29>",
        "amount_due_ref": "<N_30>",
    },
    "unassigned": ["<N_31>"],
}


FEW_SHOT_EXAMPLES: List[Dict[str, Any]] = [
    {
        "title": "HÓA ĐƠN HÀNG HÓA TIÊU CHUẨN (CÓ LINE ITEMS VÀ SUBTOTAL/TAX/TOTAL)",
        "input": FEW_SHOT_GOODS_INVOICE_TEXT,
        "output": FEW_SHOT_GOODS_INVOICE_OUTPUT,
    },
    {
        "title": "HÓA ĐƠN TIỆN ÍCH (UTILITY BILL: CON EDISON, CÓ CHARGES VÀ PAYMENTS, KHÔNG CÓ SỐ LƯỢNG VÀ ĐƠN GIÁ)",
        "input": FEW_SHOT_UTILITY_BILL_TEXT,
        "output": FEW_SHOT_UTILITY_BILL_OUTPUT,
    },
    {
        "title": "HÓA ĐƠN CÓ CHIẾT KHẤU VÀ SỐ ÂM (DISCOUNT VÀ GIÁ TRỊ ÂM)",
        "input": FEW_SHOT_DISCOUNT_INVOICE_TEXT,
        "output": FEW_SHOT_DISCOUNT_INVOICE_OUTPUT,
    },
]


def _format_few_shot_section() -> str:
    """Format few-shot examples into string without introducing non-token digits."""
    parts = []
    for ex in FEW_SHOT_EXAMPLES:
        header = f"--- {ex['title']} ---"
        input_part = f"VĂN BẢN ĐÃ CHE:\n{ex['input']}"
        json_str = json.dumps(ex["output"], indent=2, ensure_ascii=False)
        output_part = f"KẾT QUẢ JSON MẪU:\n{json_str}"
        parts.append(f"{header}\n\n{input_part}\n\n{output_part}")
    return "\n\n".join(parts)


def build_system_prompt() -> str:
    """Construct system prompt instructing LLM to extract token references only.

    Strict Invariant:
    The returned prompt text contains ZERO real financial digits. All digits
    must strictly belong to token placeholders (<N_k>, <D_k>, <ID_k>, <N_k:neg>).
    """
    categories_list = "\n".join(f'- "{cat.value}"' for cat in Category)
    few_shots_text = _format_few_shot_section()

    instructions = (
        "Bạn là trợ lý AI chuyên gia trích xuất cấu trúc dữ liệu hóa đơn tài chính.\n\n"
        "Văn bản đầu vào đã được che (mask) toàn bộ số và thông tin định danh bằng các token sau:\n"
        "- <N_k>: Số (tiền, số lượng, đơn giá, thuế, tổng cộng, phụ phí).\n"
        "- <D_k>: Ngày tháng (ngày hóa đơn, ngày đến hạn, kỳ thanh toán).\n"
        "- <ID_k>: Định danh (số hóa đơn, số tài khoản, mã khách hàng, số đơn hàng).\n"
        "- <N_k:neg>: Số âm (chiết khấu, giảm giá, hoàn tiền, thanh toán đã nhận).\n\n"
        "BẤT BIẾN BẮT BUỘC:\n"
        "- Bạn chỉ được tham chiếu token theo đúng tên định danh (ví dụ: <N_k>, <D_k>, <ID_k>, <N_k:neg>).\n"
        "- Tuyệt đối KHÔNG viết ra bất kỳ con số thật nào, không suy luận giá trị số học.\n"
        "- Mỗi token số chỉ được sử dụng tối đa một lần trong các trường số.\n"
        "- Nếu không chắc chắn vai trò của một token, hãy gán null cho trường đó và thêm token vào danh sách unassigned.\n"
        "- Mọi trường có hậu tố _ref chỉ nhận chuỗi token hoặc null.\n\n"
        "PHÂN LOẠI CHI PHÍ (category):\n"
        "Chỉ được chọn một trong các giá trị đóng sau:\n"
        f"{categories_list}\n"
        f'Nếu chi phí không nằm rõ ràng trong danh sách trên, bắt buộc chọn "{Category.OTHER.value}".\n\n'
        "LOẠI TÀI LIỆU (doc_type):\n"
        '- "goods_invoice": Hóa đơn mua bán hàng hóa tiêu chuẩn có danh sách mặt hàng.\n'
        '- "receipt": Biên lai thanh toán bán lẻ.\n'
        '- "utility_bill": Hóa đơn dịch vụ tiện ích như điện nước khí đốt (ví dụ: Con Edison).\n'
        '- "credit_memo": Giấy báo có điều chỉnh giảm tiền.\n'
        '- "statement": Bảng sao kê tài khoản.\n'
        '- "other": Tài liệu khác.\n\n'
        "QUY TẮC CẤU TRÚC HÓA ĐƠN:\n"
        '- Hóa đơn hàng hóa có danh sách mặt hàng: Điền vào line_items với item_name, qty_ref, '
        'unit_price_ref, line_total_ref, unit, extra_refs, kind ("goods", "fee", "discount", '
        '"tax_line", "deposit", "shipping"). Trường charges để mảng rỗng.\n'
        "- Hóa đơn tiện ích (utility_bill: Con Edison) không có số lượng nhân đơn giá: Điền vào charges "
        "với description và amount_ref cho từng khoản phí (bao gồm Previous Balance, Payments Received, "
        "phí dịch vụ điện khí). Trường line_items để mảng rỗng.\n"
        '- Hóa đơn có chiết khấu và số âm: Mặt hàng chiết khấu trong line_items có kind là "discount" và '
        "line_total_ref tham chiếu token số âm (<N_k:neg>). Khoản chiết khấu tổng được đưa vào discount_ref trong summary.\n\n"
        "ĐỊNH DẠNG ĐẦU RA:\n"
        "Trả về duy nhất đối tượng JSON hợp lệ tuân thủ schema LLMInvoice, không kèm lời giải thích hay markdown bọc ngoài.\n\n"
        "VÍ DỤ MẪU (FEW-SHOT EXAMPLES):\n\n"
        f"{few_shots_text}"
    )

    return instructions


# Bind PROMPT_VERSION to build_system_prompt
build_system_prompt.prompt_version = PROMPT_VERSION


def build_user_message(masked_document_text: str) -> str:
    """Format user prompt payload with masked document text."""
    return (
        "Trích xuất thông tin hóa đơn từ văn bản đã được che (masked) dưới đây.\n"
        "Chỉ sử dụng tham chiếu token (<N_k>, <D_k>, <ID_k>, <N_k:neg>), tuyệt đối không điền số thật.\n"
        "Trả về duy nhất đối tượng JSON theo schema LLMInvoice.\n\n"
        f"--- BẮT ĐẦU VĂN BẢN ---\n{masked_document_text}\n--- KẾT THÚC VĂN BẢN ---"
    )
