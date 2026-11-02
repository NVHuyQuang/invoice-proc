"""File classification and universal image loading module.

PLAN 1.1-1.2:
- Magic bytes detection (PDF, JPEG, PNG, WEBP, HEIC/HEIF).
- ImageOps.exif_transpose immediately after opening.
- RGB conversion, uint8 numpy array, scale constraint (MAX_IMAGE_DIMENSION).
- Records scale factor to map bounding boxes back to original coordinates.
- Multi-frame image handling: take first frame and warn.
"""

from pathlib import Path
from typing import Tuple, Optional
import numpy as np


def detect_file_type(file_path: Path) -> str:
    """Identify file type using magic bytes.

    Args:
        file_path: Path to the target file.

    Returns:
        One of "pdf", "jpeg", "png", "webp", "heic", or "unsupported".
    """
    raise NotImplementedError("W1-imageloader implementation pending")


def load_image(file_path: Path) -> Tuple[np.ndarray, float]:
    """Load an image file safely with EXIF transposition and dimension bounds.

    Args:
        file_path: Path to image (jpg, png, webp, heic).

    Returns:
        Tuple of (rgb_uint8_ndarray, scale_factor).

    Raises:
        ValueError: If file is corrupted or unsupported format.
    """
    raise NotImplementedError("W1-imageloader implementation pending")


def compute_file_sha256(file_path: Path) -> str:
    """Compute sha256 hex digest of file contents for deduplication and caching.

    Args:
        file_path: Path to target file.

    Returns:
        Hexadecimal SHA-256 string.
    """
    raise NotImplementedError("W1-imageloader implementation pending")
