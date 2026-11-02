"""Column detection and column-index assignment module.

PLAN 2.4: Column boundary detection and cell formatting.
- Detects column boundaries across successive lines using X clusters.
- Inserts column separator ' | ' when horizontal distance exceeds threshold.
- Assigns column index (col_idx) to each cell for downstream cross-checks.
"""

import bisect
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from core.types import Line


def is_numeric_token(text: str) -> bool:
    """Check if text represents a numeric value (quantity, price, amount, code, date).

    Strips currency symbols, parentheses, percentages, plus/minus signs.
    """
    cleaned = text.strip()
    if not cleaned:
        return False
    stripped = re.sub(r'[\$€£¥₫%\s\(\)\-\+]', '', cleaned)
    if not stripped:
        return False
    has_digit = bool(re.search(r'\d', stripped))
    valid_chars = bool(re.fullmatch(r'[\d.,/:]+', stripped))
    return has_digit and valid_chars


@dataclass
class _Segment:
    cells: List[Tuple[str, Tuple[float, float, float, float], float, int]]
    x0: float
    y0: float
    x1: float
    y1: float
    xc: float
    text: str
    is_numeric: bool
    x0_prime: float = 0.0
    x1_prime: float = 0.0
    xc_prime: float = 0.0


def _segment_line(
    line: Line,
    gap_threshold: float
) -> List[_Segment]:
    """Group horizontally adjacent cells within a line into segments based on gap threshold."""
    if not line.cells:
        return []

    # Sort cells left to right by x0
    sorted_cells = sorted(line.cells, key=lambda c: c[1][0])
    non_empty = [c for c in sorted_cells if c[0].strip()]
    if not non_empty:
        return []

    groups: List[List[Tuple[str, Tuple[float, float, float, float], float, int]]] = []
    curr_group = [non_empty[0]]

    for c in non_empty[1:]:
        prev_c = curr_group[-1]
        gap = c[1][0] - prev_c[1][2]
        if gap <= gap_threshold:
            curr_group.append(c)
        else:
            groups.append(curr_group)
            curr_group = [c]
    groups.append(curr_group)

    segments: List[_Segment] = []
    for g in groups:
        x0 = min(c[1][0] for c in g)
        y0 = min(c[1][1] for c in g)
        x1 = max(c[1][2] for c in g)
        y1 = max(c[1][3] for c in g)
        xc = (x0 + x1) / 2.0
        text = " ".join(c[0].strip() for c in g)
        is_num = is_numeric_token(text) or any(is_numeric_token(c[0]) for c in g)
        segments.append(
            _Segment(
                cells=g,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                xc=xc,
                text=text,
                is_numeric=is_num,
                x0_prime=x0,
                x1_prime=x1,
                xc_prime=xc,
            )
        )
    return segments


def _detect_skew_slope(
    sorted_lines: List[Line],
    line_segments: Dict[int, List[_Segment]]
) -> float:
    """Detect horizontal drift/skew slope (dx/dy) across consecutive lines."""
    slopes: List[float] = []
    for i in range(len(sorted_lines) - 1):
        l_curr = sorted_lines[i]
        l_next = sorted_lines[i + 1]
        dy = l_next.y - l_curr.y
        if dy < 2.0:
            continue
        segs_c = line_segments[id(l_curr)]
        segs_n = line_segments[id(l_next)]

        # Match numeric segments across consecutive lines
        num_c = [s for s in segs_c if s.is_numeric]
        num_n = [s for s in segs_n if s.is_numeric]
        for sc in num_c:
            for sn in num_n:
                if abs(sn.xc - sc.xc) <= 35.0:
                    slopes.append((sn.xc - sc.xc) / dy)

        # Match segment pairs when segment counts match and >= 2
        if len(segs_c) >= 2 and len(segs_c) == len(segs_n):
            for sc, sn in zip(segs_c, segs_n):
                if abs(sn.xc - sc.xc) <= 25.0:
                    slopes.append((sn.xc - sc.xc) / dy)

    if slopes:
        med_s = statistics.median(slopes)
        if 0.003 <= abs(med_s) <= 0.5:
            return float(med_s)
    return 0.0


