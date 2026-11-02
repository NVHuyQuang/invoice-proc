"""PDF ingestion and dual-routing module.

PLAN 1.3-1.4:
- Dual-routing per page:
  Page is clean text if:
  1. Printable char count >= 50 (MIN_PRINTABLE_CHARS)
  2. Valid char ratio >= 0.85 (MIN_VALID_CHAR_RATIO)
  3. Background image area ratio <= 0.80 (MAX_IMAGE_AREA_RATIO)
  If met: extract text words via page.get_text("words") with conf=1.0 and source="pdf_text".
  If not met: render page at 300 DPI (page.get_pixmap(dpi=300)) for downstream OCR.
- Document assembly: gathers all pages into single Document.
- Header/footer deduplication across pages for repeated boilerplate.
"""

import hashlib
import re
import string
import unicodedata
from pathlib import Path
from typing import List, Tuple, Union, Any, Set
import numpy as np
import pymupdf as fitz
from rapidfuzz import fuzz

from core.types import Word, Page, Document
from config import (
    PDF_RENDER_DPI,
    MIN_PRINTABLE_CHARS,
    MIN_VALID_CHAR_RATIO,
    MAX_IMAGE_AREA_RATIO,
    MAX_IMAGE_DIMENSION,
    DEDUP_SIMILARITY_THRESHOLD,
)

# Enable duck-typing iteration/len/indexing on Document if not already present
if not hasattr(Document, "__iter__"):
    Document.__iter__ = lambda self: iter(self.pages)  # type: ignore[assignment]
if not hasattr(Document, "__len__"):
    Document.__len__ = lambda self: len(self.pages)  # type: ignore[assignment]
if not hasattr(Document, "__getitem__"):
    Document.__getitem__ = lambda self, idx: self.pages[idx]  # type: ignore[assignment]

COMMON_PUNCTUATION: Set[str] = set(string.punctuation) | {
    "–", "—", "“", "”", "‘", "’", "•", "°", "…", "«", "»"
}

PAGE_NUM_PATTERN = re.compile(
    r"\b(?:page|trang)\s+\d+(?:\s*(?:of|/|trên)\s*\d+)?\b|\b\d+\s*(?:of|/|trên)\s*\d+\b",
    re.IGNORECASE,
)


def is_valid_char(c: str) -> bool:
    """Check if character is a valid alphanumeric letter, digit, common punctuation, or currency symbol."""
    if c.isalnum():
        return True
    if c in COMMON_PUNCTUATION:
        return True
    cat = unicodedata.category(c)
    if cat.startswith("P") or cat in ("Sc", "Sm"):
        return True
    return False


def compute_valid_char_ratio(text: str) -> float:
    """Compute ratio of valid characters (letters, numbers, common punctuation) over non-whitespace characters."""
    non_space_chars = [c for c in text if not c.isspace()]
    if not non_space_chars:
        return 0.0
    valid_count = sum(1 for c in non_space_chars if is_valid_char(c))
    return valid_count / len(non_space_chars)


def compute_background_image_ratio(page_obj: Any) -> float:
    """Compute the maximum area ratio occupied by a single background image on the page."""
    page_rect = page_obj.rect
    page_area = max(1.0, float(page_rect.width) * float(page_rect.height))
    try:
        image_infos = page_obj.get_image_info()
    except Exception:
        return 0.0

    if not image_infos:
        return 0.0

    max_area = 0.0
    for info in image_infos:
        bbox = info.get("bbox")
        if bbox:
            img_rect = fitz.Rect(bbox) & page_rect
            area = max(0.0, float(img_rect.width)) * max(0.0, float(img_rect.height))
            if area > max_area:
                max_area = area

    return max_area / page_area


