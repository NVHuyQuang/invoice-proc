"""JSONL streaming exporter module.

PLAN 6.1:
- Append + flush per document to prevent losing records on mid-run crash.
- Decimal values serialized as strings to preserve exact financial precision.
- Separate failures log at output/failures.jsonl (file path, error code, no contents).
"""

import io
import json
import os
from pathlib import Path
import tempfile
from typing import Optional, Union, Any, Sequence

from models.schema import CanonicalInvoice


def rewrite_invoices_atomic(output_file: Union[Path, str], invoices: Sequence[Any]) -> None:
    """Rewrite a JSONL file atomically using a temporary file and os.replace.

    Guarantees that no corrupted or partial JSONL file is left on mid-run crash or failure.
    Uses os.fsync to ensure data is committed to disk before atomic rename.

    Args:
        output_file: Destination JSONL file path.
        invoices: Sequence of CanonicalInvoice objects (or dicts).
    """
    target = Path(output_file)
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_fd, temp_file_path = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_file_path)

    try:
        with open(temp_fd, "w", encoding="utf-8") as f:
            for inv in invoices:
                if hasattr(inv, "to_jsonl_dict"):
                    data = inv.to_jsonl_dict()
                elif isinstance(inv, dict):
                    data = inv
                else:
                    data = dict(inv)
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except (OSError, AttributeError, io.UnsupportedOperation):
                pass
        os.replace(temp_path, target)
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise


class JSONLExporter:

    """Streams CanonicalInvoice records to JSONL files with immediate flush."""

    def __init__(self, output_file: Union[Path, str], failure_file: Optional[Union[Path, str]] = None) -> None:
        self.output_file = Path(output_file)
        self.failure_file = Path(failure_file) if failure_file else self.output_file.parent / "failures.jsonl"
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self.failure_file.parent.mkdir(parents=True, exist_ok=True)

    def write_invoice(self, invoice: CanonicalInvoice) -> None:
        """Append an invoice to the JSONL file and flush immediately.

        Args:
            invoice: CanonicalInvoice instance.
        """
        data = invoice.to_jsonl_dict()
        line = json.dumps(data, ensure_ascii=False)
        with open(self.output_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except (OSError, AttributeError, io.UnsupportedOperation):
                pass

    def write_failure(self, file_path: Union[str, Path], error_code: str) -> None:
        """Append a failure record to failures.jsonl.

        Args:
            file_path: Relative or absolute path of failed file.
            error_code: Standardized error code identifier.
        """
        payload = {
            "file_path": str(file_path),
            "error_code": str(error_code),
        }
        line = json.dumps(payload, ensure_ascii=False)
        with open(self.failure_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except (OSError, AttributeError, io.UnsupportedOperation):
                pass

    def close(self) -> None:
        """No-op for stateless file handle management, provided for cleanup protocols."""
        pass

    def __enter__(self) -> "JSONLExporter":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
