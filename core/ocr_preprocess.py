"""OCR image preprocessing module.

PLAN 2.2: Conditional image enhancement before OCR:
- Small angle deskew (cv2 minAreaRect or Hough lines on text regions, rotate if |angle| > 0.5 deg).
- Faded thermal receipts: grayscale conversion, CLAHE (clipLimit ~2.0, tile 8x8) when contrast is low.
- Narrow / long receipts (aspect ratio height/width > 3): slice into vertically overlapping segments,
  OCR each segment, stitch results, and remove duplicates in overlap region.
"""

from typing import Tuple, List, Union
import cv2
import numpy as np


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
            x1, y1, x2, y2 = line[0]
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
            ang = rect[2]
            h_ang = ang if ang <= 45.0 else ang - 90.0
            if abs(h_ang) <= 45.0:
                rect_angles.append(h_ang)

    if rect_angles:
        return float(np.median(rect_angles))

    # 3. Fallback: minAreaRect across all non-zero pixels
    pts = cv2.findNonZero(thresh)
    if pts is not None and len(pts) > 20:
        rect = cv2.minAreaRect(pts)
        ang = rect[2]
        h_ang = ang if ang <= 45.0 else ang - 90.0
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


def enhance_contrast_clahe(img: np.ndarray, std_threshold: float = 40.0) -> np.ndarray:
    """Conditionally apply CLAHE if image contrast (grayscale standard deviation) is below threshold.

    Args:
        img: Input image.
        std_threshold: Grayscale standard deviation threshold.

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
