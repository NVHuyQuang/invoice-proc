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
from core.ocr_preprocess import deskew_image, enhance_contrast_clahe
from core.types import Document, Page, Line, Word, Vault, VaultEntry
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


STRIP_CHARS = "$€£¥₫(), \t\n" + chr(13)


def link_vault_to_words(vault: Vault, words: List[Word]) -> None:
    """Link Word.bbox, page, conf to VaultEntry objects to preserve original coordinates."""
    if not words or not vault:
        return

    sorted_words = sorted(words, key=lambda w: (w.page, w.bbox[1], w.bbox[0]))
    num_words = len(sorted_words)
    word_ptr = 0

    for token in list(vault.keys()):
        entry = vault[token]
        # Skip if entry already has non-zero bbox
        if entry.bbox != (0.0, 0.0, 0.0, 0.0):
            continue

        raw = entry.raw.strip()
        raw_clean = raw.strip(STRIP_CHARS)

        matched_idx = -1

        # Search forward from current pointer
        for i in range(word_ptr, num_words):
            w = sorted_words[i]
            w_text = w.text.strip()
            w_clean = w_text.strip(STRIP_CHARS)

            if (
                raw == w_text
                or (raw_clean and raw_clean == w_clean)
                or (raw_clean and raw_clean in w_text)
                or (w_clean and len(w_clean) >= 2 and w_clean in raw)
            ):
                matched_idx = i
                break

        # Search from beginning if forward search fails
        if matched_idx == -1:
            for i in range(0, min(word_ptr, num_words)):
                w = sorted_words[i]
                w_text = w.text.strip()
                w_clean = w_text.strip(STRIP_CHARS)

                if (
                    raw == w_text
                    or (raw_clean and raw_clean == w_clean)
                    or (raw_clean and raw_clean in w_text)
                    or (w_clean and len(w_clean) >= 2 and w_clean in raw)
                ):
                    matched_idx = i
                    break


        if matched_idx != -1:
            matched_w = sorted_words[matched_idx]
            word_ptr = matched_idx + 1

            bx0, by0, bx1, by1 = matched_w.bbox
            m_conf = matched_w.conf
            m_page = matched_w.page

            # Combine adjacent word bounding boxes if token spans multiple words
            if matched_idx + 1 < num_words and len(matched_w.text.strip()) < len(raw):
                next_w = sorted_words[matched_idx + 1]
                comb = matched_w.text.strip() + next_w.text.strip()
                if (raw_clean and raw_clean in comb) or (comb in raw):
                    bx0 = min(bx0, next_w.bbox[0])
                    by0 = min(by0, next_w.bbox[1])
                    bx1 = max(bx1, next_w.bbox[2])
                    by1 = max(by1, next_w.bbox[3])
                    m_conf = min(m_conf, next_w.conf)
                    word_ptr = matched_idx + 2

            new_entry = VaultEntry(
                token=entry.token,
                raw=entry.raw,
                kind=entry.kind,
                page=m_page,
                bbox=(bx0, by0, bx1, by1),
                conf=m_conf,
                neg_hint=entry.neg_hint,
            )
            vault.add(new_entry)



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
                            prep_img, _ = deskew_image(img)
                            prep_img = enhance_contrast_clahe(prep_img)
                        except Exception as e:
                            logger.warning("Preprocessing failed for page %s: %s", page_num, e)
                            prep_img = img

                        try:
                            ocr_words = ocr_engine.predict(prep_img, page_num=page_num, raise_on_error=True)
                        except TypeError:
                            ocr_words = ocr_engine.predict(prep_img, page_num=page_num)
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

            # Conditional preprocessing (deskew, CLAHE)
            try:
                prep_img, _ = deskew_image(img_arr)
                prep_img = enhance_contrast_clahe(prep_img)
            except Exception as e:
                logger.warning("Preprocessing failed for image %s: %s", path.name, e)
                prep_img = img_arr

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
                    ocr_words = ocr_engine.predict(prep_img, page_num=1, raise_on_error=True)
                except TypeError:
                    ocr_words = ocr_engine.predict(prep_img, page_num=1)
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

        logger.debug("[Pipeline Step 1: Ingestion] %s (ftype=%s, pages=%d)", path.name, ftype, len(doc.pages))

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
        logger.debug("[Pipeline Step 2: Layout] Reconstructed %d lines from %d words", len(all_lines), len(doc.all_words))

        # 3. Redactor
        redacted_text, _ = redact_text(formatted_text)
        logger.debug("[Pipeline Step 3: Redactor] Redacted formatted text (%d chars)", len(redacted_text))

        # 4. Tokenizer
        masked_text, vault = tokenize_text(redacted_text, vault=vault)
        # Link original Word.bbox, page, conf to VaultEntry
        link_vault_to_words(vault, doc.all_words)
        logger.debug("[Pipeline Step 4: Tokenizer] Generated %d vault entries with provenance", len(vault))

        # 5. Leak Guard
        is_valid, _ = verify_payload(masked_text)
        logger.debug("[Pipeline Step 5: Leak Guard] Payload valid: %s", is_valid)
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
                    logger.debug("[Pipeline Step 6: LLM/Cache] Cache hit for %s", path.name)
                except Exception:
                    llm_invoice = None

        if llm_invoice is None:
            prompt = build_system_prompt()
            try:
                llm_invoice = llm_client.parse_invoice(prompt, masked_text)
                logger.debug("[Pipeline Step 6: LLM/Cache] LLM extraction completed for %s", path.name)
            except Exception:
                return CanonicalInvoice(
                    source_file=str(path),
                    source_sha256=sha256,
                    status=InvoiceStatus.FAILED,
                    review_reasons=["llm_error"],
                )
            if cache is not None:
                try:
                    cache.put(cache_key, llm_invoice.model_dump_json())
                except Exception as exc:
                    logger.warning("Failed to store cache for %s: %s", path.name, exc)

        # 8. Rehydrate
        try:
            verify_llm_tokens(llm_invoice, vault)
            canonical_invoice = rehydrate_invoice(
                llm_invoice=llm_invoice,
                vault=vault,
                source_file=str(path),
                source_sha256=sha256,
            )
            logger.debug("[Pipeline Step 7: Rehydrate] Rehydrated invoice successfully")
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
        logger.debug("[Pipeline Step 8: Validator] Final status: %s", final_invoice.status)
        return final_invoice


    finally:
        vault.clear()
