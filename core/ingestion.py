"""File classification and universal image loading module.

PLAN 1.1-1.2:
- Magic bytes detection (PDF, JPEG, PNG, WEBP, HEIC/HEIF).
- ImageOps.exif_transpose immediately after opening.
- RGB conversion, uint8 numpy array, scale constraint (MAX_IMAGE_DIMENSION).
- Records scale factor to map bounding boxes back to original coordinates.
- Multi-frame image handling: take first frame and warn.
- SHA-256 calculation for deduplication and caching.
"""

from pathlib import Path
from typing import Tuple, Optional
import hashlib
import warnings
import numpy as np
from PIL import Image, ImageOps
import pillow_heif

from config import MAX_IMAGE_DIMENSION

# Register HEIF opener with Pillow once
pillow_heif.register_heif_opener()

SUPPORTED_IMAGE_TYPES = frozenset({"jpeg", "png", "webp", "heic"})
HEIC_BRANDS = frozenset({
    b"heic", b"heix", b"heim", b"heis",
    b"mif1", b"msf1", b"hevc", b"hevx", b"hevm", b"hevs"
})


def compute_file_sha256(file_path: Path) -> str:
    """Compute sha256 hex digest of file contents for deduplication and caching.

    Args:
        file_path: Path to target file.

    Returns:
        Hexadecimal SHA-256 string.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def detect_file_type(file_path: Path) -> str:
    """Identify file type using magic bytes.

    Args:
        file_path: Path to the target file.

    Returns:
        One of "pdf", "jpeg", "png", "webp", "heic", or "unsupported".
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    try:
        with open(path, "rb") as f:
            header = f.read(64)
    except OSError:
        return "unsupported"

    if len(header) < 4:
        return "unsupported"

    # PDF: starts with %PDF
    if header.startswith(b"%PDF"):
        return "pdf"

    # JPEG: starts with \xff\xd8
    if header.startswith(b"\xff\xd8"):
        return "jpeg"

    # PNG: starts with \x89PNG
    if header.startswith(b"\x89PNG"):
        return "png"

    # WEBP: RIFF....WEBP
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"

    # HEIC / HEIF: ISOBMFF ftyp box
    if len(header) >= 12 and header[4:8] == b"ftyp":
        major_brand = header[8:12].lower()
        if major_brand in HEIC_BRANDS:
            return "heic"
        box_size = int.from_bytes(header[0:4], "big")
        limit = min(len(header), box_size if box_size > 0 else len(header))
        for offset in range(16, limit, 4):
            if header[offset:offset + 4].lower() in HEIC_BRANDS:
                return "heic"
        if pillow_heif.is_supported(header[:32]):
            return "heic"

    return "unsupported"


def load_image(file_path: Path, max_dimension: Optional[int] = None) -> Tuple[np.ndarray, float]:
    """Load an image file safely with EXIF transposition and dimension bounds.

    Args:
        file_path: Path to image (jpg, png, webp, heic).
        max_dimension: Optional maximum dimension override (defaults to MAX_IMAGE_DIMENSION).

    Returns:
        Tuple of (rgb_uint8_ndarray, scale_factor).

    Raises:
        ValueError: If file is corrupted or unsupported format.
        FileNotFoundError: If file does not exist.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    file_type = detect_file_type(path)
    if file_type not in SUPPORTED_IMAGE_TYPES:
        raise ValueError(f"Unsupported image format: '{file_type}' for file {path}")

    limit_dim = max_dimension if max_dimension is not None else MAX_IMAGE_DIMENSION

    try:
        with Image.open(path) as raw_img:
            # Multi-frame image handling: only take first frame and warn
            n_frames = getattr(raw_img, "n_frames", 1)
            if n_frames > 1:
                warnings.warn(
                    f"Multi-frame image detected ({n_frames} frames) in {path}. "
                    "Only the first frame is processed.",
                    UserWarning,
                    stacklevel=2,
                )
                raw_img.seek(0)

            # BẮT BUỘC ImageOps.exif_transpose ngay sau khi mở
            img = ImageOps.exif_transpose(raw_img)

            # Chuyển về RGB
            if img.mode != "RGB":
                img = img.convert("RGB")

            # Giới hạn cạnh dài tối đa (MAX_IMAGE_DIMENSION), trả về hệ số scale_factor
            width, height = img.size
            max_dim = max(width, height)
            scale_factor = 1.0

            if max_dim > limit_dim:
                scale_factor = limit_dim / max_dim
                new_w = max(1, int(round(width * scale_factor)))
                new_h = max(1, int(round(height * scale_factor)))
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            arr = np.array(img, dtype=np.uint8)
            return arr, float(scale_factor)
    except (ValueError, FileNotFoundError):
        raise
    except Exception as e:
        raise ValueError(f"Corrupted or invalid image file {path}: {e}") from e