def _partition_sections(
    sorted_lines: List[Line],
    line_segments: Dict[int, List[_Segment]]
) -> List[List[Line]]:
    """Partition lines on a page into coherent layout blocks (e.g. 2-column header vs multi-column table)."""
    if not sorted_lines:
        return []

    sections: List[List[Line]] = []
    curr_section = [sorted_lines[0]]

    for i in range(1, len(sorted_lines)):
        prev_line = sorted_lines[i - 1]
        curr_line = sorted_lines[i]

        dy = curr_line.y - prev_line.y
        # Significant vertical gap indicates a separate section
        if dy > 60.0:
            sections.append(curr_section)
            curr_section = [curr_line]
            continue

        segs_prev = line_segments[id(prev_line)]
        segs_curr = line_segments[id(curr_line)]

        # Structural conflict check between consecutive multi-column lines
        if len(segs_prev) >= 2 and len(segs_curr) >= 2:
            conflict = False
            for k in range(len(segs_prev) - 1):
                g_left = segs_prev[k].x1_prime
                g_right = segs_prev[k + 1].x0_prime
                if g_right - g_left > 40.0:
                    inside = [
                        s for s in segs_curr
                        if g_left + 15.0 < s.xc_prime < g_right - 15.0
                    ]
                    if inside:
                        conflict = True
                        break
            if conflict:
                sections.append(curr_section)
                curr_section = [curr_line]
                continue

        curr_section.append(curr_line)

    if curr_section:
        sections.append(curr_section)
    return sections


def _find_section_boundaries(
    section_lines: List[Line],
    line_segments: Dict[int, List[_Segment]]
) -> List[float]:
    """Find column boundaries for a section using max-segment lines and numeric cluster anchors."""
    valid_lines = [line_segments[id(l)] for l in section_lines if line_segments[id(l)]]
    if not valid_lines:
        return []

    max_segs = max(len(segs) for segs in valid_lines)
    if max_segs <= 1:
        return []

    # Lines with the maximum number of columns define clean boundaries
    rich_lines = [segs for segs in valid_lines if len(segs) == max_segs]
    boundaries: List[float] = []

    for k in range(max_segs - 1):
        left_max = max(segs[k].x1_prime for segs in rich_lines)
        right_min = min(segs[k + 1].x0_prime for segs in rich_lines)
        if right_min > left_max:
            b = (left_max + right_min) / 2.0
        else:
            b = statistics.median(
                [(segs[k].x1_prime + segs[k + 1].x0_prime) / 2.0 for segs in rich_lines]
            )
        boundaries.append(float(b))

    boundaries.sort()
    return boundaries


