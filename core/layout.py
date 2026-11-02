"""Geometric line grouping module.

PLAN 2.3: Line reconstruction independent of OCR engine.
- Groups Word bounding boxes into horizontal lines based on median box height.
- Sorts words left-to-right within line; sorts lines top-to-bottom.
- Handles slight skew residual without assuming strict top-edge alignment.
"""

from typing import List
from core.types import Word, Line, Page


def reconstruct_lines(words: List[Word], page_height: float, page_width: float) -> List[Line]:
    """Group words into ordered lines based on median box height clustering.

    Args:
        words: List of Word instances with bounding boxes.
        page_height: Height of the page.
        page_width: Width of the page.

    Returns:
        List of reconstructed Line objects.
    """
    raise NotImplementedError("W1-layout-lines implementation pending")
