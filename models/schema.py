"""Pydantic schemas for LLM structured output and Canonical Invoice.

Frozen at Wave 0.
"""

from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
import re

from config import Category, SCHEMA_VERSION
from core.types import Provenance


class DocType(str, Enum):
    GOODS_INVOICE = "goods_invoice"
    RECEIPT = "receipt"
    UTILITY_BILL = "utility_bill"
    CREDIT_MEMO = "credit_memo"
    STATEMENT = "statement"
    OTHER = "other"


class LineItemKind(str, Enum):
    GOODS = "goods"
    FEE = "fee"
    DISCOUNT = "discount"
    TAX_LINE = "tax_line"
    DEPOSIT = "deposit"
    SHIPPING = "shipping"


class InvoiceStatus(str, Enum):
    VERIFIED = "VERIFIED"
    REVIEW_NEEDED = "REVIEW_NEEDED"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"


TOKEN_REF_PATTERN = re.compile(r"^<(?:N|D|ID)_\d+(?::neg)?>$")


def validate_token_ref(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if not TOKEN_REF_PATTERN.match(v):
        raise ValueError(f"Invalid token reference format: {v!r}. Must match <N_k>, <D_k>, <ID_k>, or <N_k:neg>")
    return v


# ---------------------------------------------------------
# LLM Output Schema (Tokens only, NO raw values)
# ---------------------------------------------------------

class LLMLineItem(BaseModel):
    item_name: str = ""
    qty_ref: Optional[str] = None
    unit_price_ref: Optional[str] = None
    line_total_ref: Optional[str] = None
    unit: Optional[str] = None
    extra_refs: Dict[str, str] = Field(default_factory=dict)
    kind: LineItemKind = LineItemKind.GOODS

    @field_validator("qty_ref", "unit_price_ref", "line_total_ref", mode="before")
    @classmethod
    def check_token_ref(cls, v: Optional[str]) -> Optional[str]:
        return validate_token_ref(v)


class LLMCharge(BaseModel):
    description: str = ""
    amount_ref: Optional[str] = None

    @field_validator("amount_ref", mode="before")
    @classmethod
    def check_token_ref(cls, v: Optional[str]) -> Optional[str]:
        return validate_token_ref(v)


class LLMSummary(BaseModel):
    subtotal_ref: Optional[str] = None
    tax_ref: Optional[str] = None
    discount_ref: Optional[str] = None
    shipping_ref: Optional[str] = None
    tip_ref: Optional[str] = None
    fees_ref: List[str] = Field(default_factory=list)
    grand_total_ref: Optional[str] = None
    amount_due_ref: Optional[str] = None

    @field_validator(
        "subtotal_ref", "tax_ref", "discount_ref", "shipping_ref", "tip_ref",
        "grand_total_ref", "amount_due_ref", mode="before"
    )
    @classmethod
    def check_token_ref(cls, v: Optional[str]) -> Optional[str]:
        return validate_token_ref(v)

    @field_validator("fees_ref", mode="before")
    @classmethod
    def check_fees_ref(cls, v: Any) -> List[str]:
        if not v:
            return []
        if isinstance(v, list):
            res = []
            for item in v:
                validated = validate_token_ref(item)
                if validated:
                    res.append(validated)
            return res
        return []


class LLMInvoice(BaseModel):
    doc_type: DocType = DocType.GOODS_INVOICE
    vendor_name: Optional[str] = None
    invoice_no_ref: Optional[str] = None
    invoice_date_ref: Optional[str] = None
    due_date_ref: Optional[str] = None
    currency: Optional[str] = "$"
    category: Optional[Category] = None
    line_items: List[LLMLineItem] = Field(default_factory=list)
    charges: List[LLMCharge] = Field(default_factory=list)
    summary: LLMSummary = Field(default_factory=LLMSummary)
    unassigned: List[str] = Field(default_factory=list)

    @field_validator("invoice_no_ref", "invoice_date_ref", "due_date_ref", mode="before")
    @classmethod
    def check_token_ref(cls, v: Optional[str]) -> Optional[str]:
        return validate_token_ref(v)


# ---------------------------------------------------------
# Canonical Schema (After Rehydration and Validation)
# ---------------------------------------------------------

class CanonicalLineItem(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    item_name: str
    qty: Optional[Decimal] = None
    qty_prov: Optional[Provenance] = None
    unit_price: Optional[Decimal] = None
    unit_price_prov: Optional[Provenance] = None
    line_total: Optional[Decimal] = None
    line_total_prov: Optional[Provenance] = None
    unit: Optional[str] = None
    kind: LineItemKind = LineItemKind.GOODS
    checkable: bool = True
    math_error: Optional[str] = None


class CanonicalCharge(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    description: str
    amount: Decimal
    amount_prov: Optional[Provenance] = None


class CanonicalInvoice(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    source_file: str
    source_sha256: str
    status: InvoiceStatus = InvoiceStatus.REVIEW_NEEDED
    doc_type: DocType = DocType.GOODS_INVOICE
    vendor_name: Optional[str] = None
    invoice_no: Optional[str] = None
    invoice_no_prov: Optional[Provenance] = None
    invoice_date: Optional[str] = None  # ISO YYYY-MM-DD
    invoice_date_prov: Optional[Provenance] = None
    due_date: Optional[str] = None
    due_date_prov: Optional[Provenance] = None
    currency: str = "USD"
    category: Category = Category.OTHER
    line_items: List[CanonicalLineItem] = Field(default_factory=list)
    charges: List[CanonicalCharge] = Field(default_factory=list)
    subtotal: Optional[Decimal] = None
    subtotal_prov: Optional[Provenance] = None
    tax: Optional[Decimal] = None
    tax_prov: Optional[Provenance] = None
    discount: Optional[Decimal] = None
    discount_prov: Optional[Provenance] = None
    shipping: Optional[Decimal] = None
    shipping_prov: Optional[Provenance] = None
    tip: Optional[Decimal] = None
    tip_prov: Optional[Provenance] = None
    fees: List[Decimal] = Field(default_factory=list)
    grand_total: Optional[Decimal] = None
    grand_total_prov: Optional[Provenance] = None
    amount_due: Optional[Decimal] = None
    amount_due_prov: Optional[Provenance] = None
    review_reasons: List[str] = Field(default_factory=list)
    schema_version: str = SCHEMA_VERSION
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None

    def to_jsonl_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary with Decimals as strings."""
        data = self.model_dump()

        def convert_decimals(obj: Any) -> Any:
            if isinstance(obj, Decimal):
                return str(obj)
            if isinstance(obj, dict):
                return {k: convert_decimals(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [convert_decimals(elem) for elem in obj]
            return obj

        return convert_decimals(data)
