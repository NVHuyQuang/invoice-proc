"""Tests for geometric line reconstruction (PLAN 2.3).

All tests use synthetic bounding boxes to strictly obey the zero-real-invoice invariant.
Tests cover:
- Empty & single-word edge cases
- Standard multi-word horizontal line ordering (L-to-R)
- Top-to-bottom multi-line ordering
- Skewed lines (positive and negative tilt residual)
- Broken lines (wide horizontal gaps, vertical jitter, wrapped text)
- Multi-page documents
- Vertically stacked close lines (avoiding false merges)
"""

import math
import random
from typing import List, Tuple
import pytest

from core.types import Word, Line
from core.layout import reconstruct_lines


def make_word(
    text: str,
    bbox: Tuple[float, float, float, float],
    page: int = 1,
    conf: float = 1.0,
    source: str = "pdf_text"
) -> Word:
    """Helper to create synthetic Word instances."""
    return Word(
        text=text,
        bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
        conf=conf,
        page=page,
        source=source
    )


class TestLayoutBasic:
    """Basic edge cases and single line behaviors."""

    def test_empty_words_returns_empty_list(self):
        lines = reconstruct_lines([], page_height=1000.0, page_width=800.0)
        assert lines == []

    def test_single_word(self):
        word = make_word("Invoice", (100.0, 50.0, 200.0, 70.0), page=1)
        lines = reconstruct_lines([word], page_height=1000.0, page_width=800.0)
        assert len(lines) == 1
        line = lines[0]
        assert line.page == 1
        assert line.y == pytest.approx(60.0)
        assert len(line.cells) == 1
        text, bbox, conf, col_idx = line.cells[0]
        assert text == "Invoice"
        assert bbox == (100.0, 50.0, 200.0, 70.0)
        assert conf == 1.0
        assert col_idx == 0

    def test_horizontal_ordering_left_to_right(self):
        """Words provided in shuffled order on a single line must sort left-to-right."""
        words = [
            make_word("TOTAL", (400.0, 100.0, 480.0, 120.0)),
            make_word("INVOICE", (50.0, 100.0, 150.0, 120.0)),
            make_word("DUE", (250.0, 100.0, 300.0, 120.0)),
        ]
        # Shuffle input to ensure ordering is geometric, not input-order dependent
        random.seed(42)
        shuffled = list(words)
        random.shuffle(shuffled)

        lines = reconstruct_lines(shuffled, page_height=1000.0, page_width=800.0)
        assert len(lines) == 1
        texts = [cell[0] for cell in lines[0].cells]
        assert texts == ["INVOICE", "DUE", "TOTAL"]


class TestLayoutMultiLine:
    """Multi-line top-to-bottom reconstruction."""

    def test_multiple_horizontal_lines_sorted_top_to_bottom(self):
        """Three horizontal lines should be grouped and ordered top-to-bottom."""
        # Line 1 at y in [50, 70]
        line1 = [
            make_word("Vendor", (50.0, 50.0, 120.0, 70.0)),
            make_word("ABC", (130.0, 50.0, 180.0, 70.0)),
        ]
        # Line 2 at y in [100, 120]
        line2 = [
            make_word("Item", (50.0, 100.0, 100.0, 120.0)),
            make_word("Description", (110.0, 100.0, 220.0, 120.0)),
            make_word("15.00", (450.0, 100.0, 500.0, 120.0)),
        ]
        # Line 3 at y in [200, 220]
        line3 = [
            make_word("Total", (50.0, 200.0, 100.0, 220.0)),
            make_word("15.00", (450.0, 200.0, 500.0, 220.0)),
        ]

        all_words = line3 + line1 + line2  # purposely out of order
        lines = reconstruct_lines(all_words, page_height=1000.0, page_width=800.0)

        assert len(lines) == 3
        assert [c[0] for c in lines[0].cells] == ["Vendor", "ABC"]
        assert [c[0] for c in lines[1].cells] == ["Item", "Description", "15.00"]
        assert [c[0] for c in lines[2].cells] == ["Total", "15.00"]

        assert lines[0].y < lines[1].y < lines[2].y

    def test_vertically_stacked_words_do_not_merge(self):
        """Lines that are vertically close and horizontally overlap must NOT merge."""
        # Median height is 20. Lines are separated by 12px center-to-center.
        # Line 1: x in [50, 150], y in [100, 120] -> center y = 110
        # Line 2: x in [50, 150], y in [112, 132] -> center y = 122
        w1 = make_word("Subtotal", (50.0, 100.0, 150.0, 120.0))
        w2 = make_word("Tax", (50.0, 112.0, 150.0, 132.0))

        lines = reconstruct_lines([w1, w2], page_height=1000.0, page_width=800.0)
        assert len(lines) == 2
        assert lines[0].cells[0][0] == "Subtotal"
        assert lines[1].cells[0][0] == "Tax"


