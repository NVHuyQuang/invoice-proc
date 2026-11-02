"""OCR image preprocessing module.

PLAN 2.2: Conditional image enhancement before OCR:
- Small angle deskew (cv2 minAreaRect or Hough lines on text regions, rotate if |angle| > 0.5 deg).
- Faded thermal receipts: grayscale conversion, CLAHE (clipLimit ~2.0, tile 8x8) when contrast is low.
- Narrow / long receipts (aspect ratio height/width > 3): slice into vertically overlapping segments,
  OCR each segment, stitch results, and remove duplicates in overlap region.
"""

from typing import Tuple, List, Union, Optional
import cv2
import numpy as np

from core.types import Word


def _normalize_min_area_rect_angle(rect: Tuple[Tuple[float, float], Tuple[float, float], float]) -> float:
    """Normalize minAreaRect angle to standard skew angle in [-45, 45].

    Standard OpenCV skew logic:
    if w < h: angle = -(90 + angle) (OpenCV < 4.5 angle in [-90, 0)) or angle - 90 (OpenCV >= 4.5).
    """
    (_, (w, h), angle) = rect
    if angle < 0:
        if w < h:
            angle = -(90.0 + angle)
        else:
            angle = -angle
    else:
        if w < h:
            angle = angle - 90.0
        else:
            angle = angle
    return float(angle)


def _estimate_skew_angle(gray: np.ndarray) -> float:
    """Estimate skew angle of text lines in a grayscale image.

    Uses HoughLinesP line detection, with fallback to minAreaRect on
    connected text contours or all foreground points.

    Returns:
        Skew angle in degrees in range [-45.0, 45.0].
    """
    h, w = gray.shape[:2]
    if h == 0 or w == 0:
        return 0.0

    # 1. Edge detection and Hough lines
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=40,
        minLineLength=int(min(w, h) * 0.1) if min(w, h) > 100 else 20,
        maxLineGap=10,
    )

    hough_angles = []
    if lines is not None:
        for line in lines:
            flat = np.asarray(line).ravel()
            if len(flat) >= 4:
                x1, y1, x2, y2 = flat[:4]
                if x2 != x1:
                    ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                    while ang <= -90.0:
                        ang += 180.0
                    while ang > 90.0:
                        ang -= 180.0
                    if abs(ang) <= 45.0:
                        hough_angles.append(ang)

    if len(hough_angles) >= 3:
        return float(np.median(hough_angles))

    # 2. Text contours with minAreaRect
    if float(np.mean(gray.astype(np.float32))) > 127.0:
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    else:
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
    dilated = cv2.dilate(thresh, kernel, iterations=1)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    rect_angles = []
    for c in contours:
        if cv2.contourArea(c) >= 50:
            rect = cv2.minAreaRect(c)
            h_ang = _normalize_min_area_rect_angle(rect)
            if abs(h_ang) <= 45.0:
                rect_angles.append(h_ang)

    if rect_angles:
        return float(np.median(rect_angles))

    # 3. Fallback: minAreaRect across all non-zero pixels
    pts = cv2.findNonZero(thresh)
    if pts is not None and len(pts) > 20:
        rect = cv2.minAreaRect(pts)
        h_ang = _normalize_min_area_rect_angle(rect)
        if abs(h_ang) <= 45.0:
            return float(h_ang)

    return 0.0



def deskew_image(img: np.ndarray) -> Tuple[np.ndarray, float]:
    """Detect text orientation angle and deskew image if |angle| > 0.5 degrees.

    Args:
        img: Input image (BGR or RGB numpy array, or grayscale).

    Returns:
        Tuple of (deskewed_image, rotation_angle_degrees).
    """
    if img is None or img.size == 0:
        return img, 0.0

    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()

    h, w = gray.shape[:2]
    if h == 0 or w == 0:
        return img, 0.0

    # Low standard deviation indicates uniform/blank image
    if float(np.std(gray.astype(np.float32))) < 1.0:
        return img, 0.0

    detected_angle = _estimate_skew_angle(gray)

    # Rotate only if skew exceeds 0.5 degrees
    if abs(detected_angle) <= 0.5:
        return img, 0.0

    center = (float(w) / 2.0, float(h) / 2.0)
    matrix = cv2.getRotationMatrix2D(center, detected_angle, 1.0)

    # Determine background border color based on image luminance
    is_light = float(np.mean(gray.astype(np.float32))) > 127.0
    bg_val = (255.0, 255.0, 255.0) if is_light else (0.0, 0.0, 0.0)

    deskewed = cv2.warpAffine(img, matrix, (w, h), flags=cv2.INTER_LINEAR, borderValue=bg_val)
    return deskewed, detected_angle


def enhance_contrast_clahe(img: np.ndarray, std_threshold: float = 20.0) -> np.ndarray:
    """Conditionally apply CLAHE if image contrast (grayscale standard deviation) is below threshold.

    Args:
        img: Input image.
        std_threshold: Grayscale standard deviation threshold (default 20.0 to avoid noise on sharp black/white text).

    Returns:
        Enhanced image (or original image if contrast is sufficient).
    """
    if img is None or img.size == 0:
        return img

    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()

    std = float(np.std(gray.astype(np.float32)))
    if std >= std_threshold:
        return img

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    return enhanced