def render_page_to_image(
    page_obj: Any,
    dpi: int = PDF_RENDER_DPI,
    max_dimension: int = MAX_IMAGE_DIMENSION,
) -> np.ndarray:
    """Render a fitz.Page to an RGB uint8 numpy array with DPI and dimension constraints."""
    zoom = dpi / 72.0
    w_est = page_obj.rect.width * zoom
    h_est = page_obj.rect.height * zoom
    max_dim = max(w_est, h_est)
    if max_dim > max_dimension:
        scale = zoom * (max_dimension / max_dim)
    else:
        scale = zoom

    mat = fitz.Matrix(scale, scale)
    pix = page_obj.get_pixmap(matrix=mat, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
    if pix.n == 1:
        img = np.stack([img.squeeze()] * 3, axis=-1)
    elif pix.n > 3:
        img = img[:, :, :3]
    return img


def inspect_pdf_page(page_obj: Any) -> Tuple[bool, Union[List[Word], np.ndarray]]:
    """Determine whether page has clean text layer or requires OCR rendering.

    Evaluates 3 conditions for clean text:
    1. Printable character count >= MIN_PRINTABLE_CHARS (50)
    2. Valid character ratio >= MIN_VALID_CHAR_RATIO (0.85)
    3. Background image area ratio <= MAX_IMAGE_AREA_RATIO (0.80)

    Args:
        page_obj: fitz.Page object.

    Returns:
        Tuple of (is_clean_text, words_list_or_rendered_rgb_image).
    """
    page_num = getattr(page_obj, "number", 0) + 1
    raw_text = page_obj.get_text("text") or ""
    printable_chars = [c for c in raw_text if c.isprintable()]
    printable_count = len(printable_chars)

    valid_ratio = compute_valid_char_ratio(raw_text)
    bg_image_ratio = compute_background_image_ratio(page_obj)

    raw_words = page_obj.get_text("words") or []

    is_clean = (
        printable_count >= MIN_PRINTABLE_CHARS
        and valid_ratio >= MIN_VALID_CHAR_RATIO
        and bg_image_ratio <= MAX_IMAGE_AREA_RATIO
        and len(raw_words) > 0
    )

    if is_clean:
        words: List[Word] = []
        rot_matrix = getattr(page_obj, "rotation_matrix", None)
        rotation = getattr(page_obj, "rotation", 0)

        for w in raw_words:
            x0, y0, x1, y1, text = float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])
            if rotation != 0 and rot_matrix is not None:
                r = fitz.Rect(x0, y0, x1, y1) * rot_matrix
                bbox = (float(r.x0), float(r.y0), float(r.x1), float(r.y1))
            else:
                bbox = (x0, y0, x1, y1)

            words.append(
                Word(
                    text=text,
                    bbox=bbox,
                    conf=1.0,
                    page=page_num,
                    source="pdf_text",
                )
            )
        return (True, words)
    else:
        img = render_page_to_image(page_obj)
        return (False, img)


def _group_words_into_lines(words: List[Word], y_tolerance: float = 4.0) -> List[List[Word]]:
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: ((w.bbox[1] + w.bbox[3]) / 2.0, w.bbox[0]))
    lines: List[List[Word]] = []
    current_line: List[Word] = [sorted_words[0]]
    current_y = (sorted_words[0].bbox[1] + sorted_words[0].bbox[3]) / 2.0

    for w in sorted_words[1:]:
        wy = (w.bbox[1] + w.bbox[3]) / 2.0
        w_height = max(1.0, w.bbox[3] - w.bbox[1])
        tol = max(y_tolerance, w_height * 0.5)
        if abs(wy - current_y) <= tol:
            current_line.append(w)
            current_y = sum((x.bbox[1] + x.bbox[3]) / 2.0 for x in current_line) / len(current_line)
        else:
            lines.append(sorted(current_line, key=lambda x: x.bbox[0]))
            current_line = [w]
            current_y = wy
    if current_line:
        lines.append(sorted(current_line, key=lambda x: x.bbox[0]))
    return lines


def _normalize_line_text(line: List[Word]) -> Tuple[str, str]:
    text = " ".join(w.text for w in line).strip().lower()
    text = re.sub(r"\s+", " ", text)
    page_norm = PAGE_NUM_PATTERN.sub("<PAGE>", text)
    return text, page_norm


