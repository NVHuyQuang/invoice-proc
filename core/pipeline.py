"""End-to-end processing pipeline for a single invoice document.

Connects:
ingestion -> (OCR) -> layout -> redactor -> tokenizer -> leak_guard -> prompt -> llm -> rehydrator -> validator.
Isolates errors per file.
Ensures vault.clear() is called in a finally block.
Supports resume via cache.
"""

from pathlib import Path
from typing import Optional, List
import logging

from models.schema import (
    CanonicalInvoice,
    InvoiceStatus,
    LLMInvoice,
)
from core.llm_parser import LLMClient
from core.llm_cache import LLMCache
from core.ocr_engine import OCREngine
from core.types import Document, Page, Line, Word
from core.vault import create_vault
from core.ingestion import compute_file_sha256, detect_file_type, load_image
from core.ingestion_pdf import load_pdf_document, deduplicate_headers_footers
from core.layout import reconstruct_lines
from core.layout_columns import assign_columns, format_lines_as_text
from core.redactor import redact_text
from core.tokenizer import tokenize_text
from core.leak_guard import verify_payload
from core.prompt import build_system_prompt
from core.rehydrator import verify_llm_tokens, rehydrate_invoice
from core.validator import assign_invoice_status

logger = logging.getLogger(__name__)


