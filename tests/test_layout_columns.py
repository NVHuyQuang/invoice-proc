"""Tests for core/layout_columns.py (PLAN 2.4).

Verifies:
- Multi-column tables (bảng nhiều cột) with numeric clusters and missing columns
- Two parallel columns (hai cột song song)
- Gradually drifting/skewed columns (cột lệch dần)
- Multi-word cells within columns
- Empty lines, edge cases, multi-page independence
- format_lines_as_text column separation
"""

import pytest
from core.layout_columns import assign_columns, format_lines_as_text, is_numeric_token
from core.types import Line


class TestNumericTokenDetection:
    """Test is_numeric_token recognition."""

    def test_integers_and_decimals(self):
        assert is_numeric_token("123") is True
        assert is_numeric_token("3.50") is True
        assert is_numeric_token("1,234.56") is True
        assert is_numeric_token("0.05") is True

    def test_currency_and_brackets(self):
        assert is_numeric_token("$12.50") is True
        assert is_numeric_token("€99.00") is True
        assert is_numeric_token("(15.00)") is True
        assert is_numeric_token("-5.00") is True
        assert is_numeric_token("+10.00") is True

    def test_dates_and_codes(self):
        assert is_numeric_token("2026-08-01") is True
        assert is_numeric_token("08/15/2026") is True
        assert is_numeric_token("12:30:00") is True

    def test_non_numeric(self):
        assert is_numeric_token("Apples") is False
        assert is_numeric_token("Widget Alpha") is False
        assert is_numeric_token("PO-9988") is False
        assert is_numeric_token("") is False
        assert is_numeric_token("   ") is False


class TestMultiColumnTable:
    """Test detection and assignment for multi-column tables (bảng nhiều cột)."""

    def test_standard_four_column_table(self):
        lines = [
            Line(
                page=1,
                y=100.0,
                cells=[
                    ("Item Description", (50, 95, 180, 115), 1.0, 0),
                    ("Qty", (290, 95, 310, 115), 1.0, 0),
                    ("Unit Price", (375, 95, 425, 115), 1.0, 0),
                    ("Total", (480, 95, 510, 115), 1.0, 0),
                ],
            ),
            Line(
                page=1,
                y=120.0,
                cells=[
                    ("Fresh Organic Apples", (50, 115, 190, 135), 1.0, 0),
                    ("2", (295, 115, 305, 135), 1.0, 0),
                    ("3.50", (385, 115, 410, 135), 1.0, 0),
                    ("7.00", (485, 115, 510, 135), 1.0, 0),
                ],
            ),
            Line(
                page=1,
                y=140.0,
                cells=[
                    ("Whole Milk 1 Gallon", (50, 135, 185, 155), 1.0, 0),
                    ("1", (295, 135, 305, 155), 1.0, 0),
                    ("4.25", (385, 135, 410, 155), 1.0, 0),
                    ("4.25", (485, 135, 510, 155), 1.0, 0),
                ],
            ),
            Line(
                page=1,
                y=160.0,
                cells=[
                    ("Artisan Sourdough Bread", (50, 155, 195, 175), 1.0, 0),
                    ("3", (295, 155, 305, 175), 1.0, 0),
                    ("5.00", (385, 155, 410, 175), 1.0, 0),
                    ("15.00", (480, 155, 510, 175), 1.0, 0),
                ],
            ),
        ]

        result = assign_columns(lines, page_width=600.0)
        assert len(result) == 4

        # Verify col_idx for each line
        for line in result:
            col_indices = [c[3] for c in line.cells]
            assert col_indices == [0, 1, 2, 3]

        # Verify format_lines_as_text
        text = format_lines_as_text(result)
        expected_lines = [
            "Item Description | Qty | Unit Price | Total",
            "Fresh Organic Apples | 2 | 3.50 | 7.00",
            "Whole Milk 1 Gallon | 1 | 4.25 | 4.25",
            "Artisan Sourdough Bread | 3 | 5.00 | 15.00",
        ]
        assert text == "\n".join(expected_lines)

    def test_multi_column_table_with_missing_columns(self):
        """Discount row only has Description and Total, skipping Qty and Price."""
        lines = [
            Line(
                page=1,
                y=100.0,
                cells=[
                    ("Item", (50, 95, 120, 115), 1.0, 0),
                    ("Qty", (290, 95, 310, 115), 1.0, 0),
                    ("Price", (380, 95, 410, 115), 1.0, 0),
                    ("Total", (480, 95, 510, 115), 1.0, 0),
                ],
            ),
            Line(
                page=1,
                y=120.0,
                cells=[
                    ("Product A", (50, 115, 130, 135), 1.0, 0),
                    ("2", (295, 115, 305, 135), 1.0, 0),
                    ("10.00", (380, 115, 415, 135), 1.0, 0),
                    ("20.00", (480, 115, 515, 135), 1.0, 0),
                ],
            ),
            Line(
                page=1,
                y=140.0,
                cells=[
                    ("Loyalty Discount", (50, 135, 150, 155), 1.0, 0),
                    ("-5.00", (480, 135, 515, 155), 1.0, 0),
                ],
            ),
        ]

        result = assign_columns(lines, page_width=600.0)
        # In discount row, Loyalty Discount should be col 0, and -5.00 should be col 3
        discount_cols = [c[3] for c in result[2].cells]
        assert discount_cols == [0, 3]

        text = format_lines_as_text(result)
        assert "Loyalty Discount | -5.00" in text

    def test_multi_word_cells_in_column(self):
        """Individual words within the description column must share col_idx=0."""
        lines = [
            Line(
                page=1,
                y=100.0,
                cells=[
                    ("Item", (50, 95, 80, 115), 1.0, 0),
                    ("Desc", (85, 95, 120, 115), 1.0, 0),
                    ("Qty", (290, 95, 310, 115), 1.0, 0),
                    ("Price", (380, 95, 410, 115), 1.0, 0),
                ],
            ),
            Line(
                page=1,
                y=120.0,
                cells=[
                    ("Fresh", (50, 115, 80, 135), 1.0, 0),
                    ("Organic", (85, 115, 130, 135), 1.0, 0),
                    ("Fuji", (135, 115, 160, 135), 1.0, 0),
                    ("Apples", (165, 115, 205, 135), 1.0, 0),
                    ("4", (295, 115, 305, 135), 1.0, 0),
                    ("2.50", (385, 115, 410, 135), 1.0, 0),
                ],
            ),
        ]

        result = assign_columns(lines, page_width=600.0)
        # All 4 words of the description should have col_idx=0
        item_words = result[1].cells[:4]
        for w in item_words:
            assert w[3] == 0
        assert result[1].cells[4][3] == 1  # Qty
        assert result[1].cells[5][3] == 2  # Price

        text = format_lines_as_text(result)
        assert "Fresh Organic Fuji Apples | 4 | 2.50" in text