def deduplicate_headers_footers(
    pages: List[Page],
    edge_ratio: float = 0.20,
    threshold: float = float(DEDUP_SIMILARITY_THRESHOLD),
) -> List[Page]:
    """Strip repeated headers/footers (e.g. 'Page X of Y', repeated vendor banner) across multi-page docs.

    Args:
        pages: List of pages in document.
        edge_ratio: Fraction of page height defining header and footer margins.
        threshold: Fuzzy match similarity threshold (default from DEDUP_SIMILARITY_THRESHOLD).

    Returns:
        Cleaned list of pages.
    """
    if len(pages) <= 1:
        return pages

    cleaned_pages: List[Page] = []
    seen_headers: List[Tuple[str, str]] = []
    seen_footers: List[Tuple[str, str]] = []

    for idx, page in enumerate(pages):
        if not page.words:
            cleaned_pages.append(page)
            continue

        h = page.height
        top_boundary = h * edge_ratio
        bottom_boundary = h * (1.0 - edge_ratio)

        header_words: List[Word] = []
        footer_words: List[Word] = []
        body_words: List[Word] = []

        for w in page.words:
            w_cy = (w.bbox[1] + w.bbox[3]) / 2.0
            if w_cy <= top_boundary:
                header_words.append(w)
            elif w_cy >= bottom_boundary:
                footer_words.append(w)
            else:
                body_words.append(w)

        header_lines = _group_words_into_lines(header_words)
        footer_lines = _group_words_into_lines(footer_words)

        if idx == 0:
            for hl in header_lines:
                seen_headers.append(_normalize_line_text(hl))
            for fl in footer_lines:
                seen_footers.append(_normalize_line_text(fl))
            cleaned_pages.append(page)
        else:
            kept_words: List[Word] = list(body_words)

            for hl in header_lines:
                raw_norm, page_norm = _normalize_line_text(hl)
                is_duplicate = False
                for ref_raw, ref_page in seen_headers:
                    if raw_norm == ref_raw or page_norm == ref_page:
                        is_duplicate = True
                        break
                    if fuzz.ratio(page_norm, ref_page) >= threshold:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    kept_words.extend(hl)

            for fl in footer_lines:
                raw_norm, page_norm = _normalize_line_text(fl)
                is_duplicate = False
                for ref_raw, ref_page in seen_footers:
                    if raw_norm == ref_raw or page_norm == ref_page:
                        is_duplicate = True
                        break
                    if fuzz.ratio(page_norm, ref_page) >= threshold:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    kept_words.extend(fl)

            kept_words.sort(key=lambda w: (w.bbox[1], w.bbox[0]))
            new_page = Page(
                page_num=page.page_num,
                width=page.width,
                height=page.height,
                words=kept_words,
                lines=page.lines,
            )
            cleaned_pages.append(new_page)

    return cleaned_pages


def load_pdf_document(file_path: Union[str, Path]) -> Tuple[Document, List[Tuple[int, np.ndarray]]]:
    """Load PDF file, extracting words for clean text pages and rendered images for OCR pages.

    Args:
        file_path: Path to PDF.

    Returns:
        Tuple of (Document, list_of_pages_needing_ocr).
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF file not found: {path}")

    data = path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()

    pdf_doc = fitz.open(stream=data, filetype="pdf")
    pages: List[Page] = []
    ocr_pages: List[Tuple[int, np.ndarray]] = []

    try:
        for page_idx in range(len(pdf_doc)):
            fitz_page = pdf_doc[page_idx]
            page_num = page_idx + 1
            width = float(fitz_page.rect.width)
            height = float(fitz_page.rect.height)

            is_clean, result = inspect_pdf_page(fitz_page)
            if is_clean:
                words: List[Word] = result  # type: ignore[assignment]
                page = Page(page_num=page_num, width=width, height=height, words=words)
            else:
                img: np.ndarray = result  # type: ignore[assignment]
                ocr_pages.append((page_num, img))
                page = Page(page_num=page_num, width=width, height=height, words=[])
            pages.append(page)
    finally:
        pdf_doc.close()

    cleaned_pages = deduplicate_headers_footers(pages)
    doc = Document(file_path=str(path), sha256=sha256, pages=cleaned_pages)
    return (doc, ocr_pages)
