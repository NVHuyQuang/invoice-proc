"""Unit tests for core/ocr_engine.py.

Invariants:
- NEVER access real invoice files.
- NEVER make live network requests.
- All tests use synthetic/mock data.
"""

from typing import Any, Dict, List
import numpy as np
import pytest

from config import OCR_CONFIDENCE_THRESHOLD
from core.ocr_engine import (
    MockPaddleOCR,
    OCREngine,
    OCRError,
    _poly_to_bbox,
)
from core.types import Word

try:
    import paddleocr
    PADDLEOCR_AVAILABLE = True
except (ImportError, Exception):
    PADDLEOCR_AVAILABLE = False


@pytest.fixture(autouse=True)
def clean_engine_cache():
    """Ensure clean singleton and shared backend state for each test."""
    OCREngine.clear_cache()
    yield
    OCREngine.clear_cache()


@pytest.fixture
def dummy_img() -> np.ndarray:
    """Synthetic dummy RGB image array."""
    return np.ones((100, 200, 3), dtype=np.uint8) * 255


class TestPolyToBbox:
    """Test geometry conversion from polygons to (x0, y0, x1, y1)."""

    def test_four_point_polygon_list(self):
        poly = [[10.0, 20.0], [80.0, 20.0], [80.0, 50.0], [10.0, 50.0]]
        bbox = _poly_to_bbox(poly)
        assert bbox == (10.0, 20.0, 80.0, 50.0)

    def test_flat_four_coordinate_box(self):
        poly = [15.5, 25.0, 95.5, 60.0]
        bbox = _poly_to_bbox(poly)
        assert bbox == (15.5, 25.0, 95.5, 60.0)

    def test_inverted_coordinates_ordered(self):
        poly = [95.5, 60.0, 15.5, 25.0]
        bbox = _poly_to_bbox(poly)
        assert bbox == (15.5, 25.0, 95.5, 60.0)

    def test_numpy_array_polygon(self):
        poly = np.array([[10, 20], [80, 20], [80, 50], [10, 50]])
        bbox = _poly_to_bbox(poly)
        assert bbox == (10.0, 20.0, 80.0, 50.0)

    def test_empty_or_malformed(self):
        assert _poly_to_bbox([]) == (0.0, 0.0, 0.0, 0.0)
        assert _poly_to_bbox(None) == (0.0, 0.0, 0.0, 0.0)