class TestLayoutSkew:
    """Skew handling with positive and negative slight angles."""

    def test_positive_skew_grouped_into_lines(self):
        """A page tilted by +2.5 degrees: words on the same line have raw delta Y > threshold,
        but skew compensation correctly groups them."""
        angle_rad = math.radians(2.5)
        slope = math.tan(angle_rad)  # approx 0.04366
        h = 20.0  # median height is 20, threshold is 10.0

        # Line 1 base y=100, spanning from x=50 to x=550
        # At x=50: yc = 100 + 50*slope = 102.18
        # At x=550: yc = 100 + 550*slope = 124.01
        # Raw delta Y between extremes is 21.83 > 10.0 (would fail without skew compensation!)
        cols_l1 = [50.0, 150.0, 300.0, 500.0]
        words_l1 = []
        for c in cols_l1:
            yc = 100.0 + c * slope
            words_l1.append(make_word(f"L1_{int(c)}", (c, yc - h / 2, c + 40.0, yc + h / 2)))

        # Line 2 base y=160
        cols_l2 = [50.0, 200.0, 450.0]
        words_l2 = []
        for c in cols_l2:
            yc = 160.0 + c * slope
            words_l2.append(make_word(f"L2_{int(c)}", (c, yc - h / 2, c + 40.0, yc + h / 2)))

        all_words = words_l2 + words_l1
        lines = reconstruct_lines(all_words, page_height=1000.0, page_width=800.0)

        assert len(lines) == 2
        assert len(lines[0].cells) == 4
        assert [c[0] for c in lines[0].cells] == ["L1_50", "L1_150", "L1_300", "L1_500"]
        assert len(lines[1].cells) == 3
        assert [c[0] for c in lines[1].cells] == ["L2_50", "L2_200", "L2_450"]

    def test_negative_skew_grouped_into_lines(self):
        """A page tilted by -2.0 degrees (upwards to the right)."""
        angle_rad = math.radians(-2.0)
        slope = math.tan(angle_rad)  # approx -0.0349
        h = 18.0

        cols = [60.0, 180.0, 320.0, 480.0]
        words = []
        for c in cols:
            yc = 200.0 + c * slope
            words.append(make_word(f"Word_{int(c)}", (c, yc - h / 2, c + 50.0, yc + h / 2)))

        lines = reconstruct_lines(words, page_height=1000.0, page_width=800.0)
        assert len(lines) == 1
        assert len(lines[0].cells) == 4
        assert [c[0] for c in lines[0].cells] == [f"Word_{int(c)}" for c in cols]


class TestLayoutBrokenLines:
    """Broken lines: wide gaps, vertical jitter, and broken word tokens."""

    def test_broken_line_wide_horizontal_gap(self):
        """A line with item name on the far left and price on the far right (wide gap)."""
        w1 = make_word("Coffee Latte", (50.0, 150.0, 160.0, 170.0))
        # 300px horizontal gap
        w2 = make_word("4.50", (460.0, 150.0, 500.0, 170.0))

        lines = reconstruct_lines([w2, w1], page_height=1000.0, page_width=800.0)
        assert len(lines) == 1
        assert [c[0] for c in lines[0].cells] == ["Coffee Latte", "4.50"]

    def test_broken_line_vertical_jitter(self):
        """Boxes with slight vertical baseline jitter (e.g. descenders, different font styles)
        within 0.5 * median height must remain on the same line."""
        # Median height is 20 -> threshold is 10
        w1 = make_word("Item", (50.0, 100.0, 100.0, 120.0))       # yc = 110
        w2 = make_word("Quality", (110.0, 103.0, 180.0, 123.0))   # yc = 113 (delta 3 < 10)
        w3 = make_word("Grade", (190.0, 98.0, 250.0, 118.0))      # yc = 108 (delta 2 < 10)
        w4 = make_word("A+", (260.0, 101.0, 290.0, 121.0))        # yc = 111 (delta 1 < 10)

        lines = reconstruct_lines([w3, w1, w4, w2], page_height=1000.0, page_width=800.0)
        assert len(lines) == 1
        assert [c[0] for c in lines[0].cells] == ["Item", "Quality", "Grade", "A+"]

    def test_broken_line_split_tokens(self):
        """OCR engine splitting a single phrase into adjacent partial tokens."""
        w1 = make_word("Invo", (50.0, 100.0, 90.0, 120.0))
        w2 = make_word("ice", (91.0, 100.0, 120.0, 120.0))
        w3 = make_word("No:", (125.0, 100.0, 160.0, 120.0))
        w4 = make_word("12345", (170.0, 100.0, 220.0, 120.0))

        lines = reconstruct_lines([w4, w2, w1, w3], page_height=1000.0, page_width=800.0)
        assert len(lines) == 1
        assert [c[0] for c in lines[0].cells] == ["Invo", "ice", "No:", "12345"]


