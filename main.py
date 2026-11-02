"""CLI entrypoint for Invoice Processor.

PLAN 6.4:
Usage:
python main.py <path> [--month 2026-08] [--out output] [--only <file>] [--workers 2] [--no-cache] [--dry-run]
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from pathlib import Path
import sys
import time
from typing import List, Optional

from tqdm import tqdm

from core.dedup import deduplicate_invoices
from core.llm_cache import LLMCache
from core.llm_parser import LLMClient
from core.ocr_engine import OCREngine
from core.pipeline import process_invoice_file
from exporters.excel_exporter import export_excel_summary
from exporters.jsonl_exporter import JSONLExporter
from models.schema import CanonicalInvoice, InvoiceStatus

logger = logging.getLogger("invoice_processor")

VALID_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic"})


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Invoice Processor CLI: extract, mask, validate, and export invoice data.",
    )
    parser.add_argument(
        "path",
        help="Path to invoice directory or single file",
    )
    parser.add_argument(
        "--month",
        default="2026-08",
        help="Target processing month (YYYY-MM), default: 2026-08",
    )
    parser.add_argument(
        "--out",
        default="output",
        help="Output directory (default: 'output')",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Process only a specific file for debugging",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Number of worker threads (ThreadPoolExecutor, default: 2)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable LLM cache (default uses cache at cache/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run up to mask & Leak Guard, print masked payload to stdout, and halt (DO NOT call LLM)",
    )
    return parser.parse_args(argv)


def find_files(target_path: Path, only_filter: Optional[str] = None) -> List[Path]:
    """Find candidate invoice files matching extensions and optional --only filter.

    Args:
        target_path: Path to file or folder.
        only_filter: Optional file name or path filter.

    Returns:
        List of Path objects to process.
    """
    if not target_path.exists():
        return []

    if target_path.is_file():
        candidates = [target_path]
    else:
        candidates = sorted(
            [
                p
                for p in target_path.rglob("*")
                if p.is_file() and p.suffix.lower() in VALID_EXTENSIONS
            ]
        )

    if not only_filter:
        return candidates

    # Filter with --only
    only_path = Path(only_filter)
    if only_path.is_file():
        return [only_path]

    relative_to_target = target_path / only_filter
    if relative_to_target.is_file():
        return [relative_to_target]

    matched = [
        p
        for p in candidates
        if p.name == only_filter
        or str(p) == only_filter
        or p.stem == only_filter
        or p.name.lower() == only_filter.lower()
    ]
    return matched


def _print_summary(
    total_files: int,
    num_verified: int,
    num_review: int,
    num_failed: int,
    num_duplicate: int,
    duration: float,
) -> None:
    """Print final execution summary table."""
    print("\n" + "=" * 50)
    print("              BẢNG TỔNG KẾT XỬ LÝ HÓA ĐƠN")
    print("=" * 50)
    print(f"  Tổng số file:       {total_files}")
    print(f"  Số VERIFIED:        {num_verified}")
    print(f"  Số REVIEW_NEEDED:   {num_review}")
    print(f"  Số FAILED:          {num_failed}")
    print(f"  Số DUPLICATE:       {num_duplicate}")
    print(f"  Thời gian chạy:     {duration:.2f}s")
    print("=" * 50 + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI execution flow."""
    args = parse_args(argv)

    # Configure logging
    if args.dry_run:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    elif args.only:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
        logger.setLevel(logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    target_path = Path(args.path)
    if not target_path.exists():
        logger.error("Path does not exist: %s", target_path)
        return 1

    files = find_files(target_path, only_filter=args.only)
    if args.only and not files:
        logger.error("Specified file for --only not found: %s", args.only)
        return 1

    start_time = time.time()

    # Initialize components
    cache = None if args.no_cache else LLMCache(cache_dir="cache")
    llm_client = LLMClient()
    ocr_engine = OCREngine()

    # 1. Dry-run branch: halts after Leak Guard, prints masked payload to stdout, DO NOT call LLM
    if args.dry_run:
        for file_path in files:
            process_invoice_file(
                file_path=file_path,
                llm_client=llm_client,
                ocr_engine=ocr_engine,
                cache=None,
                target_month=args.month,
                dry_run=True,
            )
        return 0

    if not files:
        logger.warning("No invoice files found to process.")
        _print_summary(0, 0, 0, 0, 0, time.time() - start_time)
        return 0

    # 2. Output directory and streaming exporters setup
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "invoices.jsonl"
    failure_path = out_dir / "failures.jsonl"

    # Ensure both output jsonl files exist
    jsonl_path.touch(exist_ok=True)
    failure_path.touch(exist_ok=True)

    exporter = JSONLExporter(output_file=jsonl_path, failure_file=failure_path)

    # 3. Batch execution with ThreadPoolExecutor & tqdm
    workers = max(1, args.workers)
    invoices: List[Optional[CanonicalInvoice]] = [None] * len(files)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_idx = {
            executor.submit(
                process_invoice_file,
                file_path=f,
                llm_client=llm_client,
                ocr_engine=ocr_engine,
                cache=cache,
                target_month=args.month,
                dry_run=False,
            ): idx
            for idx, f in enumerate(files)
        }

        with tqdm(total=len(files), desc="Processing invoices", unit="file") as pbar:
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                f = files[idx]
                try:
                    inv = future.result()
                except Exception as exc:
                    logger.error("Processing failed for file %s: %s", f.name, type(exc).__name__)
                    inv = CanonicalInvoice(
                        source_file=str(f),
                        source_sha256="",
                        status=InvoiceStatus.FAILED,
                        review_reasons=["worker_error"],
                    )

                invoices[idx] = inv
                exporter.write_invoice(inv)
                if inv.status == InvoiceStatus.FAILED:
                    err_code = inv.review_reasons[0] if inv.review_reasons else "UNKNOWN_ERROR"
                    exporter.write_failure(inv.source_file, err_code)

                pbar.update(1)

    collected_invoices: List[CanonicalInvoice] = [inv for inv in invoices if inv is not None]

    # 4. Deduplication
    deduped_invoices, duplicates = deduplicate_invoices(collected_invoices)

    # If duplicates were detected, sync invoices.jsonl with final status
    if duplicates:
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for inv in deduped_invoices:
                f.write(json.dumps(inv.to_jsonl_dict(), ensure_ascii=False) + "\n")

    # 5. Export Excel 4-sheet summary
    export_excel_summary(
        invoices=deduped_invoices,
        duplicates=duplicates,
        output_dir=out_dir,
        month=args.month,
    )

    # 6. Final statistics & summary table
    duration = time.time() - start_time
    num_verified = sum(1 for inv in deduped_invoices if inv.status == InvoiceStatus.VERIFIED)
    num_review = sum(1 for inv in deduped_invoices if inv.status == InvoiceStatus.REVIEW_NEEDED)
    num_failed = sum(1 for inv in deduped_invoices if inv.status == InvoiceStatus.FAILED)
    num_duplicate = sum(
        1 for inv in deduped_invoices if inv.status == InvoiceStatus.DUPLICATE or inv.is_duplicate
    )

    _print_summary(
        total_files=len(files),
        num_verified=num_verified,
        num_review=num_review,
        num_failed=num_failed,
        num_duplicate=num_duplicate,
        duration=duration,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
