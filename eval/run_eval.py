"""Phase 7 Evaluation and Metric Calculation Module.

PLAN 7.1:
- False-verify rate: ratio of VERIFIED invoices where at least one key field differs from ground truth.
  Target is 0.0 on golden set (critical invariant: false auto-verification is far worse than review).
- Automation rate: ratio of VERIFIED invoices out of total processed files.
- Per-field accuracy: vendor_name, invoice_no, invoice_date, subtotal, tax, grand_total, category.
- Line items accuracy: matching item/qty/price/total.
- Speed: average seconds per page (overall and per branch: pdf_text, ocr).
- Clean summary report presentation.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from decimal import Decimal
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Sequence, Union

logger = logging.getLogger(__name__)

EVALUATED_FIELDS = (
    "vendor_name",
    "invoice_no",
    "invoice_date",
    "subtotal",
    "tax",
    "grand_total",
    "category",
)


def _to_decimal(val: Any) -> Optional[Decimal]:
    """Parse value to Decimal if possible."""
    if val is None or val == "":
        return None
    try:
        cleaned = str(val).replace(",", "").replace("$", "").strip()
        return Decimal(cleaned)
    except Exception:
        return None


def _normalize_str(val: Any) -> str:
    """Normalize string for robust comparison."""
    if val is None:
        return ""
    return str(val).strip().lower()


def _compare_field_values(pred_val: Any, truth_val: Any, field_name: str) -> bool:
    """Compare predicted field against ground truth field."""
    # Both None / empty
    if (pred_val is None or pred_val == "") and (truth_val is None or truth_val == ""):
        return True

    # One is missing
    if (pred_val is None or pred_val == "") != (truth_val is None or truth_val == ""):
        return False

    # Monetary fields comparison
    if field_name in ("subtotal", "tax", "grand_total"):
        d_pred = _to_decimal(pred_val)
        d_truth = _to_decimal(truth_val)
        if d_pred is not None and d_truth is not None:
            return abs(d_pred - d_truth) < Decimal("0.02")
        return str(pred_val).strip() == str(truth_val).strip()

    # Vendor / text / category / date normalization
    s_pred = _normalize_str(pred_val)
    s_truth = _normalize_str(truth_val)
    return s_pred == s_truth


@dataclass
class EvalReport:
    """Evaluation summary metrics container."""

    total_files: int = 0
    verified_count: int = 0
    review_needed_count: int = 0
    failed_count: int = 0
    duplicate_count: int = 0
    false_verify_count: int = 0

    automation_rate: float = 0.0
    false_verify_rate: float = 0.0

    field_accuracy: Dict[str, float] = field(default_factory=dict)
    field_counts: Dict[str, int] = field(default_factory=dict)
    field_correct: Dict[str, int] = field(default_factory=dict)

    line_items_accuracy: float = 0.0

    total_duration_sec: float = 0.0
    total_pages: int = 0
    seconds_per_page: float = 0.0
    branch_seconds_per_page: Dict[str, float] = field(default_factory=dict)

    file_discrepancies: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert report metrics to dictionary."""
        return {
            "total_files": self.total_files,
            "verified_count": self.verified_count,
            "review_needed_count": self.review_needed_count,
            "failed_count": self.failed_count,
            "duplicate_count": self.duplicate_count,
            "false_verify_count": self.false_verify_count,
            "automation_rate": round(self.automation_rate, 4),
            "false_verify_rate": round(self.false_verify_rate, 4),
            "field_accuracy": {k: round(v, 4) for k, v in self.field_accuracy.items()},
            "line_items_accuracy": round(self.line_items_accuracy, 4),
            "total_duration_sec": round(self.total_duration_sec, 2),
            "total_pages": self.total_pages,
            "seconds_per_page": round(self.seconds_per_page, 4),
            "branch_seconds_per_page": {
                k: round(v, 4) for k, v in self.branch_seconds_per_page.items()
            },
        }

    def print_report(self) -> None:
        """Print formatted terminal report table."""
        print("\n" + "=" * 60)
        print("                 PHASE 7 EVALUATION REPORT")
        print("=" * 60)
        print(f"  Tổng số tài liệu:          {self.total_files}")
        print(f"  Số VERIFIED (tự động):     {self.verified_count} ({self.automation_rate * 100:.1f}%)")
        print(f"  Số REVIEW_NEEDED:          {self.review_needed_count}")
        print(f"  Số FAILED:                 {self.failed_count}")
        print(f"  Số DUPLICATE:              {self.duplicate_count}")
        print("-" * 60)
        print(f"  FALSE-VERIFY COUNT:        {self.false_verify_count}")
        print(f"  FALSE-VERIFY RATE:         {self.false_verify_rate * 100:.2f}% (Target: 0.00%)")
        print("-" * 60)
        print("  ĐỘ CHÍNH XÁC THEO TRƯỜNG (Field Accuracy):")
        for fld in EVALUATED_FIELDS:
            acc = self.field_accuracy.get(fld, 0.0) * 100
            corr = self.field_correct.get(fld, 0)
            tot = self.field_counts.get(fld, 0)
            print(f"    - {fld:<16}: {acc:6.1f}% ({corr}/{tot})")
        if "line_items" in self.field_accuracy:
            acc = self.field_accuracy["line_items"] * 100
            print(f"    - line_items      : {acc:6.1f}%")
        print("-" * 60)
        print(f"  TỔNG THỜI GIAN:            {self.total_duration_sec:.2f}s")
        print(f"  TỔNG SỐ TRANG:             {self.total_pages}")
        print(f"  TỐC ĐỘ (giây/trang):       {self.seconds_per_page:.3f} s/trang")
        if self.branch_seconds_per_page:
            for br, spd in self.branch_seconds_per_page.items():
                print(f"    - Nhánh {br:<12}: {spd:.3f} s/trang")
        print("=" * 60 + "\n")


