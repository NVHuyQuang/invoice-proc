"""Pydantic schemas for LLM structured output and Canonical Invoice.

Frozen at Wave 0.
"""

from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator, ConfigDict, model_validator
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


# ---------------------------------------------------------
# Multimodal VLM Direct Output Schemas & Converter
# ---------------------------------------------------------

class VLMLineItem(BaseModel):
    item_name: str = ""
    qty: Optional[Union[str, float, int, Decimal]] = None
    unit_price: Optional[Union[str, float, int, Decimal]] = None
    line_total: Optional[Union[str, float, int, Decimal]] = None
    unit: Optional[str] = None
    kind: LineItemKind = LineItemKind.GOODS
    checkable: bool = True


class VLMCharge(BaseModel):
    description: str = ""
    amount: Optional[Union[str, float, int, Decimal]] = None


class VLMSummary(BaseModel):
    subtotal: Optional[Union[str, float, int, Decimal]] = None
    tax: Optional[Union[str, float, int, Decimal]] = None
    discount: Optional[Union[str, float, int, Decimal]] = None
    shipping: Optional[Union[str, float, int, Decimal]] = None
    tip: Optional[Union[str, float, int, Decimal]] = None
    fees: List[Union[str, float, int, Decimal]] = Field(default_factory=list)
    grand_total: Optional[Union[str, float, int, Decimal]] = None
    amount_due: Optional[Union[str, float, int, Decimal]] = None

    @field_validator("fees", mode="before")
    @classmethod
    def normalize_fees(cls, v: Any) -> List[Any]:
        if v is None:
            return []
        if isinstance(v, (int, float, Decimal)):
            return [] if v == 0 else [v]
        if isinstance(v, str):
            if v.strip() in ("", "0", "0.0", "0.00"):
                return []
            return [v]
        if isinstance(v, list):
            return v
        return []


class VLMInvoice(BaseModel):
    doc_type: DocType = DocType.GOODS_INVOICE
    vendor_name: str = ""
    invoice_no: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    currency: str = "USD"
    category: Category = Category.OTHER
    line_items: List[VLMLineItem] = Field(default_factory=list)
    charges: List[VLMCharge] = Field(default_factory=list)
    summary: VLMSummary = Field(default_factory=VLMSummary)

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("vendor_name"):
                for alias in ("vendor", "supplier", "seller", "merchant", "biller", "issuer", "company"):
                    if alias in data and data[alias]:
                        v = data[alias]
                        if isinstance(v, dict):
                            data["vendor_name"] = str(v.get("name", "") or v.get("vendor_name", "") or "")
                        elif isinstance(v, str):
                            data["vendor_name"] = v
                        if data.get("vendor_name"):
                            break
            if not data.get("invoice_no"):
                for alias in (
                    "invoice_number", "inv_no", "inv_number", "receipt_number", "receipt_no",
                    "bill_number", "bill_no", "account_number", "account_no", "acc_no", "account"
                ):
                    if alias in data and data[alias]:
                        data["invoice_no"] = str(data[alias])
                        break
            if not data.get("invoice_date"):
                for alias in ("bill_date", "billing_date", "statement_date", "date"):
                    if alias in data and data[alias]:
                        data["invoice_date"] = str(data[alias])
                        break
        return data


def vlm_to_canonical(
    vlm: VLMInvoice,
    source_file: str,
    source_sha256: str,
    date_locale: Optional[str] = None,
) -> CanonicalInvoice:
    """Convert raw VLMInvoice output into validated CanonicalInvoice.

    Sanitizes numbers and currency strings using core.numparse.parse_number,
    parses dates to ISO YYYY-MM-DD via core.rehydrator._parse_date,
    and sets initial status to REVIEW_NEEDED for subsequent math validation.
    """
    from core.numparse import parse_number, AmbiguousNumberError
    from core.rehydrator import _parse_date
    from config import DEFAULT_DATE_LOCALE

    eff_date_locale = date_locale or DEFAULT_DATE_LOCALE
    review_reasons: List[str] = []

    def _convert_num(val: Any, neg_hint: bool = False) -> Optional[Decimal]:
        if val is None:
            return None
        if isinstance(val, Decimal):
            return val
        if isinstance(val, (int, float)):
            return Decimal(str(val))
        s = str(val).strip()
        if not s or s.lower() in ("none", "null", "n/a"):
            return None
        try:
            return parse_number(s, neg_hint=neg_hint)
        except AmbiguousNumberError:
            if "ambiguous_number" not in review_reasons:
                review_reasons.append("ambiguous_number")
            try:
                cleaned = re.sub(r"[^\d.-]", "", s)
                if cleaned:
                    return Decimal(cleaned)
            except Exception:
                pass
            return None
        except Exception:
            try:
                cleaned = re.sub(r"[^\d.-]", "", s)
                if cleaned:
                    return Decimal(cleaned)
            except Exception:
                pass
            return None

    # Line items
    canonical_items: List[CanonicalLineItem] = []
    for it in vlm.line_items:
        q = _convert_num(it.qty)
        p = _convert_num(it.unit_price)
        t = _convert_num(it.line_total)
        canonical_items.append(
            CanonicalLineItem(
                item_name=it.item_name,
                qty=q,
                unit_price=p,
                line_total=t,
                unit=it.unit,
                kind=it.kind,
                checkable=it.checkable,
            )
        )

    # Charges
    canonical_charges: List[CanonicalCharge] = []
    for ch in vlm.charges:
        amt = _convert_num(ch.amount)
        if amt is not None:
            canonical_charges.append(
                CanonicalCharge(
                    description=ch.description,
                    amount=amt,
                )
            )

    # Dates
    is_us_locale = (vlm.currency in ("USD", "$") or eff_date_locale == "MM/DD")
    inv_date: Optional[str] = None
    if vlm.invoice_date:
        parsed_d, is_ambig = _parse_date(str(vlm.invoice_date), default_locale=eff_date_locale)
        inv_date = parsed_d
        if is_ambig and not is_us_locale and "ambiguous_date" not in review_reasons:
            review_reasons.append("ambiguous_date")

    due_date: Optional[str] = None
    if vlm.due_date:
        parsed_due, is_due_ambig = _parse_date(str(vlm.due_date), default_locale=eff_date_locale)
        due_date = parsed_due
        if is_due_ambig and not is_us_locale and "ambiguous_date" not in review_reasons:
            review_reasons.append("ambiguous_date")

    # Summary
    sub = _convert_num(vlm.summary.subtotal)
    tax = _convert_num(vlm.summary.tax)
    disc = _convert_num(vlm.summary.discount)
    ship = _convert_num(vlm.summary.shipping)
    tip = _convert_num(vlm.summary.tip)
    fees = [_convert_num(f) for f in vlm.summary.fees if _convert_num(f) is not None]
    gt = _convert_num(vlm.summary.grand_total)
    ad = _convert_num(vlm.summary.amount_due)

    return CanonicalInvoice(
        source_file=source_file,
        source_sha256=source_sha256,
        status=InvoiceStatus.REVIEW_NEEDED,
        doc_type=vlm.doc_type,
        vendor_name=vlm.vendor_name,
        invoice_no=vlm.invoice_no,
        invoice_date=inv_date,
        due_date=due_date,
        currency=vlm.currency,
        category=vlm.category,
        line_items=canonical_items,
        charges=canonical_charges,
        subtotal=sub,
        tax=tax,
        discount=disc,
        shipping=ship,
        tip=tip,
        fees=[f for f in fees if f is not None],
        grand_total=gt,
        amount_due=ad,
        review_reasons=review_reasons,
    )
