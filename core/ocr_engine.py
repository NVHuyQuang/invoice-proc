"""OCR Engine wrapper module.

PLAN 2.1, 2.5:
- PaddleOCR wrapper returning standardized list[Word].
- Singleton / reuse instance across batch to prevent expensive re-initialization.
- Confidence scores recorded on all words; words with conf < OCR_CONFIDENCE_THRESHOLD flagged.
- Per-file error isolation: logs failure to error list without crashing batch.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import numpy as np

from config import OCR_CONFIDENCE_THRESHOLD
from core.types import Word

logger = logging.getLogger(__name__)


class OCRError(Exception):
    """Exception raised for OCR engine failures."""
    pass


class MockPaddleOCR:
    """Mock PaddleOCR engine for testing and headless/non-GPU environments."""

    def __init__(self, sample_results: Optional[Any] = None) -> None:
        self.sample_results = sample_results if sample_results is not None else []
        self.call_count = 0
        self.last_input: Optional[np.ndarray] = None

    def predict(self, input_data: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        self.call_count += 1
        if isinstance(input_data, np.ndarray):
            self.last_input = input_data
        return self.sample_results

    def ocr(self, img: Any, **kwargs: Any) -> Any:
        self.call_count += 1
        return self.sample_results


def _poly_to_bbox(poly: Any) -> Tuple[float, float, float, float]:
    """Convert polygon coordinates or 4-element box to (x0, y0, x1, y1).

    Args:
        poly: Polygon representation:
            - List of 4+ points: [[x0, y0], [x1, y1], [x2, y2], [x3, y3]]
            - Bounding box: [x0, y0, x1, y1]
            - Corresponding numpy arrays

    Returns:
        Tuple of (x0, y0, x1, y1) as floats with x0 <= x1 and y0 <= y1.
    """
    if isinstance(poly, np.ndarray):
        poly = poly.tolist()

    if not poly:
        return (0.0, 0.0, 0.0, 0.0)

    # Flat 4-coordinate bounding box [x0, y0, x1, y1]
    if len(poly) == 4 and not isinstance(poly[0], (list, tuple, np.ndarray)):
        x0, y0, x1, y1 = poly
        return (
            float(min(x0, x1)),
            float(min(y0, y1)),
            float(max(x0, x1)),
            float(max(y0, y1)),
        )

    # List of 2D points [[x, y], ...]
    try:
        xs = [float(pt[0]) for pt in poly]
        ys = [float(pt[1]) for pt in poly]
        return (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))
    except (IndexError, TypeError, ValueError):
        return (0.0, 0.0, 0.0, 0.0)


class OCREngine:
    """Wrapper around OCR backend producing normalized Word tokens.

    Supports PaddleOCR v3 (paddlex pipeline) and v2, engine reuse/caching across batch,
    per-file error isolation, and confidence scoring.
    """

    _shared_backends: Dict[str, Any] = {}
    _instances: Dict[str, "OCREngine"] = {}
    _class_lock: threading.Lock = threading.Lock()

    def __init__(
        self,
        lang: str = "en",
        engine: Optional[Any] = None,
        use_shared_engine: bool = True,
        mock: bool = False,
    ) -> None:
        """Initialize OCREngine wrapper.

        Args:
            lang: Language code for OCR (default 'en').
            engine: Pre-initialized backend engine or mock.
            use_shared_engine: Whether to reuse shared backend across instances.
            mock: If True, uses built-in MockPaddleOCR instead of live backend.
        """
        self.lang = lang
        self._engine = engine
        self.use_shared_engine = use_shared_engine
        self.mock = mock
        self.errors: List[Dict[str, Any]] = []
        self._lock: threading.Lock = threading.Lock()

        if self.mock and self._engine is None:
            self._engine = MockPaddleOCR()

        if self._engine is None and not self.mock and self.use_shared_engine and self.lang in self._shared_backends:
            self._engine = self._shared_backends[self.lang]

    @classmethod
    def get_instance(cls, lang: str = "en", **kwargs: Any) -> "OCREngine":
        """Get or create a cached singleton OCREngine instance for a given language."""
        with cls._class_lock:
            if lang not in cls._instances:
                inst = cls(lang=lang, **kwargs)
                inst.initialize()
                cls._instances[lang] = inst
            return cls._instances[lang]

    @classmethod
    def clear_cache(cls) -> None:
        """Clear shared backend and instance caches."""
        with cls._class_lock:
            cls._shared_backends.clear()
            cls._instances.clear()

    def initialize(self, mock_fallback: bool = False) -> None:
        """Initialize OCR engine once for the batch.

        Args:
            mock_fallback: Fall back to MockPaddleOCR if backend loading fails.
        """
        with self._lock:
            if self._engine is not None:
                return

            if self.mock:
                self._engine = MockPaddleOCR()
                return

            try:
                from paddleocr import PaddleOCR

                # PLAN 2.1 PaddleOCR v3 configuration
                try:
                    backend = PaddleOCR(
                        lang=self.lang,
                        use_doc_orientation_classify=True,
                        use_doc_unwarping=False,
                        use_textline_orientation=True,
                    )
                except TypeError:
                    # PLAN 2.1 fallback for v2.x
                    try:
                        backend = PaddleOCR(
                            lang=self.lang,
                            use_angle_cls=True,
                            show_log=False,
                        )
                    except TypeError:
                        backend = PaddleOCR(lang=self.lang)

                self._engine = backend
                if self.use_shared_engine:
                    OCREngine._shared_backends[self.lang] = backend
                logger.info("Initialized PaddleOCR engine (lang=%s)", self.lang)

            except ImportError as e:
                if mock_fallback:
                    logger.warning("PaddleOCR not installed; falling back to MockPaddleOCR: %s", e)
                    self._engine = MockPaddleOCR()
                else:
                    raise RuntimeError("PaddleOCR is not installed. Install paddleocr or provide mock=True.") from e
            except Exception as e:
                if mock_fallback:
                    logger.warning("Failed to initialize PaddleOCR (%s); falling back to MockPaddleOCR", e)
                    self._engine = MockPaddleOCR()
                else:
                    raise RuntimeError(f"Failed to initialize PaddleOCR: {e}") from e

    def predict(
        self,
        img: np.ndarray,
        page_num: int = 1,
        raise_on_error: bool = False,
    ) -> List[Word]:
        """Run OCR on image array and return list of normalized Word tokens.

        Isolates errors per file/call without crashing the batch unless raise_on_error=True.

        Args:
            img: RGB or BGR numpy array.
            page_num: Page index for provenance (1-indexed).
            raise_on_error: If True, re-raises errors as OCRError instead of returning [].

        Returns:
            List of Word instances with source='ocr'.
        """
        with self._lock:
            try:
                if self._engine is None:
                    self.initialize()

                if not isinstance(img, np.ndarray):
                    raise TypeError(f"Expected img to be np.ndarray, got {type(img).__name__}")
                if img.size == 0:
                    raise ValueError("Image array is empty (size == 0)")

                raw_res = self._call_backend(img)
                words = self._parse_results(raw_res, page_num=page_num)
                return words

            except Exception as e:
                err_record = {
                    "page_num": page_num,
                    "error": str(e),
                    "exception_type": type(e).__name__,
                }
                self.errors.append(err_record)
                logger.error("OCR prediction failed for page %s: %s", page_num, e)

                if raise_on_error:
                    raise OCRError(f"OCR prediction failed for page {page_num}: {e}") from e
                return []


    def _call_backend(self, img: np.ndarray) -> Any:
        """Call underlying OCR backend (predict, ocr, or callable)."""
        if self._engine is not None:
            if hasattr(self._engine, "predict"):
                return self._engine.predict(img)
            if hasattr(self._engine, "ocr"):
                return self._engine.ocr(img)
            if callable(self._engine):
                return self._engine(img)
        raise TypeError(f"Unsupported OCR engine backend: {type(self._engine)}")

    def _parse_results(self, raw_res: Any, page_num: int) -> List[Word]:
        """Normalize raw OCR outputs into standardized List[Word]."""
        words: List[Word] = []

        if raw_res is None:
            return words

        # Unpack generator if necessary
        if not isinstance(raw_res, (list, tuple, dict)):
            try:
                raw_res = list(raw_res)
            except TypeError:
                pass

        if not raw_res:
            return words

        # Case 1: Dict-like result or list of dicts (PaddleOCR v3 paddlex OCRResult)
        item: Any = raw_res
        if isinstance(raw_res, (list, tuple)) and len(raw_res) > 0:
            if isinstance(raw_res[0], dict) or hasattr(raw_res[0], "get"):
                item = raw_res[0]

        if isinstance(item, dict) or hasattr(item, "get"):
            texts = item.get("rec_texts") or []
            scores = item.get("rec_scores") or []
            polys = item.get("rec_polys")
            if polys is None:
                polys = item.get("rec_boxes") or []

            # If scores is numpy array, convert to list
            if isinstance(scores, np.ndarray):
                scores = scores.tolist()
            if isinstance(polys, np.ndarray):
                polys = polys.tolist()

            for idx, text in enumerate(texts):
                text_str = str(text).strip()
                if not text_str:
                    continue

                score = float(scores[idx]) if idx < len(scores) else 1.0
                conf = max(0.0, min(1.0, score))
                poly = polys[idx] if idx < len(polys) else (0.0, 0.0, 0.0, 0.0)
                bbox = _poly_to_bbox(poly)

                words.append(
                    Word(
                        text=text_str,
                        bbox=bbox,
                        conf=conf,
                        page=page_num,
                        source="ocr",
                    )
                )
            return words

        # Case 2: PaddleOCR v2 format: list of pages -> list of lines -> [poly, (text, conf)]
        # or flat list of lines
        lines: Any = raw_res
        if isinstance(raw_res, (list, tuple)) and len(raw_res) > 0:
            if isinstance(raw_res[0], (list, tuple)) and len(raw_res[0]) > 0:
                # If first element is a list whose first element is [poly, (text, conf)]
                first_elem = raw_res[0]
                if isinstance(first_elem[0], (list, tuple)) and len(first_elem[0]) == 2:
                    lines = first_elem

        for entry in lines:
            if entry is None:
                continue
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                poly, text_conf = entry
                if isinstance(text_conf, (list, tuple)) and len(text_conf) >= 2:
                    text_val = text_conf[0]
                    score_val = float(text_conf[1])
                elif isinstance(text_conf, (list, tuple)) and len(text_conf) == 1:
                    text_val = text_conf[0]
                    score_val = 1.0
                else:
                    text_val = text_conf
                    score_val = 1.0

                text_str = str(text_val).strip()
                if not text_str:
                    continue

                conf = max(0.0, min(1.0, score_val))
                bbox = _poly_to_bbox(poly)

                words.append(
                    Word(
                        text=text_str,
                        bbox=bbox,
                        conf=conf,
                        page=page_num,
                        source="ocr",
                    )
                )

        return words

    @staticmethod
    def is_low_confidence(word: Word, threshold: float = OCR_CONFIDENCE_THRESHOLD) -> bool:
        """Check if a word's confidence is below threshold."""
        return word.conf < threshold

    @staticmethod
    def get_low_confidence_words(
        words: List[Word],
        threshold: float = OCR_CONFIDENCE_THRESHOLD,
    ) -> List[Word]:
        """Filter words whose confidence score is below threshold."""
        return [w for w in words if w.conf < threshold]

    def clear_errors(self) -> None:
        """Clear recorded errors."""
        self.errors.clear()