def _match_source_key(source_name: str, keys: Sequence[str]) -> Optional[str]:
    """Match prediction source file path to ground truth keys."""
    if source_name in keys:
        return source_name

    p = Path(source_name)
    # Check by filename
    if p.name in keys:
        return p.name

    # Check by stem
    if p.stem in keys:
        return p.stem

    # Check without extension or suffix match
    for k in keys:
        if Path(k).name == p.name or Path(k).stem == p.stem or k.endswith(source_name):
            return k
    return None


def run_evaluation(
    predictions: Sequence[Union[dict, Any]],
    ground_truths: Union[Sequence[dict], Dict[str, dict]],
    timing_data: Optional[Dict[str, Any]] = None,
) -> EvalReport:
    """Evaluate pipeline predictions against ground truth labels.

    Args:
        predictions: Sequence of prediction dicts or CanonicalInvoice instances.
        ground_truths: Ground truth records as dict mapping or list.
        timing_data: Optional execution timing metrics (duration, pages, branch data).

    Returns:
        EvalReport instance containing all calculated Phase 7 metrics.
    """
    report = EvalReport()

    # Index ground truths
    truth_map: Dict[str, dict] = {}
    if isinstance(ground_truths, dict):
        truth_map = ground_truths
    else:
        for item in ground_truths:
            src = item.get("source_file") or item.get("file_name") or ""
            if src:
                truth_map[src] = item
                truth_map[Path(src).name] = item

    # Initialize field counters
    for fld in EVALUATED_FIELDS:
        report.field_counts[fld] = 0
        report.field_correct[fld] = 0

    evaluated_count = 0
    line_item_scores: List[float] = []

    for pred in predictions:
        pred_dict = pred.to_jsonl_dict() if hasattr(pred, "to_jsonl_dict") else dict(pred)
        src = str(pred_dict.get("source_file", ""))
        status = pred_dict.get("status")
        if hasattr(status, "value"):
            status = status.value
        status_str = str(status or "").upper()

        if status_str == "VERIFIED":
            report.verified_count += 1
        elif status_str == "REVIEW_NEEDED":
            report.review_needed_count += 1
        elif status_str == "FAILED":
            report.failed_count += 1
        elif status_str == "DUPLICATE" or pred_dict.get("is_duplicate"):
            report.duplicate_count += 1

        # Find matching truth
        truth_key = _match_source_key(src, list(truth_map.keys()))
        if not truth_key:
            continue

        truth = truth_map[truth_key]
        evaluated_count += 1

        is_doc_correct = True
        discrepancies: Dict[str, Any] = {}

        # Evaluate fields
        for fld in EVALUATED_FIELDS:
            if fld in truth and truth[fld] is not None:
                report.field_counts[fld] += 1
                pred_val = pred_dict.get(fld)
                truth_val = truth.get(fld)
                match = _compare_field_values(pred_val, truth_val, fld)
                if match:
                    report.field_correct[fld] += 1
                else:
                    is_doc_correct = False
                    discrepancies[fld] = {"pred": pred_val, "truth": truth_val}

        # Evaluate line items if present
        if "line_items" in truth and isinstance(truth["line_items"], list) and truth["line_items"]:
            t_items = truth["line_items"]
            p_items = pred_dict.get("line_items", []) or []
            matched_items = 0
            for t_item in t_items:
                t_name = _normalize_str(t_item.get("item_name"))
                t_tot = _to_decimal(t_item.get("line_total"))
                for p_item in p_items:
                    p_name = _normalize_str(p_item.get("item_name"))
                    p_tot = _to_decimal(p_item.get("line_total"))
                    name_match = (t_name in p_name) or (p_name in t_name)
                    tot_match = (t_tot == p_tot) if (t_tot is not None and p_tot is not None) else True
                    if name_match and tot_match:
                        matched_items += 1
                        break
            item_acc = matched_items / max(1, len(t_items))
            line_item_scores.append(item_acc)

        # False-verify check:
        # A document was marked VERIFIED by the pipeline, but ground truth comparison had errors
        if status_str == "VERIFIED" and not is_doc_correct:
            report.false_verify_count += 1
            report.file_discrepancies.append({
                "source_file": src,
                "discrepancies": discrepancies,
            })

    report.total_files = len(predictions) if predictions else len(truth_map)
    if report.total_files > 0:
        report.automation_rate = report.verified_count / report.total_files

    if report.verified_count > 0:
        report.false_verify_rate = report.false_verify_count / report.verified_count
    else:
        report.false_verify_rate = 0.0

    # Calculate field accuracies
    for fld in EVALUATED_FIELDS:
        cnt = report.field_counts.get(fld, 0)
        corr = report.field_correct.get(fld, 0)
        report.field_accuracy[fld] = (corr / cnt) if cnt > 0 else 1.0

    if line_item_scores:
        report.line_items_accuracy = sum(line_item_scores) / len(line_item_scores)
        report.field_accuracy["line_items"] = report.line_items_accuracy

    # Process timing data
    if timing_data:
        report.total_duration_sec = float(timing_data.get("total_duration_sec", 0.0))
        report.total_pages = int(timing_data.get("total_pages", 0))
        if report.total_pages > 0 and report.total_duration_sec > 0:
            report.seconds_per_page = report.total_duration_sec / report.total_pages
        elif timing_data.get("seconds_per_page"):
            report.seconds_per_page = float(timing_data["seconds_per_page"])

        if "branch_seconds_per_page" in timing_data:
            report.branch_seconds_per_page = dict(timing_data["branch_seconds_per_page"])
    else:
        # Calculate pages from ground truths if available
        pages_sum = sum(
            int(t.get("page_count", 1)) for t in truth_map.values() if isinstance(t, dict)
        )
        report.total_pages = max(1, pages_sum)

    return report