def assign_columns(lines: List[Line], page_width: float) -> List[Line]:
    """Detect table columns across lines and assign col_idx to each cell.

    - Detects column boundaries across successive lines using X clusters.
    - Handles slight skew/drift residual across consecutive lines.
    - Assigns strictly increasing column indices col_idx to cells in Line.cells.

    Args:
        lines: List of reconstructed Line objects.
        page_width: Page width in points or pixels.

    Returns:
        Updated list of Line objects with col_idx assigned.
    """
    if not lines:
        return []

    # Group lines by page while preserving line identities
    page_map: Dict[int, List[Tuple[int, Line]]] = defaultdict(list)
    for idx, l in enumerate(lines):
        page_map[l.page].append((idx, l))

    updated_cells: List[Optional[List[Tuple[str, Tuple[float, float, float, float], float, int]]]] = [
        None
    ] * len(lines)

    for page_num, line_entries in page_map.items():
        sorted_entries = sorted(line_entries, key=lambda x: x[1].y)

        # Estimate average character width on this page
        char_widths: List[float] = []
        for _, line in sorted_entries:
            for cell in line.cells:
                text = cell[0].strip()
                bbox = cell[1]
                w = bbox[2] - bbox[0]
                if len(text) > 0 and w > 0:
                    char_widths.append(w / len(text))

        if char_widths:
            median_cw = statistics.median(char_widths)
            gap_threshold = max(8.0, 1.5 * median_cw)
        else:
            gap_threshold = 12.0

        # Segment each line
        line_segments: Dict[int, List[_Segment]] = {}
        for orig_idx, line in sorted_entries:
            line_segments[id(line)] = _segment_line(line, gap_threshold)

        # Detect and compensate for skew/drift
        page_lines = [entry[1] for entry in sorted_entries]
        skew_slope = _detect_skew_slope(page_lines, line_segments)

        y_ref = min(l.y for l in page_lines)
        for line in page_lines:
            for s in line_segments[id(line)]:
                s.x0_prime = s.x0 - skew_slope * (line.y - y_ref)
                s.x1_prime = s.x1 - skew_slope * (line.y - y_ref)
                s.xc_prime = (s.x0_prime + s.x1_prime) / 2.0

        # Partition into sections and assign column boundaries
        sections = _partition_sections(page_lines, line_segments)
        for section in sections:
            boundaries = _find_section_boundaries(section, line_segments)

            for line in section:
                segs = line_segments[id(line)]
                if not segs:
                    continue

                assigned_line_cells: List[
                    Tuple[str, Tuple[float, float, float, float], float, int]
                ] = []
                last_col = -1

                for s in segs:
                    if boundaries:
                        col = bisect.bisect_right(boundaries, s.xc_prime)
                    else:
                        col = 0
                    if col <= last_col:
                        col = last_col + 1
                    last_col = col

                    for c in s.cells:
                        conf = c[2] if len(c) > 2 else 1.0
                        assigned_line_cells.append((c[0], c[1], conf, col))

                # Find original index
                for orig_idx, orig_l in sorted_entries:
                    if orig_l is line:
                        updated_cells[orig_idx] = assigned_line_cells
                        break

    # Apply updated cells back to lines
    for idx, new_cells in enumerate(updated_cells):
        if new_cells is not None:
            lines[idx].cells = new_cells
        elif lines[idx].cells:
            # Normalize existing cells to 4-tuple if unassigned
            lines[idx].cells = [
                (c[0], c[1], c[2] if len(c) > 2 else 1.0, c[3] if len(c) > 3 else 0)
                for c in lines[idx].cells
            ]

    return lines


def format_lines_as_text(lines: List[Line]) -> str:
    """Format lines into table-like text with column separators ' | '.

    - Inserts ' | ' between columns when horizontal distance exceeds threshold
      or col_idx changes.
    - Joins words within the same column with spaces.

    Args:
        lines: Lines with assigned cells.

    Returns:
        Clean multi-line string with ' | ' between columns.
    """
    if not lines:
        return ""

    # Estimate page-level gap threshold
    char_widths: List[float] = []
    for line in lines:
        for cell in line.cells:
            text = cell[0].strip()
            bbox = cell[1]
            w = bbox[2] - bbox[0]
            if len(text) > 0 and w > 0:
                char_widths.append(w / len(text))

    if char_widths:
        median_cw = statistics.median(char_widths)
        gap_threshold = max(8.0, 1.5 * median_cw)
    else:
        gap_threshold = 12.0

    result_lines: List[str] = []
    for line in lines:
        if not line.cells:
            result_lines.append("")
            continue

        # Sort cells left to right
        sorted_cells = sorted(line.cells, key=lambda c: c[1][0])
        non_empty = [c for c in sorted_cells if c[0].strip()]
        if not non_empty:
            result_lines.append("")
            continue

        parts: List[str] = []
        curr_text = non_empty[0][0].strip()
        curr_col = non_empty[0][3] if len(non_empty[0]) > 3 else 0
        curr_x1 = non_empty[0][1][2]

        for next_c in non_empty[1:]:
            next_text = next_c[0].strip()
            next_col = next_c[3] if len(next_c) > 3 else 0
            next_x0 = next_c[1][0]
            next_x1 = next_c[1][2]

            gap = next_x0 - curr_x1
            is_col_break = (next_col != curr_col) or (gap > gap_threshold)

            if is_col_break:
                parts.append(curr_text)
                curr_text = next_text
                curr_col = next_col
            else:
                curr_text = f"{curr_text} {next_text}"

            curr_x1 = max(curr_x1, next_x1)

        parts.append(curr_text)
        result_lines.append(" | ".join(parts))

    return "\n".join(result_lines)
