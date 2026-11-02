"""Column detection and column-index assignment module.

PLAN 2.4: Column boundary detection and cell formatting.
- Detects column boundaries across successive lines using X clusters.
- Inserts column separator ' | ' when horizontal distance exceeds threshold.
- Assigns column index (col_idx) to each cell for downstream cross-checks.
"""

from typing import List
from core.types import Line


def assign_columns(lines: List[Line], page_width: float) -> List[Line]:
    """Detect table columns across lines and assign col_idx to each cell.

    Args:
        lines: List of reconstructed Line objects.
        page_width: Page width in points or pixels.

    Returns:
        Updated list of Line objects with col_idx assigned.
    """
    raise NotImplementedError("W1-layout-columns implementation pending")


def format_lines_as_text(lines: List[Line]) -> str:
    """Format lines into table-like text with column separators ' | '.

    Args:
        lines: Lines with assigned cells.

    Returns:
        Clean multi-line string with ' | ' between columns.
    """
    raise NotImplementedError("W1-layout-columns implementation pending")
