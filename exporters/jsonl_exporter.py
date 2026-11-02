"""JSONL streaming exporter module.

PLAN 6.1:
- Append + flush per document to prevent losing records on mid-run crash.
- Decimal values serialized as strings to preserve exact financial precision.
- Separate failures log at output/failures.jsonl (file path, error code, no contents).
"""

from pathlib import Path
from typing import Optional
from models.schema import CanonicalInvoice


class JSONLExporter:
    """Streams CanonicalInvoice records to JSONL files with immediate flush."""

    def __init__(self, output_file: Path, failure_file: Optional[Path] = None) -> None:
        self.output_file = Path(output_file)
        self.failure_file = Path(failure_file) if failure_file else self.output_file.parent / "failures.jsonl"
        self.output_file.parent.mkdir(parents=True, exist_ok=True)

    def write_invoice(self, invoice: CanonicalInvoice) -> None:
        """Append an invoice to the JSONL file and flush immediately.

        Args:
            invoice: CanonicalInvoice instance.
        """
        raise NotImplementedError("W1-jsonl implementation pending")

    def write_failure(self, file_path: str, error_code: str) -> None:
        """Append a failure record to failures.jsonl.

        Args:
            file_path: Relative or absolute path of failed file.
            error_code: Standardized error code identifier.
        """
        raise NotImplementedError("W1-jsonl implementation pending")
