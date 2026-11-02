"""OCR Engine wrapper module.

PLAN 2.1, 2.5:
- PaddleOCR wrapper returning standardized list[Word].
- Singleton / reuse instance across batch to prevent expensive re-initialization.
- Confidence scores recorded on all words; words with conf < OCR_CONFIDENCE_THRESHOLD flagged.
- Per-file error isolation: logs failure to error list without crashing batch.
"""

from typing import List, Optional
import numpy as np
from core.types import Word


class OCREngine:
    """Wrapper around OCR backend producing normalized Word tokens."""

    def __init__(self, lang: str = "en") -> None:
        self.lang = lang
        self._engine = None

    def initialize(self) -> None:
        """Initialize OCR engine once."""
        raise NotImplementedError("W1-ocr-engine implementation pending")

    def predict(self, img: np.ndarray, page_num: int = 1) -> List[Word]:
        """Run OCR on image array and return list of Word tokens.

        Args:
            img: RGB or BGR numpy array.
            page_num: Page index for provenance.

        Returns:
            List of Word instances with source='ocr'.
        """
        raise NotImplementedError("W1-ocr-engine implementation pending")
