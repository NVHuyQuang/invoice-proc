"""Excel 4-sheet report exporter module.

PLAN 6.2:
Generates Summary_<YYYY>-<MM>.xlsx with 4 sheets:
1. Invoice Overview: Date, Bill No, Vendor, Category, Subtotal, Tax, Total, Status, Source File.
2. Line Items Detail: Each line item with invoice_ref link.
3. Discrepancy Alerts: REVIEW_NEEDED / FAILED invoices with detailed reasons, link to file, and audit columns.
4. Duplicates: Suspected duplicate invoice pairs.
All numeric amounts formatted with openpyxl number_format.
Calls excel_safety for formula protection and atomic writes.
"""

from pathlib import Path
from typing import List, Tuple
from models.schema import CanonicalInvoice


def export_excel_summary(
    invoices: List[CanonicalInvoice],
    duplicates: List[Tuple[str, str, str]],
    output_dir: Path,
    month: str
) -> Path:
    """Generate Excel 4-sheet summary workbook.

    Args:
        invoices: List of parsed CanonicalInvoice instances.
        duplicates: List of duplicate pairs detected.
        output_dir: Directory to save workbook.
        month: Target month string 'YYYY-MM'.

    Returns:
        Path to the written .xlsx file.
    """
    raise NotImplementedError("W1-excel-sheets implementation pending")