class TestTwoParallelColumns:
    """Test detection and assignment for two parallel columns (hai cột song song)."""

    def test_two_parallel_columns_headers(self):
        lines = [
            Line(
                page=1,
                y=100.0,
                cells=[
                    ("Vendor: ACME Corporation", (50, 95, 220, 115), 1.0, 0),
                    ("Invoice Date: 2026-08-01", (350, 95, 520, 115), 1.0, 0),
                ],
            ),
            Line(
                page=1,
                y=120.0,
                cells=[
                    ("Address: 123 Main Street", (50, 115, 210, 135), 1.0, 0),
                    ("Due Date: 2026-08-15", (350, 115, 500, 135), 1.0, 0),
                ],
            ),
            Line(
                page=1,
                y=140.0,
                cells=[
                    ("City: Seattle, WA 98101", (50, 135, 200, 155), 1.0, 0),
                    ("Terms: Net 15 Days", (350, 135, 480, 155), 1.0, 0),
                ],
            ),
            Line(
                page=1,
                y=160.0,
                cells=[
                    ("Contact: accounts@acme.com", (50, 155, 230, 175), 1.0, 0),
                    ("P.O. Number: PO-8842", (350, 155, 490, 175), 1.0, 0),
                ],
            ),
        ]

        result = assign_columns(lines, page_width=600.0)
        assert len(result) == 4

        for line in result:
            assert len(line.cells) == 2
            assert line.cells[0][3] == 0  # Left column
            assert line.cells[1][3] == 1  # Right column

        text = format_lines_as_text(result)
        expected = [
            "Vendor: ACME Corporation | Invoice Date: 2026-08-01",
            "Address: 123 Main Street | Due Date: 2026-08-15",
            "City: Seattle, WA 98101 | Terms: Net 15 Days",
            "Contact: accounts@acme.com | P.O. Number: PO-8842",
        ]
        assert text == "\n".join(expected)


