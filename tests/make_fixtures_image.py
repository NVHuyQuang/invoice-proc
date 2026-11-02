"""Synthetic image and receipt fixture generator for Invoice Processor.

Generates synthetic thermal receipts and receipts with EXIF orientations (JPEG, PNG, HEIC)
along with ground-truth metadata in JSON format.

INVARIANTS:
1. NEVER use real invoice data. All generated data is purely synthetic.
2. Deterministic: Fixed random seeds ensure reproducible outputs.
"""

from decimal import Decimal
import io
import json
from pathlib import Path
import random
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
import pillow_heif

# Register pillow_heif for HEIC support
pillow_heif.register_heif_opener()

FIXED_SEED = 42
EXIF_ORIENTATION_TAG = 0x0112


def set_seed(seed: int = FIXED_SEED) -> None:
    """Set global seeds for deterministic generation."""
    random.seed(seed)
    np.random.seed(seed)


def get_font(size: int, bold: bool = False) -> Any:
    """Load system truetype font or fall back to default."""
    candidates = (
        ["arialbd.ttf", "calibrib.ttf", "DejaVuSans-Bold.ttf"]
        if bold
        else ["arial.ttf", "calibri.ttf", "DejaVuSans.ttf"]
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_receipt_canvas(
    vendor_name: str,
    address: str,
    phone: str,
    invoice_no: str,
    invoice_date: str,
    items: List[Dict[str, Any]],
    subtotal: Decimal,
    tax: Decimal,
    grand_total: Decimal,
    width: int = 400,
    height: int = 1450,
    bg_color: Tuple[int, int, int] = (248, 247, 244),
    text_color: Tuple[int, int, int] = (30, 30, 30),
) -> Image.Image:
    """Draw a clean, upright receipt on an image canvas."""
    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    font_title = get_font(20, bold=True)
    font_bold = get_font(15, bold=True)
    font_mono = get_font(14, bold=False)
    font_small = get_font(12, bold=False)

    y = 35

    # Top serration / receipt header margin
    draw.line([(15, y), (width - 15, y)], fill=(200, 200, 200), width=1)
    y += 20

    # Vendor header
    draw.text((width // 2, y), vendor_name, font=font_title, fill=text_color, anchor="mt")
    y += 32
    draw.text((width // 2, y), address, font=font_small, fill=(70, 70, 70), anchor="mt")
    y += 20
    draw.text((width // 2, y), f"TEL: {phone}", font=font_small, fill=(70, 70, 70), anchor="mt")
    y += 26

    # Receipt metadata
    draw.line([(15, y), (width - 15, y)], fill=(120, 120, 120), width=1)
    y += 12
    draw.text((20, y), f"RECEIPT: {invoice_no}", font=font_mono, fill=text_color)
    y += 22
    draw.text((20, y), f"DATE: {invoice_date} 14:32:05", font=font_mono, fill=text_color)
    y += 25
    draw.line([(15, y), (width - 15, y)], fill=(120, 120, 120), width=1)
    y += 12

    # Column header
    draw.text((20, y), "ITEM", font=font_bold, fill=text_color)
    draw.text((220, y), "QTY", font=font_bold, fill=text_color)
    draw.text((275, y), "PRICE", font=font_bold, fill=text_color)
    draw.text((width - 20, y), "TOTAL", font=font_bold, fill=text_color, anchor="rt")
    y += 24
    draw.line([(15, y), (width - 15, y)], fill=(180, 180, 180), width=1)
    y += 16

    # Line items
    for item in items:
        name = item["item_name"]
        qty = str(item["qty"])
        unit = item.get("unit") or ""
        qty_str = f"{qty} {unit}".strip()
        price_str = f"${Decimal(str(item['unit_price'])):.2f}"
        total_str = f"${Decimal(str(item['line_total'])):.2f}"

        draw.text((20, y), name, font=font_mono, fill=text_color)
        y += 20
        draw.text((220, y), qty_str, font=font_small, fill=(60, 60, 60))
        draw.text((275, y), price_str, font=font_small, fill=(60, 60, 60))
        draw.text((width - 20, y), total_str, font=font_mono, fill=text_color, anchor="rt")
        y += 28

    y += 10
    draw.line([(15, y), (width - 15, y)], fill=(120, 120, 120), width=1)
    y += 16

    # Totals
    def draw_total_row(label: str, val_str: str, bold: bool = False, extra_y: int = 24):
        nonlocal y
        f = font_bold if bold else font_mono
        draw.text((160, y), label, font=f, fill=text_color)
        draw.text((width - 20, y), val_str, font=f, fill=text_color, anchor="rt")
        y += extra_y

    draw_total_row("SUBTOTAL:", f"${subtotal:.2f}")
    draw_total_row("TAX:", f"${tax:.2f}")
    draw.line([(150, y), (width - 15, y)], fill=(160, 160, 160), width=1)
    y += 8
    draw_total_row("GRAND TOTAL:", f"${grand_total:.2f}", bold=True, extra_y=32)

    # Payment info
    draw.line([(15, y), (width - 15, y)], fill=(120, 120, 120), width=1)
    y += 16
    draw.text((20, y), "PAYMENT METHOD: VISA **** 4819", font=font_small, fill=(60, 60, 60))
    y += 18
    draw.text((20, y), "AUTH CODE: 088421", font=font_small, fill=(60, 60, 60))
    y += 18
    draw.text((20, y), "CHANGE: $0.00", font=font_small, fill=(60, 60, 60))
    y += 35

    # Footer
    draw.text((width // 2, y), "THANK YOU FOR YOUR BUSINESS!", font=font_bold, fill=text_color, anchor="mt")
    y += 22
    draw.text((width // 2, y), "Please retain receipt for returns", font=font_small, fill=(80, 80, 80), anchor="mt")
    y += 30
    draw.line([(15, y), (width - 15, y)], fill=(200, 200, 200), width=1)

    return img


def apply_skew(img_bgr: np.ndarray, angle_deg: float, bg_color: Tuple[int, int, int] = (248, 247, 244)) -> np.ndarray:
    """Rotate image by angle_deg without clipping corners."""
    h, w = img_bgr.shape[:2]
    center = (w / 2.0, h / 2.0)
    M = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    cos = np.abs(M[0, 0])
    sin = np.abs(M[0, 1])
    new_w = int((h * sin) + (w * cos))
    new_h = int((h * cos) + (w * sin))
    M[0, 2] += (new_w / 2.0) - center[0]
    M[1, 2] += (new_h / 2.0) - center[1]
    return cv2.warpAffine(img_bgr, M, (new_w, new_h), borderMode=cv2.BORDER_CONSTANT, borderValue=bg_color)


def add_noise_and_blur(
    img_bgr: np.ndarray,
    blur_ksize: int = 3,
    noise_std: float = 3.5,
) -> np.ndarray:
    """Simulate thermal print blur and sensor noise."""
    blurred = cv2.GaussianBlur(img_bgr, (blur_ksize, blur_ksize), 0.6)
    noise = np.random.normal(0, noise_std, img_bgr.shape).astype(np.float32)
    noisy = np.clip(blurred.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return noisy


def make_faded_low_contrast(
    img_bgr: np.ndarray,
    alpha: float = 0.35,
    beta: float = 155.0,
) -> np.ndarray:
    """Simulate faded thermal receipt with low contrast (grayscale std < 40)."""
    return cv2.convertScaleAbs(img_bgr, alpha=alpha, beta=beta)


def save_with_exif_orientation(
    img_pil: Image.Image,
    out_path: Path,
    file_format: str,
    orientation: int,
) -> None:
    """Save image with EXIF orientation tag."""
    # Rotate raw pixels so that orientation tag correctly restores upright orientation:
    # Orientation 6: Rotate 90 CW to restore upright -> raw pixels are rotated 90 CCW
    # Orientation 8: Rotate 270 CW to restore upright -> raw pixels are rotated 90 CW (270 CCW)
    # Orientation 3: Rotate 180 to restore upright -> raw pixels are rotated 180
    if orientation == 6:
        stored = img_pil.transpose(Image.Transpose.ROTATE_90)
    elif orientation == 8:
        stored = img_pil.transpose(Image.Transpose.ROTATE_270)
    elif orientation == 3:
        stored = img_pil.transpose(Image.Transpose.ROTATE_180)
    else:
        stored = img_pil

    exif = stored.getexif()
    exif[EXIF_ORIENTATION_TAG] = orientation

    if file_format.upper() in ("JPEG", "JPG"):
        stored.save(out_path, format="JPEG", exif=exif, quality=95)
    elif file_format.upper() == "PNG":
        stored.save(out_path, format="PNG", exif=exif)
    elif file_format.upper() in ("HEIF", "HEIC"):
        stored.save(out_path, format="HEIF", exif=exif)
    else:
        stored.save(out_path, format=file_format)


def build_truth_dict(
    source_file: str,
    vendor_name: str,
    invoice_no: str,
    invoice_date: str,
    category: str,
    items: List[Dict[str, Any]],
    subtotal: Decimal,
    tax: Decimal,
    grand_total: Decimal,
    doc_type: str = "receipt",
    status: str = "VERIFIED",
) -> Dict[str, Any]:
    """Construct canonical truth dictionary for ground-truth evaluation."""
    line_items = []
    for it in items:
        line_items.append(
            {
                "item_name": it["item_name"],
                "qty": str(it["qty"]),
                "unit_price": f"{Decimal(str(it['unit_price'])):.2f}",
                "line_total": f"{Decimal(str(it['line_total'])):.2f}",
                "unit": it.get("unit"),
                "kind": "goods",
            }
        )

    return {
        "source_file": source_file,
        "vendor_name": vendor_name,
        "invoice_no": invoice_no,
        "invoice_date": invoice_date,
        "due_date": None,
        "currency": "USD",
        "category": category,
        "status": status,
        "doc_type": doc_type,
        "line_items": line_items,
        "charges": [],
        "subtotal": f"{subtotal:.2f}",
        "tax": f"{tax:.2f}",
        "discount": "0.00",
        "shipping": None,
        "tip": None,
        "fees": [],
        "grand_total": f"{grand_total:.2f}",
        "amount_due": f"{grand_total:.2f}",
    }


def generate_all_fixtures(output_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Generate all synthetic thermal and EXIF-oriented fixtures."""
    set_seed(FIXED_SEED)

    if output_dir is None:
        base_dir = Path(__file__).resolve().parent
        output_dir = base_dir / "fixtures" / "image"

    output_dir.mkdir(parents=True, exist_ok=True)

    fixtures_meta = []
    truth_all: Dict[str, Any] = {}

    # -------------------------------------------------------------------------
    # Fixture 1: Narrow thermal receipt (aspect ratio > 3:1), skewed 1.5 deg,
    # with noise and blur
    # -------------------------------------------------------------------------
    fn1 = "thermal_receipt_narrow_skewed.png"
    v1 = "GREEN GROVE MARKET #42"
    inv1 = "REC-2026-0815-42"
    date1 = "2026-08-15"
    cat1 = "Nguyên vật liệu thực phẩm"
    items1 = [
        {"item_name": "ORGANIC WHOLE MILK 1 GAL", "qty": Decimal("2"), "unit": "GAL", "unit_price": Decimal("4.50"), "line_total": Decimal("9.00")},
        {"item_name": "SOURDOUGH BREAD LOAF", "qty": Decimal("3"), "unit": "EA", "unit_price": Decimal("5.25"), "line_total": Decimal("15.75")},
        {"item_name": "ROASTED COFFEE BEANS 12OZ", "qty": Decimal("1"), "unit": "OZ", "unit_price": Decimal("14.99"), "line_total": Decimal("14.99")},
        {"item_name": "ORGANIC EGGS DOZEN", "qty": Decimal("2"), "unit": "DOZ", "unit_price": Decimal("4.20"), "line_total": Decimal("8.40")},
        {"item_name": "PAPER NAPKINS 200CT", "qty": Decimal("1"), "unit": "PK", "unit_price": Decimal("8.50"), "line_total": Decimal("8.50")},
    ]
    subtotal1 = Decimal("56.64")
    tax1 = Decimal("2.83")
    total1 = Decimal("59.47")

    canvas1 = render_receipt_canvas(
        v1, "456 OAK AVENUE, METROPOLIS", "(555) 019-2834",
        inv1, date1, items1, subtotal1, tax1, total1,
        width=400, height=1450,
    )
    bgr1 = cv2.cvtColor(np.array(canvas1), cv2.COLOR_RGB2BGR)
    skewed1 = apply_skew(bgr1, angle_deg=1.5, bg_color=(248, 247, 244))
    noisy1 = add_noise_and_blur(skewed1, blur_ksize=3, noise_std=3.5)
    aspect_ratio1 = noisy1.shape[0] / noisy1.shape[1]
    cv2.imwrite(str(output_dir / fn1), noisy1)

    truth1 = build_truth_dict(fn1, v1, inv1, date1, cat1, items1, subtotal1, tax1, total1)
    fixtures_meta.append({
        "filename": fn1,
        "format": "PNG",
        "aspect_ratio": round(aspect_ratio1, 3),
        "skew_angle": 1.5,
        "exif_orientation": 1,
        "truth": truth1,
    })

    # -------------------------------------------------------------------------
    # Fixture 2: Faded low-contrast thermal receipt (aspect ratio > 3:1, std < 40)
    # -------------------------------------------------------------------------
    fn2 = "thermal_receipt_faded.jpg"
    v2 = "CORNER BISTRO & SUPPLIES"
    inv2 = "CBS-2026-9012"
    date2 = "2026-08-18"
    cat2 = "Nguyên vật liệu thực phẩm"
    items2 = [
        {"item_name": "EXTRA VIRGIN OLIVE OIL 1L", "qty": Decimal("2"), "unit": "L", "unit_price": Decimal("18.50"), "line_total": Decimal("37.00")},
        {"item_name": "BALSAMIC VINEGAR 500ML", "qty": Decimal("1"), "unit": "ML", "unit_price": Decimal("9.75"), "line_total": Decimal("9.75")},
        {"item_name": "SEA SALT COARSE 1KG", "qty": Decimal("4"), "unit": "KG", "unit_price": Decimal("3.25"), "line_total": Decimal("13.00")},
        {"item_name": "BLACK PEPPERCORNS 8OZ", "qty": Decimal("2"), "unit": "OZ", "unit_price": Decimal("6.50"), "line_total": Decimal("13.00")},
    ]
    subtotal2 = Decimal("72.75")
    tax2 = Decimal("5.82")
    total2 = Decimal("78.57")

    canvas2 = render_receipt_canvas(
        v2, "101 MARKET ST, SPRINGFIELD", "(555) 321-9876",
        inv2, date2, items2, subtotal2, tax2, total2,
        width=380, height=1300,
    )
    bgr2 = cv2.cvtColor(np.array(canvas2), cv2.COLOR_RGB2BGR)
    faded2 = make_faded_low_contrast(bgr2, alpha=0.35, beta=155.0)
    faded_noisy2 = add_noise_and_blur(faded2, blur_ksize=3, noise_std=2.0)
    gray2 = cv2.cvtColor(faded_noisy2, cv2.COLOR_BGR2GRAY)
    gray_std2 = float(np.std(np.asarray(gray2, dtype=np.float64)))
    aspect_ratio2 = faded_noisy2.shape[0] / faded_noisy2.shape[1]
    cv2.imwrite(str(output_dir / fn2), faded_noisy2, [int(cv2.IMWRITE_JPEG_QUALITY), 95])

    truth2 = build_truth_dict(fn2, v2, inv2, date2, cat2, items2, subtotal2, tax2, total2)
    fixtures_meta.append({
        "filename": fn2,
        "format": "JPEG",
        "aspect_ratio": round(aspect_ratio2, 3),
        "skew_angle": 0.0,
        "contrast_std": round(gray_std2, 2),
        "exif_orientation": 1,
        "truth": truth2,
    })

    # -------------------------------------------------------------------------
    # Fixture 3: JPEG with EXIF Orientation 6 (rotated 90 CW)
    # -------------------------------------------------------------------------
    fn3 = "receipt_exif_rot90.jpg"
    v3 = "METRO RESTAURANT DEPOT"
    inv3 = "MRD-8841-2026"
    date3 = "2026-08-10"
    cat3 = "Nguyên vật liệu thực phẩm"
    items3 = [
        {"item_name": "ALL PURPOSE FLOUR 25LB", "qty": Decimal("2"), "unit": "LB", "unit_price": Decimal("16.50"), "line_total": Decimal("33.00")},
        {"item_name": "CANE SUGAR 10LB", "qty": Decimal("3"), "unit": "LB", "unit_price": Decimal("8.20"), "line_total": Decimal("24.60")},
        {"item_name": "UNSALTED BUTTER 1LB", "qty": Decimal("10"), "unit": "LB", "unit_price": Decimal("4.10"), "line_total": Decimal("41.00")},
    ]
    subtotal3 = Decimal("98.60")
    tax3 = Decimal("0.00")
    total3 = Decimal("98.60")

    canvas3 = render_receipt_canvas(
        v3, "789 PINE RD, METROPOLIS", "(555) 765-4321",
        inv3, date3, items3, subtotal3, tax3, total3,
        width=400, height=1200,
    )
    save_with_exif_orientation(canvas3, output_dir / fn3, file_format="JPEG", orientation=6)

    truth3 = build_truth_dict(fn3, v3, inv3, date3, cat3, items3, subtotal3, tax3, total3)
    fixtures_meta.append({
        "filename": fn3,
        "format": "JPEG",
        "aspect_ratio": round(1200 / 400, 3),
        "skew_angle": 0.0,
        "exif_orientation": 6,
        "truth": truth3,
    })

    # -------------------------------------------------------------------------
    # Fixture 4: JPEG with EXIF Orientation 3 (rotated 180 deg)
    # -------------------------------------------------------------------------
    fn4 = "receipt_exif_rot180.jpg"
    v4 = "PACIFIC CLEANING & PACKAGING"
    inv4 = "PCP-4019-AUG26"
    date4 = "2026-08-22"
    cat4 = "Bao bì/vật dụng"
    items4 = [
        {"item_name": "TAKEOUT CONTAINER 9X9 150CT", "qty": Decimal("2"), "unit": "CT", "unit_price": Decimal("32.00"), "line_total": Decimal("64.00")},
        {"item_name": "BIODEGRADABLE FORKS 500CT", "qty": Decimal("1"), "unit": "CT", "unit_price": Decimal("18.50"), "line_total": Decimal("18.50")},
        {"item_name": "CLEAR DRINK CUPS 16OZ 1000CT", "qty": Decimal("1"), "unit": "CT", "unit_price": Decimal("45.00"), "line_total": Decimal("45.00")},
    ]
    subtotal4 = Decimal("127.50")
    tax4 = Decimal("10.20")
    total4 = Decimal("137.70")

    canvas4 = render_receipt_canvas(
        v4, "222 INDUSTRIAL BLVD", "(555) 889-1122",
        inv4, date4, items4, subtotal4, tax4, total4,
        width=400, height=1200,
    )
    save_with_exif_orientation(canvas4, output_dir / fn4, file_format="JPEG", orientation=3)

    truth4 = build_truth_dict(fn4, v4, inv4, date4, cat4, items4, subtotal4, tax4, total4)
    fixtures_meta.append({
        "filename": fn4,
        "format": "JPEG",
        "aspect_ratio": round(1200 / 400, 3),
        "skew_angle": 0.0,
        "exif_orientation": 3,
        "truth": truth4,
    })

    # -------------------------------------------------------------------------
    # Fixture 5: PNG with EXIF Orientation 8 (rotated 270 CW / 90 CCW)
    # -------------------------------------------------------------------------
    fn5 = "receipt_exif_rot270.png"
    v5 = "VALLEY FRESH WHOLESALE"
    inv5 = "VFW-20260825-7"
    date5 = "2026-08-25"
    cat5 = "Nguyên vật liệu thực phẩm"
    items5 = [
        {"item_name": "ROMAINE LETTUCE 24CT", "qty": Decimal("2"), "unit": "CT", "unit_price": Decimal("22.00"), "line_total": Decimal("44.00")},
        {"item_name": "CHERRY TOMATOES 12PT", "qty": Decimal("1"), "unit": "PT", "unit_price": Decimal("19.50"), "line_total": Decimal("19.50")},
        {"item_name": "RED ONIONS 25LB", "qty": Decimal("1"), "unit": "LB", "unit_price": Decimal("16.00"), "line_total": Decimal("16.00")},
        {"item_name": "CUCUMBERS 1 CS", "qty": Decimal("1"), "unit": "CS", "unit_price": Decimal("21.00"), "line_total": Decimal("21.00")},
    ]
    subtotal5 = Decimal("100.50")
    tax5 = Decimal("0.00")
    total5 = Decimal("100.50")

    canvas5 = render_receipt_canvas(
        v5, "33 BROADWAY, NEW YORK", "(555) 998-3344",
        inv5, date5, items5, subtotal5, tax5, total5,
        width=400, height=1300,
    )
    save_with_exif_orientation(canvas5, output_dir / fn5, file_format="PNG", orientation=8)

    truth5 = build_truth_dict(fn5, v5, inv5, date5, cat5, items5, subtotal5, tax5, total5)
    fixtures_meta.append({
        "filename": fn5,
        "format": "PNG",
        "aspect_ratio": round(1300 / 400, 3),
        "skew_angle": 0.0,
        "exif_orientation": 8,
        "truth": truth5,
    })

    # -------------------------------------------------------------------------
    # Fixture 6: HEIC receipt with EXIF Orientation 6 (simulating iPhone photo)
    # -------------------------------------------------------------------------
    fn6 = "receipt_iphone_exif.heic"
    v6 = "HARBOR VIEW PROVISIONS"
    inv6 = "HVP-2026-0829"
    date6 = "2026-08-29"
    cat6 = "Nguyên vật liệu thực phẩm"
    items6 = [
        {"item_name": "WILD SALMON FILLET 5LB", "qty": Decimal("2"), "unit": "LB", "unit_price": Decimal("48.00"), "line_total": Decimal("96.00")},
        {"item_name": "GULF SHRIMP 16/20 5LB", "qty": Decimal("1"), "unit": "LB", "unit_price": Decimal("55.00"), "line_total": Decimal("55.00")},
        {"item_name": "LEMONS FRESH 1 CS", "qty": Decimal("1"), "unit": "CS", "unit_price": Decimal("24.50"), "line_total": Decimal("24.50")},
    ]
    subtotal6 = Decimal("175.50")
    tax6 = Decimal("0.00")
    total6 = Decimal("175.50")

    canvas6 = render_receipt_canvas(
        v6, "55 HARBOR WAY, BOSTON", "(555) 441-2299",
        inv6, date6, items6, subtotal6, tax6, total6,
        width=400, height=1250,
    )
    save_with_exif_orientation(canvas6, output_dir / fn6, file_format="HEIF", orientation=6)

    truth6 = build_truth_dict(fn6, v6, inv6, date6, cat6, items6, subtotal6, tax6, total6)
    fixtures_meta.append({
        "filename": fn6,
        "format": "HEIC",
        "aspect_ratio": round(1250 / 400, 3),
        "skew_angle": 0.0,
        "exif_orientation": 6,
        "truth": truth6,
    })

    # -------------------------------------------------------------------------
    # Save individual .truth.json and combined truth.json
    # -------------------------------------------------------------------------
    for meta in fixtures_meta:
        fname = meta["filename"]
        stem = Path(fname).stem
        t_dict = meta["truth"]

        # Write <filename>.truth.json
        with open(output_dir / f"{fname}.truth.json", "w", encoding="utf-8") as f:
            json.dump(t_dict, f, indent=2, ensure_ascii=False)

        # Write <stem>.truth.json
        with open(output_dir / f"{stem}.truth.json", "w", encoding="utf-8") as f:
            json.dump(t_dict, f, indent=2, ensure_ascii=False)

        truth_all[fname] = t_dict
        truth_all[stem] = t_dict

    with open(output_dir / "truth.json", "w", encoding="utf-8") as f:
        json.dump(truth_all, f, indent=2, ensure_ascii=False)

    return fixtures_meta


def main() -> None:
    """CLI entrypoint for generating synthetic image fixtures."""
    print("Generating synthetic thermal and EXIF-oriented image fixtures...")
    fixtures = generate_all_fixtures()
    print(f"Successfully generated {len(fixtures)} fixtures:")
    for fx in fixtures:
        print(f"  - {fx['filename']} ({fx['format']}): AR={fx['aspect_ratio']}, Skew={fx['skew_angle']}deg, EXIF_orient={fx['exif_orientation']}")
    print("Truth files written: *.truth.json and truth.json")


if __name__ == "__main__":
    main()