class TestOCREngineMapping:
    """Test normalization of PaddleOCR results to List[Word]."""

    def test_paddle_v3_predict_mapping(self, dummy_img):
        """PaddleOCR v3 returns rec_texts, rec_scores, rec_polys."""
        v3_results = [
            {
                "rec_texts": ["INVOICE", "Total", "125.50", "   "],
                "rec_scores": [0.98, 0.95, 0.85, 0.70],
                "rec_polys": [
                    [[10.0, 10.0], [50.0, 10.0], [50.0, 25.0], [10.0, 25.0]],
                    [[10.0, 30.0], [45.0, 30.0], [45.0, 45.0], [10.0, 45.0]],
                    np.array([[50.0, 30.0], [90.0, 30.0], [90.0, 45.0], [50.0, 45.0]]),
                    [[0, 0], [1, 0], [1, 1], [0, 1]],
                ],
            }
        ]
        mock_backend = MockPaddleOCR(sample_results=v3_results)
        engine = OCREngine(engine=mock_backend)

        words = engine.predict(dummy_img, page_num=2)

        # Whitespace-only string "   " must be filtered out
        assert len(words) == 3

        # Word 1: "INVOICE"
        w0 = words[0]
        assert isinstance(w0, Word)
        assert w0.text == "INVOICE"
        assert w0.bbox == (10.0, 10.0, 50.0, 25.0)
        assert pytest.approx(w0.conf, rel=1e-3) == 0.98
        assert w0.page == 2
        assert w0.source == "ocr"

        # Word 2: "Total"
        w1 = words[1]
        assert w1.text == "Total"
        assert w1.bbox == (10.0, 30.0, 45.0, 45.0)
        assert pytest.approx(w1.conf, rel=1e-3) == 0.95
        assert w1.page == 2
        assert w1.source == "ocr"

        # Word 3: "125.50"
        w2 = words[2]
        assert w2.text == "125.50"
        assert w2.bbox == (50.0, 30.0, 90.0, 45.0)
        assert pytest.approx(w2.conf, rel=1e-3) == 0.85
        assert w2.page == 2
        assert w2.source == "ocr"

    def test_paddle_v3_with_rec_boxes(self, dummy_img):
        """PaddleOCR v3 returning rec_boxes instead of rec_polys."""
        v3_results = [
            {
                "rec_texts": ["SUBTOTAL"],
                "rec_scores": [0.92],
                "rec_boxes": [[20.0, 30.0, 80.0, 45.0]],
            }
        ]
        mock_backend = MockPaddleOCR(sample_results=v3_results)
        engine = OCREngine(engine=mock_backend)

        words = engine.predict(dummy_img, page_num=1)
        assert len(words) == 1
        assert words[0].text == "SUBTOTAL"
        assert words[0].bbox == (20.0, 30.0, 80.0, 45.0)
        assert pytest.approx(words[0].conf, rel=1e-3) == 0.92
        assert words[0].source == "ocr"

    def test_paddle_v2_ocr_format_mapping(self, dummy_img):
        """PaddleOCR v2 format: list of pages with [poly, (text, conf)]."""
        v2_results = [
            [
                [[[10, 10], [90, 10], [90, 30], [10, 30]], ("COFFEE", 0.97)],
                [[[100, 10], [150, 10], [150, 30], [100, 30]], ("4.50", 0.89)],
            ]
        ]
        mock_backend = MockPaddleOCR(sample_results=v2_results)
        engine = OCREngine(engine=mock_backend)

        words = engine.predict(dummy_img, page_num=1)
        assert len(words) == 2
        assert words[0].text == "COFFEE"
        assert words[0].bbox == (10.0, 10.0, 90.0, 30.0)
        assert pytest.approx(words[0].conf, rel=1e-3) == 0.97
        assert words[0].source == "ocr"

        assert words[1].text == "4.50"
        assert pytest.approx(words[1].conf, rel=1e-3) == 0.89
        assert words[1].source == "ocr"

    def test_empty_and_none_outputs(self, dummy_img):
        """When OCR finds no text or returns empty/None results."""
        engine = OCREngine(mock=True)

        # None output
        engine._engine = MockPaddleOCR(sample_results=None)
        assert engine.predict(dummy_img) == []

        # Empty list
        engine._engine = MockPaddleOCR(sample_results=[])
        assert engine.predict(dummy_img) == []

        # List with None (Paddle v2 empty result)
        engine._engine = MockPaddleOCR(sample_results=[None])
        assert engine.predict(dummy_img) == []

        # v3 result with empty rec_texts
        engine._engine = MockPaddleOCR(sample_results=[{"rec_texts": [], "rec_scores": []}])
        assert engine.predict(dummy_img) == []


class TestConfidenceFlagging:
    """Test confidence evaluation against OCR_CONFIDENCE_THRESHOLD."""

    def test_confidence_threshold_value(self):
        assert OCR_CONFIDENCE_THRESHOLD == 0.90

    def test_is_low_confidence(self):
        high_word = Word(text="100.00", bbox=(0, 0, 10, 10), conf=0.95, page=1, source="ocr")
        exact_thresh_word = Word(text="100.00", bbox=(0, 0, 10, 10), conf=0.90, page=1, source="ocr")
        low_word = Word(text="100.00", bbox=(0, 0, 10, 10), conf=0.89, page=1, source="ocr")

        assert OCREngine.is_low_confidence(high_word) is False
        assert OCREngine.is_low_confidence(exact_thresh_word) is False
        assert OCREngine.is_low_confidence(low_word) is True

    def test_get_low_confidence_words(self):
        w1 = Word(text="Apple", bbox=(0, 0, 10, 10), conf=0.99, page=1, source="ocr")
        w2 = Word(text="0.99", bbox=(0, 0, 10, 10), conf=0.88, page=1, source="ocr")
        w3 = Word(text="Tax", bbox=(0, 0, 10, 10), conf=0.75, page=1, source="ocr")

        lows = OCREngine.get_low_confidence_words([w1, w2, w3])
        assert lows == [w2, w3]


