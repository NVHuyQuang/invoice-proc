"""Unit tests for OCR image preprocessing module (PLAN 2.2).

Tests purely synthetic cv2 images:
- Deskew: rotated images are detected and straightened back.
- CLAHE: conditional contrast enhancement on faint receipts.
- Slicing: long receipts sliced into overlapping vertical segments with offsets.
"""

import cv2
import numpy as np
import pytest

from core.ocr_preprocess import (
    deskew_image,
    enhance_contrast_clahe,
    slice_long_receipt,
)


def _create_synthetic_receipt(
    skew_angle: float = 0.0,
    width: int = 400,
    height: int = 600,
    color: bool = False,
    dark_mode: bool = False,
) -> np.ndarray:
    """Helper to generate a clean synthetic receipt with horizontal text lines."""
    bg_val = 20.0 if dark_mode else 250.0
    text_val = 240.0 if dark_mode else 10.0
    text_color = (text_val, text_val, text_val)

    if color:
        img = np.full((height, width, 3), int(bg_val), dtype=np.uint8)
    else:
        img = np.full((height, width), int(bg_val), dtype=np.uint8)

    # Draw receipt header and lines
    cv2.putText(img, "RECEIPT STORE #1234", (40, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_color, 2)
    cv2.putText(img, "123 MAIN STREET, SUITE 100", (40, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.4, text_color, 1)

    items = [
        ("ORGANIC APPLES 1KG", "4.50"),
        ("ALMOND MILK 1L", "2.80"),
        ("WHOLE WHEAT BREAD", "3.20"),
        ("COLD BREW COFFEE 12OZ", "4.99"),
        ("CHEDDAR CHEESE 250G", "5.49"),
        ("SPARKLING WATER 6PK", "6.99"),
        ("SUBTOTAL", "27.97"),
        ("TAX 8.25%", "2.31"),
        ("TOTAL", "30.28"),
    ]

    y = 120
    for name, price in items:
        cv2.putText(img, name, (30, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, text_color, 1)
        cv2.putText(img, price, (width - 90, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, text_color, 1)
        y += 45

    if skew_angle != 0.0:
        center = (float(width) / 2.0, float(height) / 2.0)
        matrix = cv2.getRotationMatrix2D(center, skew_angle, 1.0)
        border_val = (bg_val, bg_val, bg_val)
        img = cv2.warpAffine(img, matrix, (width, height), flags=cv2.INTER_LINEAR, borderValue=border_val)

    return img


# ============================================================================
# 1. Deskew Tests
# ============================================================================


class TestDeskewImage:
    """Tests for deskew_image function."""

    def test_deskew_rotated_positive_2_degrees(self):
        """Image rotated by +2.0 degrees is detected and straightened back."""
        img_rotated = _create_synthetic_receipt(skew_angle=2.0)
        deskewed, rot_angle = deskew_image(img_rotated)

        # Skew detected should be around 2.0 degrees (within +/- 0.5 deg tolerance)
        assert abs(rot_angle) > 0.5
        assert pytest.approx(abs(rot_angle), abs=0.5) == 2.0

        # Straightened image should now have remaining skew <= 0.5 degrees
        _, second_angle = deskew_image(deskewed)
        assert second_angle == 0.0

    def test_deskew_rotated_negative_2_degrees(self):
        """Image rotated by -2.0 degrees is detected and straightened back."""
        img_rotated = _create_synthetic_receipt(skew_angle=-2.0)
        deskewed, rot_angle = deskew_image(img_rotated)

        assert abs(rot_angle) > 0.5
        assert pytest.approx(abs(rot_angle), abs=0.5) == 2.0

        # Remaining skew must be within 0.5 degrees (no further rotation)
        _, second_angle = deskew_image(deskewed)
        assert second_angle == 0.0

    def test_deskew_small_angle_not_rotated(self):
        """Small skew <= 0.5 degrees should not trigger rotation."""
        # 0.2 degrees is below the 0.5 degree threshold
        img_small_skew = _create_synthetic_receipt(skew_angle=0.2)
        deskewed, rot_angle = deskew_image(img_small_skew)

        assert rot_angle == 0.0
        assert np.array_equal(deskewed, img_small_skew)

    def test_deskew_perfectly_upright(self):
        """Upright image (0 skew) remains untouched."""
        img_upright = _create_synthetic_receipt(skew_angle=0.0)
        deskewed, rot_angle = deskew_image(img_upright)

        assert rot_angle == 0.0
        assert np.array_equal(deskewed, img_upright)

    def test_deskew_color_bgr_image(self):
        """BGR 3-channel image is deskewed while preserving channel count."""
        img_color = _create_synthetic_receipt(skew_angle=2.0, color=True)
        assert img_color.ndim == 3 and img_color.shape[2] == 3

        deskewed, rot_angle = deskew_image(img_color)
        assert abs(rot_angle) > 0.5
        assert deskewed.ndim == 3
        assert deskewed.shape == img_color.shape

        _, second_angle = deskew_image(deskewed)
        assert second_angle == 0.0

    def test_deskew_dark_background(self):
        """Dark mode receipt (light text on dark background) is handled."""
        img_dark = _create_synthetic_receipt(skew_angle=2.0, dark_mode=True)
        deskewed, rot_angle = deskew_image(img_dark)

        assert abs(rot_angle) > 0.5
        _, second_angle = deskew_image(deskewed)
        assert second_angle == 0.0

    def test_deskew_empty_and_blank_images(self):
        """Blank or empty images return 0.0 rotation and do not fail."""
        empty_img = np.zeros((0, 0), dtype=np.uint8)
        res, ang = deskew_image(empty_img)
        assert ang == 0.0

        blank_white = np.full((200, 200), 255, dtype=np.uint8)
        res_blank, ang_blank = deskew_image(blank_white)
        assert ang_blank == 0.0
        assert np.array_equal(res_blank, blank_white)


# ============================================================================
# 2. CLAHE Contrast Enhancement Tests
# ============================================================================


class TestEnhanceContrastClahe:
    """Tests for enhance_contrast_clahe function."""

    def test_clahe_on_low_contrast_image(self):
        """Low contrast (std < std_threshold) receipt triggers CLAHE enhancement."""
        # Faint receipt: low variation in grayscale
        low_contrast = np.full((200, 200), 210, dtype=np.uint8)
        cv2.putText(low_contrast, "FAINT RECEIPT 123.45", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (190.0, 190.0, 190.0), 1)

        std_in = float(np.std(low_contrast.astype(np.float32)))
        assert std_in < 40.0

        enhanced = enhance_contrast_clahe(low_contrast, std_threshold=40.0)
        assert enhanced.shape == low_contrast.shape
        # Content was altered/enhanced by CLAHE
        assert not np.array_equal(enhanced, low_contrast)

    def test_clahe_skipped_on_high_contrast_image(self):
        """High contrast (std >= std_threshold) image remains unchanged."""
        high_contrast = np.full((200, 200), 255, dtype=np.uint8)
        cv2.putText(high_contrast, "SHARP HIGH CONTRAST", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0.0, 0.0, 0.0), 2)

        std_in = float(np.std(high_contrast.astype(np.float32)))
        assert std_in >= 40.0

        result = enhance_contrast_clahe(high_contrast, std_threshold=40.0)
        assert np.array_equal(result, high_contrast)

    def test_clahe_custom_std_threshold(self):
        """Custom std_threshold properly gates enhancement."""
        img = np.full((100, 100), 128, dtype=np.uint8)
        img[25:75, 25:75] = 160
        actual_std = float(np.std(img.astype(np.float32)))

        # Threshold below actual std -> no enhancement
        res_skipped = enhance_contrast_clahe(img, std_threshold=actual_std - 1.0)
        assert np.array_equal(res_skipped, img)

        # Threshold above actual std -> enhancement applied
        res_enhanced = enhance_contrast_clahe(img, std_threshold=actual_std + 1.0)
        assert not np.array_equal(res_enhanced, img)

    def test_clahe_color_input_converts_to_gray_on_enhance(self):
        """Color low-contrast input is converted to grayscale when CLAHE is applied."""
        color_low = np.full((200, 200, 3), 210, dtype=np.uint8)
        color_low[50:150, 50:150] = 195

        enhanced = enhance_contrast_clahe(color_low, std_threshold=40.0)
        # Low contrast enhanced output is 2D grayscale
        assert enhanced.ndim == 2
        assert enhanced.shape == (200, 200)

    def test_clahe_empty_image(self):
        """Empty input does not crash and returns original."""
        empty_img = np.zeros((0, 0), dtype=np.uint8)
        assert enhance_contrast_clahe(empty_img).size == 0


# ============================================================================
# 3. Slicing Tests
# ============================================================================


class TestSliceLongReceipt:
    """Tests for slice_long_receipt function."""

    def test_normal_receipt_not_sliced(self):
        """Receipt with aspect ratio <= max_aspect_ratio is not sliced."""
        # Height 600, Width 300 -> ratio 2.0 <= 3.0
        img = np.zeros((600, 300), dtype=np.uint8)
        slices = slice_long_receipt(img, max_aspect_ratio=3.0)

        assert len(slices) == 1
        chunk, offset = slices[0]
        assert offset == 0
        assert chunk.shape == (600, 300)
        assert np.array_equal(chunk, img)

    def test_exact_boundary_aspect_ratio_not_sliced(self):
        """Receipt with aspect ratio exactly equal to max_aspect_ratio is not sliced."""
        # Height 900, Width 300 -> ratio 3.0 == 3.0
        img = np.zeros((900, 300), dtype=np.uint8)
        slices = slice_long_receipt(img, max_aspect_ratio=3.0)

        assert len(slices) == 1
        assert slices[0][1] == 0
        assert slices[0][0].shape == (900, 300)

    def test_long_receipt_slicing_and_offset_calculation(self):
        """Tall receipt (height/width > 3) is sliced into overlapping segments with correct offsets."""
        # Height 1500, Width 300 -> ratio 5.0 > 3.0
        height, width = 1500, 300
        img = np.arange(height * width, dtype=np.uint32).reshape(height, width)

        max_aspect_ratio = 3.0
        overlap_ratio = 0.15
        slices = slice_long_receipt(img, max_aspect_ratio=max_aspect_ratio, overlap_ratio=overlap_ratio)

        # Expected chunk height = 300 * 3.0 = 900
        # Overlap = int(900 * 0.15) = 135 px
        # Step = 900 - 135 = 765 px
        # Slice 0: [0:900], offset 0
        # Slice 1: [765:1500], offset 765
        assert len(slices) == 2

        # Verify slice 0
        chunk_0, offset_0 = slices[0]
        assert offset_0 == 0
        assert chunk_0.shape == (900, 300)
        assert np.array_equal(chunk_0, img[0:900, :])

        # Verify slice 1
        chunk_1, offset_1 = slices[1]
        assert offset_1 == 765
        assert chunk_1.shape == (1500 - 765, 300)
        assert np.array_equal(chunk_1, img[765:1500, :])

        # Verify overlap length
        overlap = (offset_0 + chunk_0.shape[0]) - offset_1
        assert overlap == 135

    def test_full_coverage_without_vertical_gaps(self):
        """Verify seamless coverage across various heights and aspects."""
        width = 250
        for height in [760, 1000, 1800, 2500]:
            img = np.random.randint(0, 255, (height, width), dtype=np.uint8)
            slices = slice_long_receipt(img, max_aspect_ratio=3.0, overlap_ratio=0.15)

            assert len(slices) >= 2
            covered = np.zeros(height, dtype=bool)

            for i, (chunk, offset) in enumerate(slices):
                chunk_h = chunk.shape[0]
                assert offset >= 0
                assert offset + chunk_h <= height
                assert np.array_equal(chunk, img[offset : offset + chunk_h])
                covered[offset : offset + chunk_h] = True

                if i > 0:
                    prev_chunk, prev_offset = slices[i - 1]
                    overlap_px = (prev_offset + prev_chunk.shape[0]) - offset
                    assert overlap_px > 0, f"Gap between slice {i-1} and {i} at height {height}"

            # Every single vertical row from 0 to height-1 must be covered
            assert np.all(covered), f"Uncovered rows found at height {height}"

    def test_slice_preserves_3_channels(self):
        """Slicing a 3-channel color image preserves all channels."""
        img_color = np.zeros((1200, 200, 3), dtype=np.uint8)
        slices = slice_long_receipt(img_color, max_aspect_ratio=3.0)

        assert len(slices) > 1
        for chunk, _ in slices:
            assert chunk.ndim == 3
            assert chunk.shape[1] == 200
            assert chunk.shape[2] == 3

    def test_slice_empty_image(self):
        """Empty or 0-dimension image returns empty list."""
        assert slice_long_receipt(np.zeros((0, 0), dtype=np.uint8)) == []
        assert slice_long_receipt(np.zeros((100, 0), dtype=np.uint8)) == []
        assert slice_long_receipt(np.zeros((0, 100), dtype=np.uint8)) == []
