"""PDF ingestion and dual-routing module.

PLAN 1.3-1.4:
- Dual-routing per page:
  Page is clean text if:
  1. Printable char count >= 50
  2. Valid char ratio >= 0.85
  3. Background image area ratio <= 0.80
  If met: extract text words via page.get_text("words") with conf=1.0 and source="pdf_text".
  If not met: render page at 300 DPI (page.get_pixmap(dpi=300)) for downstream OCR.
- Document assembly: gathers all pages into single Document.
- Header/footer deduplication across pages for repeated boilerplate.
"""

from pathlib import Path
from typing import List, Tuple, Union, Any
import numpy as np
from core.types import Word, Page, Document


def inspect_pdf_page(page_obj: Any) -> Tuple[bool, Union[List[Word], np.ndarray]]:
    """Determine whether page has clean text layer or requires OCR rendering.

    Args:
        page_obj: fitz.Page object.

    Returns:
        Tuple of (is_clean_text, words_list_or_rendered_rgb_image).
    """
    raise NotImplementedError("W1-pdfrouter implementation pending")


def load_pdf_document(file_path: Path) -> Tuple[List[Page], List[Tuple[int, np.ndarray]]]:
    """Load PDF file, extracting words for clean text pages and rendered images for OCR pages.

    Args:
        file_path: Path to PDF.

    Returns:
        Tuple of (pages_with_words, list_of_pages_needing_ocr).
    """
    raise NotImplementedError("W1-pdfrouter implementation pending")


def deduplicate_headers_footers(pages: List[Page]) -> List[Page]:
    """Strip repeated headers/footers (e.g. 'Page X of Y', repeated vendor banner) across multi-page docs.

    Args:
        pages: List of pages in document.

    Returns:
        Cleaned list of pages.
    """
    raise NotImplementedError("W1-pdfrouter implementation pending")