class TestLayoutMultiPage:
    """Multi-page document handling."""

    def test_multi_page_words_separated_and_ordered(self):
        """Words across page 1 and page 2 must be partitioned by page,
        page 1 first, page 2 second, each sorted top-to-bottom."""
        # Page 1 words
        p1_l1 = make_word("Page1_Header", (50.0, 50.0, 150.0, 70.0), page=1)
        p1_l2 = make_word("Page1_Body", (50.0, 200.0, 150.0, 220.0), page=1)

        # Page 2 words
        p2_l1 = make_word("Page2_Header", (50.0, 50.0, 150.0, 70.0), page=2)
        p2_l2 = make_word("Page2_Body", (50.0, 200.0, 150.0, 220.0), page=2)

        # Mixed input list
        mixed = [p2_l2, p1_l1, p2_l1, p1_l2]
        lines = reconstruct_lines(mixed, page_height=1000.0, page_width=800.0)

        assert len(lines) == 4
        # Page 1 lines first
        assert lines[0].page == 1
        assert lines[0].cells[0][0] == "Page1_Header"
        assert lines[1].page == 1
        assert lines[1].cells[0][0] == "Page1_Body"

        # Page 2 lines second
        assert lines[2].page == 2
        assert lines[2].cells[0][0] == "Page2_Header"
        assert lines[3].page == 2
        assert lines[3].cells[0][0] == "Page2_Body"

    def test_multi_page_skew_independent_per_page(self):
        """Page 1 has no skew, Page 2 has slight skew; each page calculates its own slope."""
        # Page 1 (flat)
        p1_words = [
            make_word("P1_A", (50.0, 100.0, 100.0, 120.0), page=1),
            make_word("P1_B", (300.0, 100.0, 350.0, 120.0), page=1),
        ]

        # Page 2 (tilted by ~2 degrees)
        slope = math.tan(math.radians(2.0))
        p2_words = [
            make_word("P2_A", (50.0, 100.0 + 50.0 * slope, 100.0, 120.0 + 50.0 * slope), page=2),
            make_word("P2_B", (400.0, 100.0 + 400.0 * slope, 450.0, 120.0 + 400.0 * slope), page=2),
        ]

        lines = reconstruct_lines(p1_words + p2_words, page_height=1000.0, page_width=800.0)
        assert len(lines) == 2
        assert lines[0].page == 1
        assert [c[0] for c in lines[0].cells] == ["P1_A", "P1_B"]
        assert lines[1].page == 2
        assert [c[0] for c in lines[1].cells] == ["P2_A", "P2_B"]


class TestLayoutRobustness:
    """Robustness against degenerate geometries and unusual inputs."""

    def test_degenerate_bounding_box(self):
        """Words with zero or minimal height do not crash the median/clustering logic."""
        w1 = make_word("ZeroHeight", (50.0, 100.0, 100.0, 100.0))
        w2 = make_word("Normal", (110.0, 95.0, 160.0, 115.0))
        lines = reconstruct_lines([w1, w2], page_height=1000.0, page_width=800.0)
        assert len(lines) >= 1

    def test_table_column_vertical_alignment(self):
        """Vertical column of 4 numbers should form 4 separate lines."""
        numbers = ["10.00", "25.50", "30.00", "100.00"]
        words = []
        for idx, num in enumerate(numbers):
            y = 100.0 + idx * 40.0
            words.append(make_word(num, (400.0, y, 460.0, y + 20.0)))

        lines = reconstruct_lines(words, page_height=1000.0, page_width=800.0)
        assert len(lines) == 4
        for idx, line in enumerate(lines):
            assert line.cells[0][0] == numbers[idx]