class TestDriftingColumns:
    """Test detection and assignment for gradually drifting/skewed columns (cột lệch dần)."""

    def test_linearly_drifting_columns(self):
        """Simulate a scanned document tilted by ~0.15 dx/dy drift across 6 rows."""
        lines = []
        for i in range(6):
            y_base = 100.0 + i * 20.0
            dx = i * 3.5  # 3.5 px drift per row, cumulative ~17.5 px
            lines.append(
                Line(
                    page=1,
                    y=y_base,
                    cells=[
                        (f"Item {i+1}", (50.0 + dx, y_base - 5, 120.0 + dx, y_base + 15), 1.0, 0),
                        (f"{i+1}", (300.0 + dx, y_base - 5, 310.0 + dx, y_base + 15), 1.0, 0),
                        (f"1{i}.50", (400.0 + dx, y_base - 5, 435.0 + dx, y_base + 15), 1.0, 0),
                    ],
                )
            )

        result = assign_columns(lines, page_width=600.0)
        assert len(result) == 6

        # In every drifting row, columns must be correctly assigned to 0, 1, 2
        for i, line in enumerate(result):
            col_indices = [c[3] for c in line.cells]
            assert col_indices == [0, 1, 2], f"Failed at drifting row {i}: {col_indices}"

        text = format_lines_as_text(result)
        formatted_rows = text.split("\n")
        assert len(formatted_rows) == 6
        for i, row_str in enumerate(formatted_rows):
            assert f"Item {i+1} | {i+1} | 1{i}.50" == row_str


class TestEdgeCasesAndIndependence:
    """Test edge cases: empty lists, single lines, multi-page layout."""

    def test_empty_lines(self):
        assert assign_columns([], page_width=600.0) == []
        assert format_lines_as_text([]) == ""

    def test_single_column_line(self):
        lines = [
            Line(page=1, y=50.0, cells=[("INVOICE SUMMARY", (200, 45, 350, 65), 1.0, 0)])
        ]
        result = assign_columns(lines, page_width=600.0)
        assert result[0].cells[0][3] == 0
        assert format_lines_as_text(result) == "INVOICE SUMMARY"

    def test_line_with_empty_cells_or_whitespace(self):
        lines = [
            Line(
                page=1,
                y=100.0,
                cells=[
                    ("   ", (50, 95, 60, 115), 1.0, 0),
                    ("Valid Text", (100, 95, 180, 115), 1.0, 0),
                ],
            )
        ]
        result = assign_columns(lines, page_width=600.0)
        text = format_lines_as_text(result)
        assert text == "Valid Text"

    def test_multi_page_independence(self):
        """Page 1 has 2 parallel columns, Page 2 has a 3-column table."""
        lines = [
            # Page 1
            Line(
                page=1,
                y=100.0,
                cells=[
                    ("Bill To: Alpha", (50, 95, 180, 115), 1.0, 0),
                    ("Ship To: Beta", (350, 95, 480, 115), 1.0, 0),
                ],
            ),
            Line(
                page=1,
                y=120.0,
                cells=[
                    ("123 Main St", (50, 115, 160, 135), 1.0, 0),
                    ("456 Oak Ave", (350, 115, 460, 135), 1.0, 0),
                ],
            ),
            # Page 2
            Line(
                page=2,
                y=100.0,
                cells=[
                    ("Product", (50, 95, 120, 115), 1.0, 0),
                    ("Qty", (250, 95, 270, 115), 1.0, 0),
                    ("Total", (400, 95, 440, 115), 1.0, 0),
                ],
            ),
            Line(
                page=2,
                y=120.0,
                cells=[
                    ("Gadget", (50, 115, 100, 135), 1.0, 0),
                    ("10", (250, 115, 265, 135), 1.0, 0),
                    ("100.00", (400, 115, 440, 135), 1.0, 0),
                ],
            ),
        ]

        result = assign_columns(lines, page_width=600.0)
        # Page 1 lines should have 2 columns (0, 1)
        assert [c[3] for c in result[0].cells] == [0, 1]
        assert [c[3] for c in result[1].cells] == [0, 1]

        # Page 2 lines should have 3 columns (0, 1, 2)
        assert [c[3] for c in result[2].cells] == [0, 1, 2]
        assert [c[3] for c in result[3].cells] == [0, 1, 2]

    def test_format_lines_as_text_without_preassigned_cols(self):
        """format_lines_as_text falls back to horizontal distance threshold."""
        lines = [
            Line(
                page=1,
                y=100.0,
                cells=[
                    ("Hello", (50, 95, 80, 115), 1.0, 0),
                    ("World", (85, 95, 115, 115), 1.0, 0),
                    ("Column2", (300, 95, 350, 115), 1.0, 0),
                ],
            )
        ]
        text = format_lines_as_text(lines)
        assert text == "Hello World | Column2"
