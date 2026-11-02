"""End-to-end processing pipeline for a single invoice document.

Connects:
ingestion -> (OCR) -> layout -> redactor -> tokenizer -> leak_guard -> prompt -> llm -> rehydrator -> validator.
Isolates errors per file.
Ensures vault.clear() is called in a finally block.
Supports resume via cache.
"""

from pathlib import Path
from typing import Optional
from models.schema import CanonicalInvoice
from core.llm_parser import LLMClient
from core.llm_cache import LLMCache
from core.ocr_engine import OCREngine


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
    raise NotImplementedError("W2-pipeline implementation pending")
