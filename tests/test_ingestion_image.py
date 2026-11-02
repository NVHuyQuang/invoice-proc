"""Unit tests for core/ingestion.py (PLAN 1.1 - 1.2).

INVARIANTS:
1. Tests must NEVER access real invoice files.
2. All images are synthetically generated.
3. Tests cover magic bytes, EXIF transposition, dimension scaling,
   multi-frame handling, file hashing, corrupted files, and wrong extensions.
"""

import hashlib
import io
import warnings
from pathlib import Path
import numpy as np
from PIL import Image
import pillow_heif
import pytest

from config import MAX_IMAGE_DIMENSION
from core.ingestion import compute_file_sha256, detect_file_type, load_image

# Ensure pillow_heif is ready
pillow_heif.register_heif_opener()


# ============================================================================
# Fixtures for synthetic images
# ============================================================================

@pytest.fixture
def synthetic_jpeg(tmp_path: Path) -> Path:
    """Create a valid synthetic JPEG image."""
    img_path = tmp_path / "test_synth.jpg"
    img = Image.new("RGB", (120, 80), color=(200, 100, 50))
    img.save(img_path, format="JPEG")
    return img_path


@pytest.fixture
def synthetic_png(tmp_path: Path) -> Path:
    """Create a valid synthetic PNG image (RGBA mode)."""
    img_path = tmp_path / "test_synth.png"
    img = Image.new("RGBA", (100, 60), color=(10, 20, 30, 255))
    img.save(img_path, format="PNG")
    return img_path


@pytest.fixture
def synthetic_webp(tmp_path: Path) -> Path:
    """Create a valid synthetic WEBP image."""
    img_path = tmp_path / "test_synth.webp"
    img = Image.new("RGB", (90, 70), color=(30, 150, 80))
    img.save(img_path, format="WEBP")
    return img_path


@pytest.fixture
def synthetic_heic(tmp_path: Path) -> Path:
    """Create a small valid synthetic HEIC image."""
    img_path = tmp_path / "test_synth.heic"
    img = Image.new("RGB", (60, 40), color=(40, 80, 160))
    img.save(img_path, format="HEIF")
    return img_path


@pytest.fixture
def synthetic_heic_exif_rotated(tmp_path: Path) -> Path:
    """Create a small synthetic HEIC image with EXIF orientation 6 (90 CW)."""
    img_path = tmp_path / "test_heic_rot6.heic"
    img = Image.new("RGB", (80, 40), color=(15, 25, 35))
    exif = img.getexif()
    exif[0x0112] = 6  # Rotate 90 CW (transposes width and height)
    img.save(img_path, format="HEIF", exif=exif.tobytes())
    return img_path


@pytest.fixture
def synthetic_jpeg_exif_rotated(tmp_path: Path) -> Path:
    """Create a synthetic JPEG image with EXIF orientation 6 (90 CW)."""
    img_path = tmp_path / "test_jpeg_rot6.jpg"
    img = Image.new("RGB", (100, 50), color=(80, 120, 160))
    exif = img.getexif()
    exif[0x0112] = 6  # Rotate 90 CW
    img.save(img_path, format="JPEG", exif=exif)
    return img_path


# ============================================================================
# Tests: compute_file_sha256
# ============================================================================

class TestComputeFileSha256:
    def test_sha256_known_content(self, tmp_path: Path) -> None:
        content = b"invoice-processor-test-content-12345"
        expected_hash = hashlib.sha256(content).hexdigest()
        file_path = tmp_path / "hash_sample.bin"
        file_path.write_bytes(content)

        digest = compute_file_sha256(file_path)
        assert digest == expected_hash

    def test_sha256_large_file_chunking(self, tmp_path: Path) -> None:
        # Create a file larger than 64KB chunk buffer (e.g. 150KB)
        content = b"A" * 150000
        expected_hash = hashlib.sha256(content).hexdigest()
        file_path = tmp_path / "large_sample.bin"
        file_path.write_bytes(content)

        digest = compute_file_sha256(file_path)
        assert digest == expected_hash

    def test_sha256_non_existent_file(self, tmp_path: Path) -> None:
        file_path = tmp_path / "non_existent.bin"
        with pytest.raises(FileNotFoundError):
            compute_file_sha256(file_path)


# ============================================================================
# Tests: detect_file_type
# ============================================================================