def process_invoice_file(
    file_path: Path,
    llm_client: LLMClient,
    ocr_engine: Optional[OCREngine] = None,
    cache: Optional[LLMCache] = None,
    target_month: Optional[str] = None,
    dry_run: bool = False
) -> CanonicalInvoice:
    """Process a single invoice file through the full extraction pipeline.

    Args:
        file_path: Path to target PDF or image.
        llm_client: Configured LLMClient.
        ocr_engine: Initialized OCREngine for scanned pages.
        cache: Optional LLMCache for fast resume.
        target_month: Processing month string 'YYYY-MM'.
        dry_run: If True, halts after Leak Guard and prints payload.

    Returns:
        Processed CanonicalInvoice or FAILED invoice placeholder.
    """
    path = Path(file_path)
    sha256 = ""
    vault = create_vault()

    try:
        # Check file existence
        if not path.is_file():
            return CanonicalInvoice(
                source_file=str(path),
                source_sha256="",
                status=InvoiceStatus.FAILED,
                review_reasons=["file_unreadable"],
            )

        # Ingestion - SHA-256 calculation
        try:
            sha256 = compute_file_sha256(path)
        except Exception:
            return CanonicalInvoice(
                source_file=str(path),
                source_sha256="",
                status=InvoiceStatus.FAILED,
                review_reasons=["file_unreadable"],
            )

        # Ingestion - file type detection
        try:
            ftype = detect_file_type(path)
        except Exception:
            return CanonicalInvoice(
                source_file=str(path),
                source_sha256=sha256,
                status=InvoiceStatus.FAILED,
                review_reasons=["file_unreadable"],
            )

        if ftype == "pdf":
            try:
                doc, ocr_pages = load_pdf_document(path)
            except Exception:
                return CanonicalInvoice(
                    source_file=str(path),
                    source_sha256=sha256,
                    status=InvoiceStatus.FAILED,
                    review_reasons=["file_unreadable"],
                )

            if ocr_pages:
                if ocr_engine is None:
                    try:
                        ocr_engine = OCREngine()
                    except Exception:
                        return CanonicalInvoice(
                            source_file=str(path),
                            source_sha256=sha256,
                            status=InvoiceStatus.FAILED,
                            review_reasons=["ocr_error"],
                        )
                try:
                    for page_num, img in ocr_pages:
                        try:
                            ocr_words = ocr_engine.predict(img, page_num=page_num, raise_on_error=True)
                        except TypeError:
                            ocr_words = ocr_engine.predict(img, page_num=page_num)
                        for p in doc.pages:
                            if p.page_num == page_num:
                                p.words.extend(ocr_words)
                                break
                    doc.pages = deduplicate_headers_footers(doc.pages)
                except Exception:
                    return CanonicalInvoice(
                        source_file=str(path),
                        source_sha256=sha256,
                        status=InvoiceStatus.FAILED,
                        review_reasons=["ocr_error"],
                    )

        elif ftype in ("jpeg", "png", "webp", "heic"):
            try:
                img_arr, scale_factor = load_image(path)
            except Exception:
                return CanonicalInvoice(
                    source_file=str(path),
                    source_sha256=sha256,
                    status=InvoiceStatus.FAILED,
                    review_reasons=["file_unreadable"],
                )

            if ocr_engine is None:
                try:
                    ocr_engine = OCREngine()
                except Exception:
                    return CanonicalInvoice(
                        source_file=str(path),
                        source_sha256=sha256,
                        status=InvoiceStatus.FAILED,
                        review_reasons=["ocr_error"],
                    )

            try:
                try:
                    ocr_words = ocr_engine.predict(img_arr, page_num=1, raise_on_error=True)
                except TypeError:
                    ocr_words = ocr_engine.predict(img_arr, page_num=1)
            except Exception:
                return CanonicalInvoice(
                    source_file=str(path),
                    source_sha256=sha256,
                    status=InvoiceStatus.FAILED,
                    review_reasons=["ocr_error"],
                )

            h, w = img_arr.shape[:2]
            if scale_factor != 1.0 and scale_factor > 0:
                inv_scale = 1.0 / scale_factor
                rescaled_words = []
                for word in ocr_words:
                    x0, y0, x1, y1 = word.bbox
                    rescaled_words.append(
                        Word(
                            text=word.text,
                            bbox=(x0 * inv_scale, y0 * inv_scale, x1 * inv_scale, y1 * inv_scale),
                            conf=word.conf,
                            page=word.page,
                            source=word.source,
                        )
                    )
                ocr_words = rescaled_words
                orig_w = float(w * inv_scale)
                orig_h = float(h * inv_scale)
            else:
                orig_w = float(w)
                orig_h = float(h)

            page = Page(page_num=1, width=orig_w, height=orig_h, words=ocr_words)
            doc = Document(file_path=str(path), sha256=sha256, pages=[page])

        else:
            return CanonicalInvoice(
                source_file=str(path),
                source_sha256=sha256,
                status=InvoiceStatus.FAILED,
                review_reasons=["file_unreadable"],
            )

        # 2. Layout
        if not doc.pages:
            return CanonicalInvoice(
                source_file=str(path),
                source_sha256=sha256,
                status=InvoiceStatus.FAILED,
                review_reasons=["file_unreadable"],
            )

        all_lines: List[Line] = []
        for page in doc.pages:
            lines = reconstruct_lines(page.words, page_height=page.height, page_width=page.width)
            lines = assign_columns(lines, page_width=page.width)
            page.lines = lines
            all_lines.extend(lines)

        formatted_text = format_lines_as_text(all_lines)

        # 3. Redactor
        redacted_text, _ = redact_text(formatted_text)

        # 4. Tokenizer
        masked_text, vault = tokenize_text(redacted_text, vault=vault)

        # 5. Leak Guard
        is_valid, _ = verify_payload(masked_text)
        if not is_valid:
            return CanonicalInvoice(
                source_file=str(path),
                source_sha256=sha256,
                status=InvoiceStatus.REVIEW_NEEDED,
                review_reasons=["leak_guard_violation"],
            )

        # 6. Dry Run
        if dry_run:
            print(masked_text)
            return CanonicalInvoice(
                source_file=str(path),
                source_sha256=sha256,
                status=InvoiceStatus.REVIEW_NEEDED,
                review_reasons=["dry_run"],
            )

        # 7. LLM / Cache
        cache_key = LLMCache.get_cache_key(masked_text) if cache else ""
        llm_invoice: Optional[LLMInvoice] = None

        if cache is not None:
            cached_res = cache.get(cache_key)
            if cached_res is not None:
                try:
                    llm_invoice = LLMInvoice.model_validate_json(cached_res)
                except Exception:
                    llm_invoice = None

        if llm_invoice is None:
            prompt = build_system_prompt()
            try:
                llm_invoice = llm_client.parse_invoice(prompt, masked_text)
            except Exception:
                return CanonicalInvoice(
                    source_file=str(path),
                    source_sha256=sha256,
                    status=InvoiceStatus.FAILED,
                    review_reasons=["llm_error"],
                )
            if cache is not None:
                cache.put(cache_key, llm_invoice.model_dump_json())

        # 8. Rehydrate
        try:
            verify_llm_tokens(llm_invoice, vault)
            canonical_invoice = rehydrate_invoice(
                llm_invoice=llm_invoice,
                vault=vault,
                source_file=str(path),
                source_sha256=sha256,
            )
        except Exception:
            return CanonicalInvoice(
                source_file=str(path),
                source_sha256=sha256,
                status=InvoiceStatus.FAILED,
                review_reasons=["llm_error"],
            )

        # 9. Validator
        final_invoice = assign_invoice_status(
            canonical_invoice,
            rehydrator_flags=canonical_invoice.review_reasons,
            target_month=target_month,
        )
        return final_invoice

    finally:
        vault.clear()