def slice_long_receipt(
    img: np.ndarray,
    max_aspect_ratio: float = 3.0,
    overlap_ratio: float = 0.15
) -> List[Tuple[np.ndarray, int]]:
    """Slice tall/long receipts into overlapping vertical chunks to improve OCR accuracy.

    Args:
        img: Input image.
        max_aspect_ratio: Height-to-width ratio above which slicing triggers.
        overlap_ratio: Overlap percentage between consecutive slices.

    Returns:
        List of tuples: (chunk_image, y_offset).
    """
    if img is None or img.size == 0:
        return []

    h, w = img.shape[:2]
    if w == 0 or h == 0:
        return []

    aspect_ratio = h / w
    if aspect_ratio <= max_aspect_ratio:
        return [(img, 0)]

    chunk_height = int(w * max_aspect_ratio)
    if chunk_height <= 0:
        return [(img, 0)]

    overlap_px = max(0, min(chunk_height - 1, int(chunk_height * overlap_ratio)))
    step = max(1, chunk_height - overlap_px)

    chunks: List[Tuple[np.ndarray, int]] = []
    y = 0
    while y < h:
        y_end = min(y + chunk_height, h)
        chunks.append((img[y:y_end], y))
        if y_end >= h:
            break
        y += step

    return chunks


def stitch_slice_results(
    slice_results: Union[List[Tuple[List[Word], int]], List[List[Word]]],
    y_offsets: Optional[List[int]] = None,
    iou_threshold: float = 0.3,
) -> List[Word]:
    """Stitch OCR word results from sliced receipt chunks and remove duplicates in overlap regions.

    Args:
        slice_results: List of (words, y_offset) tuples, or list of word lists if y_offsets is provided.
        y_offsets: Optional list of y-offsets corresponding to each slice.
        iou_threshold: Intersection-over-union threshold for word duplicate detection.

    Returns:
        List of merged, deduplicated Word objects with global document coordinates.
    """
    if not slice_results:
        return []

    normalized: List[Tuple[List[Word], int]] = []
    if y_offsets is not None:
        for words, offset in zip(slice_results, y_offsets):
            normalized.append((words, int(offset)))
    else:
        for item in slice_results:
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], (int, float)):
                normalized.append((item[0], int(item[1])))
            elif isinstance(item, list):
                normalized.append((item, 0))

    global_words: List[Word] = []
    for words, offset in normalized:
        for w in words:
            gw = Word(
                text=w.text,
                bbox=(float(w.bbox[0]), float(w.bbox[1] + offset), float(w.bbox[2]), float(w.bbox[3] + offset)),
                conf=float(w.conf),
                page=int(w.page),
                source=str(w.source),
            )
            global_words.append(gw)

    if not global_words:
        return []

    def _iou(b1: Tuple[float, float, float, float], b2: Tuple[float, float, float, float]) -> float:
        ix0 = max(b1[0], b2[0])
        iy0 = max(b1[1], b2[1])
        ix1 = min(b1[2], b2[2])
        iy1 = min(b1[3], b2[3])
        inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
        a1 = max(0.0, b1[2] - b1[0]) * max(0.0, b1[3] - b1[1])
        a2 = max(0.0, b2[2] - b2[0]) * max(0.0, b2[3] - b2[1])
        union = a1 + a2 - inter
        return inter / union if union > 0 else 0.0

    global_words.sort(key=lambda w: (w.page, (w.bbox[1] + w.bbox[3]) / 2.0, w.bbox[0]))

    deduped: List[Word] = []
    for w in global_words:
        is_dup = False
        w_text_norm = w.text.strip().lower()
        w_yc = (w.bbox[1] + w.bbox[3]) / 2.0
        w_h = max(1.0, w.bbox[3] - w.bbox[1])

        for idx, existing in enumerate(deduped):
            if existing.page != w.page:
                continue
            e_text_norm = existing.text.strip().lower()
            e_yc = (existing.bbox[1] + existing.bbox[3]) / 2.0
            e_h = max(1.0, existing.bbox[3] - existing.bbox[1])

            text_match = (w_text_norm == e_text_norm)
            iou = _iou(w.bbox, existing.bbox)
            y_close = abs(w_yc - e_yc) < 0.6 * max(w_h, e_h)
            x_overlap = max(0.0, min(w.bbox[2], existing.bbox[2]) - max(w.bbox[0], existing.bbox[0])) > 0.3 * min(
                w.bbox[2] - w.bbox[0], existing.bbox[2] - existing.bbox[0]
            )

            if text_match and (iou >= iou_threshold or (y_close and x_overlap)):
                is_dup = True
                if w.conf > existing.conf:
                    deduped[idx] = w
                break

        if not is_dup:
            deduped.append(w)

    deduped.sort(key=lambda w: (w.page, (w.bbox[1] + w.bbox[3]) / 2.0, w.bbox[0]))
    return deduped


stitch_receipt_slices = stitch_slice_results

