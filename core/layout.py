"""Geometric line grouping module.

PLAN 2.3: Line reconstruction independent of OCR engine.
- Groups Word bounding boxes into horizontal lines based on median box height.
- Sorts words left-to-right within line; sorts lines top-to-bottom.
- Handles slight skew residual without assuming strict top-edge alignment.
"""

import math
import statistics
from collections import defaultdict
from typing import Dict, List, Tuple

from core.types import Line, Page, Word


def _estimate_skew_slope(words: List[Word], median_height: float) -> float:
    """Estimate page-level residual skew slope (tan of skew angle) from box centers."""
    if len(words) < 2:
        return 0.0

    # Extract box centers: (xc, yc, width, height)
    centers = []
    for w in words:
        x0, y0, x1, y1 = w.bbox
        xc = (x0 + x1) / 2.0
        yc = (y0 + y1) / 2.0
        width = abs(x1 - x0)
        height = abs(y1 - y0)
        centers.append((xc, yc, width, height))

    slopes: List[float] = []
    # For each word, find candidate words to its right
    for i, (x1, y1, w1, h1) in enumerate(centers):
        candidates = []
        for j, (x2, y2, w2, h2) in enumerate(centers):
            if i == j:
                continue
            dx = x2 - x1
            dy = y2 - y1
            # Must be to the right by at least a small horizontal distance and vertically within median_height
            if dx > max(1.0, 0.2 * median_height) and abs(dy) <= median_height:
                slope = dy / dx
                # Only consider slight residual skew: |slope| <= ~0.2 (~11.3 degrees)
                if abs(slope) <= 0.20:
                    candidates.append((dx, abs(dy), slope))
        if candidates:
            # Pick nearest right neighbor
            candidates.sort(key=lambda c: c[0])
            slopes.append(candidates[0][2])

    if not slopes:
        return 0.0

    return float(statistics.median(slopes))


def _has_large_horizontal_overlap(bbox1: Tuple[float, float, float, float],
                                  bbox2: Tuple[float, float, float, float],
                                  median_height: float) -> bool:
    """Determine whether two boxes have substantial horizontal overlap (indicating stacked lines)."""
    w1 = abs(bbox1[2] - bbox1[0])
    w2 = abs(bbox2[2] - bbox2[0])
    min_w = min(w1, w2)
    if min_w <= 0:
        return False
    overlap_px = max(0.0, min(bbox1[2], bbox2[2]) - max(bbox1[0], bbox2[0]))
    overlap_ratio = overlap_px / min_w
    # Only flag as stacked if overlap is > 40% of the narrower word AND exceeds min absolute pixels
    return overlap_ratio > 0.40 and overlap_px > max(3.0, 0.25 * median_height)


def _reconstruct_page_lines(page_num: int, words: List[Word], page_height: float, page_width: float) -> List[Line]:
    """Reconstruct lines for a single page."""
    if not words:
        return []

    # Calculate median box height for the page
    heights = [abs(w.bbox[3] - w.bbox[1]) for w in words if abs(w.bbox[3] - w.bbox[1]) > 0]
    if heights:
        median_height = float(statistics.median(heights))
    else:
        median_height = 10.0

    if median_height <= 0:
        median_height = 10.0

    threshold = 0.5 * median_height

    # Estimate skew slope from box center correlation
    skew_slope = _estimate_skew_slope(words, median_height)

    # Decorate words with center coordinates and skew-corrected Y
    decorated = []
    for w in words:
        x0, y0, x1, y1 = w.bbox
        xc = (x0 + x1) / 2.0
        yc = (y0 + y1) / 2.0
        # Skew-corrected Y center
        y_prime = yc - skew_slope * xc
        decorated.append({
            'word': w,
            'xc': xc,
            'yc': yc,
            'y_prime': y_prime,
            'bbox': w.bbox
        })

    # Sort words primarily by skew-corrected Y center
    decorated.sort(key=lambda d: (d['y_prime'], d['xc']))

    # Cluster words into lines based on Y-center deviation < 0.5 * median_height
    line_clusters: List[dict] = []

    for item in decorated:
        best_line = None
        best_dist = float('inf')

        for cluster in line_clusters:
            # Check Y-center deviation threshold
            cand_y_primes = [w['y_prime'] for w in cluster['words']] + [item['y_prime']]
            cand_mean = sum(cand_y_primes) / len(cand_y_primes)

            if all(abs(yp - cand_mean) < threshold for yp in cand_y_primes):
                # Check for severe horizontal overlap (stacked text lines)
                is_stacked = any(
                    _has_large_horizontal_overlap(item['bbox'], existing['bbox'], median_height)
                    for existing in cluster['words']
                )
                if not is_stacked:
                    dist = abs(item['y_prime'] - cluster['mean_y_prime'])
                    if dist < best_dist:
                        best_dist = dist
                        best_line = cluster

        if best_line is not None:
            best_line['words'].append(item)
            best_line['mean_y_prime'] = sum(w['y_prime'] for w in best_line['words']) / len(best_line['words'])
            best_line['mean_yc'] = sum(w['yc'] for w in best_line['words']) / len(best_line['words'])
        else:
            line_clusters.append({
                'words': [item],
                'mean_y_prime': item['y_prime'],
                'mean_yc': item['yc']
            })

    # Sort lines by mean skew-corrected Y (top-to-bottom)
    line_clusters.sort(key=lambda c: c['mean_y_prime'])

    # Build Line objects
    result_lines: List[Line] = []
    for cluster in line_clusters:
        # Sort words in line from left to right by X-center
        cluster['words'].sort(key=lambda w: (w['xc'], w['bbox'][0]))

        cells = [
            (w['word'].text, w['word'].bbox, w['word'].conf, 0)
            for w in cluster['words']
        ]
        line_y = float(cluster['mean_y_prime'])
        result_lines.append(Line(page=page_num, y=line_y, cells=cells))

    return result_lines


def reconstruct_lines(words: List[Word], page_height: float, page_width: float) -> List[Line]:
    """Group words into ordered lines based on median box height clustering.

    Args:
        words: List of Word instances with bounding boxes.
        page_height: Height of the page.
        page_width: Width of the page.

    Returns:
        List of reconstructed Line objects.
    """
    if not words:
        return []

    # Group words by page number
    page_groups: Dict[int, List[Word]] = defaultdict(list)
    for w in words:
        page_groups[w.page].append(w)

    all_lines: List[Line] = []
    for page_num in sorted(page_groups.keys()):
        page_words = page_groups[page_num]
        lines = _reconstruct_page_lines(page_num, page_words, page_height, page_width)
        all_lines.extend(lines)

    return all_lines
