"""Tests for excel_safety module.

Verifies:
- Formula injection payloads with dangerous prefixes (=, +, -, @, \\t, \\r) are neutralized.
- Non-string values (numbers, booleans, dates, None) remain intact.
- Safe strings are not modified.
- Atomic workbook saving creates valid Excel files without leaving temporary garbage files.
- Atomic saving cleans up temporary files and preserves destination when errors occur.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import openpyxl
import pytest

from exporters.excel_safety import sanitize_excel_cell, save_workbook_atomic, DANGEROUS_PREFIXES


class TestSanitizeExcelCell:
    """Test suite for CSV / Excel Formula Injection prevention."""

    @pytest.mark.parametrize(
        "prefix",
        ["=", "+", "-", "@", "\t", "\r"],
    )
    def test_dangerous_prefixes_neutralized(self, prefix: str):
        payload = f"{prefix}SUM(1+1)"
        sanitized = sanitize_excel_cell(payload)
        assert sanitized.startswith("'")
        assert sanitized == f"'{payload}"

    @pytest.mark.parametrize(
        "payload,expected",
        [
            ("=cmd|' /C calc'!A0", "'=cmd|' /C calc'!A0"),
            ("+123456", "'+123456"),
            ("-500000", "'-500000"),
            ("@SUM(A1:A10)", "'@SUM(A1:A10)"),
            ("\tPAYLOAD", "'\tPAYLOAD"),
            ("\rPAYLOAD", "'\rPAYLOAD"),
            ("   =1+1", "'   =1+1"),
            (" \t@malicious", "' \t@malicious"),
            ("  -calc", "'  -calc"),
            ("\r\n+inject", "'\r\n+inject"),
        ],
    )
    def test_dangerous_payloads_prefixed(self, payload: str, expected: str):
        assert sanitize_excel_cell(payload) == expected

    def test_already_quoted_string_not_doubled(self):
        val = "'=SUM(1,2)"
        assert sanitize_excel_cell(val) == val

    @pytest.mark.parametrize(
        "safe_val",
        [
            "Invoice #12345",
            "CÔNG TY CÀ PHÊ VIỆT NAM",
            "100.000 VND",
            "test@example.com",
            "A = B + C - D",
            "",
            "   ",
        ],
    )
    def test_safe_strings_untouched(self, safe_val: str):
        assert sanitize_excel_cell(safe_val) == safe_val

    @pytest.mark.parametrize(
        "non_str_val",
        [
            123,
            -456,
            0,
            123.45,
            -987.65,
            0.0,
            True,
            False,
            None,
            date(2026, 11, 2),
            datetime(2026, 11, 2, 10, 30, 0),
            Decimal("999.99"),
        ],
    )
    def test_non_string_types_untouched(self, non_str_val):
        result = sanitize_excel_cell(non_str_val)
        assert result == non_str_val
        assert type(result) is type(non_str_val)


class TestSaveWorkbookAtomic:
    """Test suite for atomic workbook writing."""

    def test_save_workbook_atomic_success(self, tmp_path: Path):
        target_path = tmp_path / "output.xlsx"

        wb = openpyxl.Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "TestSheet"
        ws["A1"] = "Hello"
        ws["A2"] = 12345

        save_workbook_atomic(wb, target_path)

        assert target_path.exists()
        assert target_path.is_file()

        # Check no temporary files left behind
        files = list(tmp_path.iterdir())
        assert files == [target_path]

        # Verify openpyxl can load and read the file
        loaded_wb = openpyxl.load_workbook(target_path)
        loaded_ws = loaded_wb["TestSheet"]
        assert loaded_ws["A1"].value == "Hello"
        assert loaded_ws["A2"].value == 12345
        loaded_wb.close()

    def test_save_workbook_atomic_creates_parent_dirs(self, tmp_path: Path):
        target_path = tmp_path / "nested" / "sub" / "output.xlsx"

        wb = openpyxl.Workbook()
        assert wb.active is not None
        wb.active["A1"] = "Nested"

        save_workbook_atomic(wb, target_path)

        assert target_path.exists()
        loaded_wb = openpyxl.load_workbook(target_path)
        assert loaded_wb.active is not None
        assert loaded_wb.active["A1"].value == "Nested"
        loaded_wb.close()

    def test_save_workbook_atomic_overwrites_existing(self, tmp_path: Path):
        target_path = tmp_path / "overwrite.xlsx"

        wb1 = openpyxl.Workbook()
        assert wb1.active is not None
        wb1.active["A1"] = "Version 1"
        save_workbook_atomic(wb1, target_path)

        wb2 = openpyxl.Workbook()
        assert wb2.active is not None
        wb2.active["A1"] = "Version 2"
        save_workbook_atomic(wb2, target_path)

        loaded_wb = openpyxl.load_workbook(target_path)
        assert loaded_wb.active is not None
        assert loaded_wb.active["A1"].value == "Version 2"
        loaded_wb.close()

        files = list(tmp_path.iterdir())
        assert files == [target_path]

    def test_save_workbook_atomic_failure_cleanup(self, tmp_path: Path):
        target_path = tmp_path / "fail_cleanup.xlsx"

        wb = openpyxl.Workbook()
        assert wb.active is not None
        wb.active["A1"] = "Should fail"

        with patch.object(wb, "save", side_effect=IOError("Simulated disk write error")):
            with pytest.raises(IOError, match="Simulated disk write error"):
                save_workbook_atomic(wb, target_path)

        # Target should not exist
        assert not target_path.exists()

        # No leftover temp files
        files = list(tmp_path.iterdir())
        assert files == []

    def test_save_workbook_atomic_failure_preserves_existing_file(self, tmp_path: Path):
        target_path = tmp_path / "preserve.xlsx"

        # Write original valid workbook
        wb_orig = openpyxl.Workbook()
        assert wb_orig.active is not None
        wb_orig.active["A1"] = "Original Content"
        save_workbook_atomic(wb_orig, target_path)

        wb_broken = openpyxl.Workbook()
        assert wb_broken.active is not None
        wb_broken.active["A1"] = "Broken Content"

        with patch.object(wb_broken, "save", side_effect=RuntimeError("Save crashed")):
            with pytest.raises(RuntimeError, match="Save crashed"):
                save_workbook_atomic(wb_broken, target_path)

        # Target should still have original content
        loaded_wb = openpyxl.load_workbook(target_path)
        assert loaded_wb.active is not None
        assert loaded_wb.active["A1"].value == "Original Content"
        loaded_wb.close()

        # Only target_path exists in directory, no junk
        files = list(tmp_path.iterdir())
        assert files == [target_path]

    def test_strip_invalid_xml_control_characters(self, tmp_path: Path):
        """Invalid XML control characters are removed to prevent openpyxl crashes."""
        raw_text = "Bad\x00Control\x08Chars\x0bAnd\x0cMore\x1fEnd"
        sanitized = sanitize_excel_cell(raw_text)
        assert "\x00" not in sanitized
        assert "\x08" not in sanitized
        assert "\x0b" not in sanitized
        assert "\x0c" not in sanitized
        assert "\x1f" not in sanitized
        assert sanitized == "BadControlCharsAndMoreEnd"

        # Neutralization still works on formula with illegal XML chars
        formula_with_junk = "\x01=SUM(A1:B1)\x02"
        sanitized_formula = sanitize_excel_cell(formula_with_junk)
        assert sanitized_formula == "'=SUM(A1:B1)"

        # Verify saving with sanitized string succeeds in openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"] = sanitized
        out = tmp_path / "xml_clean.xlsx"
        save_workbook_atomic(wb, out)
        assert out.exists()