class TestDetectFileType:
    def test_detect_pdf(self, tmp_path: Path) -> None:
        pdf_path = tmp_path / "sample.pdf"
        pdf_path.write_bytes(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF")
        assert detect_file_type(pdf_path) == "pdf"

    def test_detect_jpeg(self, synthetic_jpeg: Path) -> None:
        assert detect_file_type(synthetic_jpeg) == "jpeg"

    def test_detect_png(self, synthetic_png: Path) -> None:
        assert detect_file_type(synthetic_png) == "png"

    def test_detect_webp(self, synthetic_webp: Path) -> None:
        assert detect_file_type(synthetic_webp) == "webp"

    def test_detect_heic(self, synthetic_heic: Path) -> None:
        assert detect_file_type(synthetic_heic) == "heic"

    def test_detect_heic_brands(self, tmp_path: Path) -> None:
        for brand in [b"heic", b"heix", b"mif1", b"msf1", b"hevc"]:
            f = tmp_path / f"brand_{brand.decode()}.heic"
            # ISOBMFF ftyp box header
            f.write_bytes(b"\x00\x00\x00\x18ftyp" + brand + b"\x00\x00\x00\x00mif1heic")
            assert detect_file_type(f) == "heic"

    def test_detect_heic_compatible_brand(self, tmp_path: Path) -> None:
        f = tmp_path / "compat_brand.heic"
        # Major brand isom, compatible brand mif1/heic
        f.write_bytes(b"\x00\x00\x00\x1cftypisom\x00\x00\x00\x00mif1heic")
        assert detect_file_type(f) == "heic"

    def test_detect_unsupported_text(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.txt"
        f.write_bytes(b"Supplier: Baldor, Total: $125.00")
        assert detect_file_type(f) == "unsupported"

    def test_detect_unsupported_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        assert detect_file_type(f) == "unsupported"

    def test_detect_unsupported_short_file(self, tmp_path: Path) -> None:
        f = tmp_path / "short.bin"
        f.write_bytes(b"123")
        assert detect_file_type(f) == "unsupported"

    def test_detect_unsupported_mp4(self, tmp_path: Path) -> None:
        f = tmp_path / "video.mp4"
        f.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42")
        assert detect_file_type(f) == "unsupported"

    def test_detect_non_existent(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            detect_file_type(tmp_path / "missing.jpg")


# ============================================================================
# Tests: load_image
# ============================================================================

class TestLoadImage:
    def test_load_jpeg_basic(self, synthetic_jpeg: Path) -> None:
        arr, scale = load_image(synthetic_jpeg)
        assert isinstance(arr, np.ndarray)
        assert arr.dtype == np.uint8
        assert arr.shape == (80, 120, 3)
        assert scale == 1.0

    def test_load_png_rgba_converts_to_rgb(self, synthetic_png: Path) -> None:
        arr, scale = load_image(synthetic_png)
        assert isinstance(arr, np.ndarray)
        assert arr.dtype == np.uint8
        assert arr.shape == (60, 100, 3)  # 3 channels (RGB)
        assert scale == 1.0

    def test_load_webp_basic(self, synthetic_webp: Path) -> None:
        arr, scale = load_image(synthetic_webp)
        assert isinstance(arr, np.ndarray)
        assert arr.dtype == np.uint8
        assert arr.shape == (70, 90, 3)
        assert scale == 1.0

    def test_load_heic_basic(self, synthetic_heic: Path) -> None:
        arr, scale = load_image(synthetic_heic)
        assert isinstance(arr, np.ndarray)
        assert arr.dtype == np.uint8
        assert arr.shape == (40, 60, 3)
        assert scale == 1.0

    def test_load_jpeg_exif_transposition(self, synthetic_jpeg_exif_rotated: Path) -> None:
        # Original is width=100, height=50 with orientation 6 (90 CW)
        # Transposed must have width=50, height=100 -> shape (100, 50, 3)
        arr, scale = load_image(synthetic_jpeg_exif_rotated)
        assert arr.shape == (100, 50, 3)
        assert scale == 1.0

    def test_load_heic_exif_transposition(self, synthetic_heic_exif_rotated: Path) -> None:
        # Original is width=80, height=40 with orientation 6 (90 CW)
        # Transposed must have width=40, height=80 -> shape (80, 40, 3)
        arr, scale = load_image(synthetic_heic_exif_rotated)
        assert arr.shape == (80, 40, 3)
        assert scale == 1.0

    def test_dimension_constraint_with_override(self, tmp_path: Path) -> None:
        # Create image 300x150, limit to 100 max dimension
        img_path = tmp_path / "big_override.jpg"
        img = Image.new("RGB", (300, 150), color=(100, 100, 100))
        img.save(img_path, format="JPEG")

        arr, scale = load_image(img_path, max_dimension=100)
        # 300 scaled to 100 -> factor = 100 / 300 = 1/3
        # new width = 100, new height = round(150 * 1/3) = 50
        assert arr.shape == (50, 100, 3)
        assert pytest.approx(scale, rel=1e-3) == (100.0 / 300.0)

    def test_dimension_constraint_default_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Monkeypatch MAX_IMAGE_DIMENSION to 200 to test default constraint
        monkeypatch.setattr("core.ingestion.MAX_IMAGE_DIMENSION", 200)

        img_path = tmp_path / "big_config.png"
        img = Image.new("RGB", (400, 100), color=(50, 50, 50))
        img.save(img_path, format="PNG")

        arr, scale = load_image(img_path)
        assert arr.shape == (50, 200, 3)
        assert pytest.approx(scale, rel=1e-3) == 0.5

    def test_dimension_unconstrained_when_under_limit(self, tmp_path: Path) -> None:
        img_path = tmp_path / "small.png"
        img = Image.new("RGB", (200, 100), color=(50, 50, 50))
        img.save(img_path, format="PNG")

        arr, scale = load_image(img_path, max_dimension=500)
        assert arr.shape == (100, 200, 3)
        assert scale == 1.0

    def test_multi_frame_warning_and_first_frame(self, tmp_path: Path) -> None:
        # Create multi-frame WEBP
        frame1 = Image.new("RGB", (50, 50), color=(255, 0, 0))
        frame2 = Image.new("RGB", (50, 50), color=(0, 255, 0))
        img_path = tmp_path / "animated.webp"
        frame1.save(img_path, format="WEBP", save_all=True, append_images=[frame2], lossless=True)

        with pytest.warns(UserWarning, match="Multi-frame image detected"):
            arr, scale = load_image(img_path)

        assert arr.shape == (50, 50, 3)
        # Red channel of frame 1 is 255, green is 0
        assert arr[0, 0, 0] == 255
        assert arr[0, 0, 1] == 0

    def test_corrupted_image_raises_value_error(self, tmp_path: Path) -> None:
        # Valid JPEG magic bytes but completely corrupted body
        bad_jpg = tmp_path / "corrupt.jpg"
        bad_jpg.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00corrupted_payload_data")

        with pytest.raises(ValueError, match="Corrupted or invalid image file"):
            load_image(bad_jpg)

    def test_random_bytes_raises_value_error(self, tmp_path: Path) -> None:
        garbage = tmp_path / "garbage.jpg"
        garbage.write_bytes(b"This is definitely not an image format at all.")

        with pytest.raises(ValueError, match="Unsupported image format"):
            load_image(garbage)

    def test_wrong_extension_jpeg_named_as_txt(self, tmp_path: Path) -> None:
        # A valid JPEG named .txt
        img_path = tmp_path / "invoice_disguised.txt"
        img = Image.new("RGB", (70, 50), color=(12, 34, 56))
        img.save(img_path, format="JPEG")

        # detect_file_type recognizes it as jpeg by magic bytes
        assert detect_file_type(img_path) == "jpeg"

        # load_image opens it successfully
        arr, scale = load_image(img_path)
        assert arr.shape == (50, 70, 3)
        assert scale == 1.0

    def test_wrong_extension_png_named_as_pdf(self, tmp_path: Path) -> None:
        # A valid PNG named .pdf
        img_path = tmp_path / "invoice_disguised.pdf"
        img = Image.new("RGB", (80, 60), color=(100, 150, 200))
        img.save(img_path, format="PNG")

        assert detect_file_type(img_path) == "png"
        arr, scale = load_image(img_path)
        assert arr.shape == (60, 80, 3)

    def test_wrong_extension_pdf_named_as_jpg(self, tmp_path: Path) -> None:
        # A real PDF named .jpg: detect_file_type says pdf, load_image rejects
        pdf_path = tmp_path / "receipt.jpg"
        pdf_path.write_bytes(b"%PDF-1.4\n%synthetic test pdf\n%%EOF")

        assert detect_file_type(pdf_path) == "pdf"
        with pytest.raises(ValueError, match="Unsupported image format: 'pdf'"):
            load_image(pdf_path)

    def test_non_existent_file_raises_not_found(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.jpg"
        with pytest.raises(FileNotFoundError):
            load_image(missing)
