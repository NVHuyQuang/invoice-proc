"""Excel security and atomic write module.

PLAN 6.2:
- Sanitizes text cells against CSV/Excel Formula Injection (=, +, -, @, \\t, \\r).
- Prepends single quote or treats as explicit string.
- Writes workbook atomically via temporary file to prevent truncated outputs.
"""

from pathlib import Path
import os
import re
import tempfile
from typing import Any
import openpyxl

DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", chr(13))
ILLEGAL_XML_CHARACTERS_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")


def sanitize_excel_cell(value: Any) -> Any:
    """Sanitize string values to neutralize formula injection payloads and remove invalid XML chars.

    Removes invalid XML control characters that crash openpyxl.
    Prepends a single quote (') to any string value that starts with dangerous
    formula trigger characters (=, +, -, @, \\t, \
), including strings with
    leading whitespace before dangerous characters.
    Non-string values are returned unmodified.

    Args:
        value: Any cell value.

    Returns:
        Sanitized value.
    """
    if isinstance(value, str):
        cleaned = ILLEGAL_XML_CHARACTERS_RE.sub("", value)
        if cleaned:
            if cleaned.startswith(DANGEROUS_PREFIXES) or cleaned.lstrip().startswith(DANGEROUS_PREFIXES):
                return f"'{cleaned}"
        return cleaned
    return value




def save_workbook_atomic(wb: openpyxl.Workbook, target_path: Path) -> None:
    """Save workbook to temporary file and atomically rename to target_path.

    Writes to a temporary file in the same directory as target_path, then
    atomically replaces target_path to ensure no corrupted or partially
    written file is ever left in place. Cleans up temporary files on error.

    Args:
        wb: openpyxl Workbook instance.
        target_path: Destination path.
    """
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_fd, temp_file_path = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    os.close(temp_fd)
    temp_path = Path(temp_file_path)

    try:
        wb.save(temp_path)
        os.replace(temp_path, target)
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise
