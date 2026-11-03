"""Global configuration for Invoice Processor.

Defines tolerances, thresholds, categories, units, and constants.
Does NOT contain secrets. Secrets are loaded via .env.ggproproxyserver.
"""

from decimal import Decimal
from enum import Enum


class Category(str, Enum):
    FOOD_INGREDIENTS = "Nguyên vật liệu thực phẩm"
    PACKAGING = "Bao bì/vật dụng"
    UTILITIES = "Điện nước"
    SERVICES = "Dịch vụ"
    OTHER = "Khác"


# Units preserved in product specifications (PLAN 3.4)
SPEC_UNITS = frozenset({
    "OZ", "LB", "ML", "L", "G", "KG", "CT", "PK", "PACK", "CS", "CASE",
    "EA", "GAL", "INCH", "PT", "QT", "FL OZ", "DOZ", "BAG", "BOX", "BTL",
    "CAN", "ROLL", "TUB", "JAR", "TIN", "PIECE", "PAIR", "SET"
})

# Versioning
PROMPT_VERSION = "2026-08-v1"
SCHEMA_VERSION = "1.0"

# LLM & Proxy settings (PLAN 4.1)
DEFAULT_PROXY_URL = "http://127.0.0.1:8045/v1"
DEFAULT_MODEL = "gemini-3.8-flash"
LLM_TIMEOUT_SECONDS = 120
LLM_MAX_RETRIES = 3
LLM_CONCURRENCY = 2
MAX_PAYLOAD_CHARS = 100000

# OCR & Vision thresholds (PLAN 2.1, 2.5)
OCR_CONFIDENCE_THRESHOLD = 0.90
MAX_IMAGE_DIMENSION = 2048
MIN_PRINTABLE_CHARS = 50
MIN_VALID_CHAR_RATIO = 0.85
MAX_IMAGE_AREA_RATIO = 0.80
PDF_RENDER_DPI = 150

# Math tolerances (PLAN 5.4)
TIER1_BASE_TOLERANCE = Decimal("0.01")
TIER1_QTY_FACTOR = Decimal("0.005")  # |qty * price - total| <= 0.01 + 0.005 * |qty|
TIER2_BASE_TOLERANCE = Decimal("0.02")
TIER2_LINE_FACTOR = Decimal("0.005")  # |sum(line_totals) - subtotal| <= 0.02 + 0.005 * n_lines
TIER3_TOLERANCE = Decimal("0.02")  # |subtotal + tax + shipping + tip + fees - discount - grand_total| <= 0.02
TIER4_TOLERANCE = Decimal("0.02")  # |sum(charges) - amount_due| <= 0.02
MIN_CHECKABLE_LINE_RATIO = 0.80
DATE_WINDOW_DAYS = 45

# Date locale default
DEFAULT_DATE_LOCALE = "MM/DD"

# Deduplication (PLAN 6.3)
DEDUP_SIMILARITY_THRESHOLD = 90