class TestEngineLifecycleAndReuse:
    """Test singleton and batch reuse: initialize once for whole batch."""

    def test_engine_reuse_across_instances(self):
        mock_backend = MockPaddleOCR()
        engine1 = OCREngine(lang="en", engine=mock_backend, use_shared_engine=True)
        OCREngine._shared_backends["en"] = mock_backend

        engine2 = OCREngine(lang="en", use_shared_engine=True)
        assert engine2._engine is mock_backend

    def test_get_instance_singleton(self):
        inst1 = OCREngine.get_instance(lang="en", mock=True)
        inst2 = OCREngine.get_instance(lang="en", mock=True)
        assert inst1 is inst2

    def test_clear_cache(self):
        OCREngine._shared_backends["en"] = "backend"
        OCREngine._instances["en"] = OCREngine(mock=True)
        OCREngine.clear_cache()
        assert len(OCREngine._shared_backends) == 0
        assert len(OCREngine._instances) == 0

    def test_mock_mode_flag(self, dummy_img):
        engine = OCREngine(mock=True)
        assert isinstance(engine._engine, MockPaddleOCR)
        words = engine.predict(dummy_img)
        assert words == []


class TestErrorIsolation:
    """Test per-file error isolation without crashing the batch."""

    class FailingBackend:
        """Backend that raises an unexpected runtime exception."""

        def predict(self, img, **kwargs):
            raise RuntimeError("Corrupted image memory or CUDA failure")

    def test_predict_isolates_error_without_crashing(self, dummy_img):
        engine = OCREngine(engine=self.FailingBackend())

        # Page 1 fails: must return [] and record error, not crash
        result_p1 = engine.predict(dummy_img, page_num=1)
        assert result_p1 == []
        assert len(engine.errors) == 1
        assert engine.errors[0]["page_num"] == 1
        assert "CUDA failure" in engine.errors[0]["error"]

        # Page 2 with working engine succeeds: batch continues uninterrupted
        engine._engine = MockPaddleOCR(sample_results=[{"rec_texts": ["OK"], "rec_scores": [0.99], "rec_polys": [[[0,0],[1,0],[1,1],[0,1]]]}])
        result_p2 = engine.predict(dummy_img, page_num=2)
        assert len(result_p2) == 1
        assert result_p2[0].text == "OK"

    def test_raise_on_error_mode(self, dummy_img):
        engine = OCREngine(engine=self.FailingBackend())
        with pytest.raises(OCRError, match="OCR prediction failed for page 1"):
            engine.predict(dummy_img, page_num=1, raise_on_error=True)

    def test_invalid_image_type(self):
        engine = OCREngine(mock=True)
        res = engine.predict("not a numpy array", page_num=1)  # type: ignore
        assert res == []
        assert len(engine.errors) == 1
        assert "Expected img to be np.ndarray" in engine.errors[0]["error"]

    def test_empty_image_array(self):
        engine = OCREngine(mock=True)
        res = engine.predict(np.zeros((0, 0, 3), dtype=np.uint8), page_num=1)
        assert res == []
        assert len(engine.errors) == 1
        assert "empty" in engine.errors[0]["error"]

    def test_clear_errors(self, dummy_img):
        engine = OCREngine(engine=self.FailingBackend())
        engine.predict(dummy_img, page_num=1)
        assert len(engine.errors) == 1
        engine.clear_errors()
        assert len(engine.errors) == 0


@pytest.mark.skipif(not PADDLEOCR_AVAILABLE, reason="PaddleOCR not installed")
class TestLivePaddleOCRInit:
    """Test real PaddleOCR initialization when available in environment."""

    def test_paddleocr_initialization(self):
        engine = OCREngine(lang="en", use_shared_engine=False)
        engine.initialize(mock_fallback=True)
        assert engine._engine is not None