def load_records_from_path(path: Union[str, Path]) -> List[dict]:
    """Load JSON or JSONL records from file or directory."""
    p = Path(path)
    records: List[dict] = []

    if not p.exists():
        logger.warning("Path does not exist: %s", p)
        return records

    if p.is_file():
        if p.suffix == ".jsonl":
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        else:
            with open(p, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, list):
                    records.extend(content)
                elif isinstance(content, dict):
                    records.append(content)
    elif p.is_dir():
        for file in sorted(p.rglob("*.json")):
            with open(file, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    if isinstance(data, list):
                        records.extend(data)
                    elif isinstance(data, dict):
                        records.append(data)
                except Exception as e:
                    logger.warning("Failed to load %s: %s", file, e)

    return records


def parse_eval_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse eval CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="run_eval.py",
        description="Phase 7 Evaluation Runner: calculates False-verify rate, field accuracy, and speed.",
    )
    parser.add_argument(
        "--golden",
        required=True,
        help="Path to golden set directory or JSON/JSONL file",
    )
    parser.add_argument(
        "--predictions",
        required=True,
        help="Path to pipeline predictions (invoices.jsonl)",
    )
    parser.add_argument(
        "--timing",
        default=None,
        help="Optional path to timing JSON data (duration, page counts)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output path for evaluation JSON report",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI execution entrypoint."""
    args = parse_eval_args(argv)

    golden_records = load_records_from_path(args.golden)
    pred_records = load_records_from_path(args.predictions)

    if not golden_records:
        logger.error("No golden records loaded from %s", args.golden)
        return 1
    if not pred_records:
        logger.error("No predictions loaded from %s", args.predictions)
        return 1

    timing_data = None
    if args.timing and Path(args.timing).is_file():
        with open(args.timing, "r", encoding="utf-8") as f:
            timing_data = json.load(f)

    report = run_evaluation(pred_records, golden_records, timing_data=timing_data)
    report.print_report()

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"Report written to: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
