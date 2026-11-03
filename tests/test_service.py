"""Tests for FastAPI Invoice Processing Microservice."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch
import openpyxl
import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

from config import DEFAULT_MODEL, DEFAULT_PROXY_URL
from models.schema import (
    DocType,
    InvoiceStatus,
    LineItemKind,
    VLMInvoice,
    VLMLineItem,
    VLMSummary,
)
from service import app


@pytest.fixture
def client() -> TestClient:
    """Create FastAPI TestClient instance."""
    return TestClient(app)


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Generate a clean synthetic PDF invoice in-memory."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    text = (
        "ACME TEST SUPPLIES INC\n"
        "Invoice Number: INV-API-001\n"
        "Invoice Date: 2026-08-15\n"
        "Due Date: 2026-08-30\n"
        "Widget Alpha | 2 | 10.00 | 20.00\n"
        "Subtotal: 20.00\n"
        "Grand Total: 20.00\n"
    )
    page.insert_text((50, 100), text, fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture
def mock_vlm_invoice() -> VLMInvoice:
    """Return a mathematically sound VLMInvoice mock."""
    return VLMInvoice(
        doc_type=DocType.GOODS_INVOICE,
        vendor_name="ACME TEST SUPPLIES INC",
        invoice_no="INV-API-001",
        invoice_date="2026-08-15",
        due_date="2026-08-30",
        currency="USD",
        line_items=[
            VLMLineItem(
                item_name="Widget Alpha",
                qty="2",
                unit_price="10.00",
                line_total="20.00",
                unit="EA",
                kind=LineItemKind.GOODS,
            )
        ],
        summary=VLMSummary(
            subtotal="20.00",
            tax="0.00",
            grand_total="20.00",
            amount_due="20.00",
        ),
    )


# ==============================================================================
# 1. Health Endpoint
# ==============================================================================

def test_health_endpoint(client: TestClient) -> None:
    """Test GET /health returns service status and model metadata."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "1.0.0"
    assert "model" in data
    assert "proxy_url" in data


def test_serve_ui_endpoint(client: TestClient) -> None:
    """Test GET / and GET /app returns HTML dashboard."""
    r1 = client.get("/")
    assert r1.status_code == 200
    assert "Invoice Processor" in r1.text

    r2 = client.get("/app")
    assert r2.status_code == 200
    assert "Invoice Processor" in r2.text


def test_get_invoices_endpoint(client: TestClient) -> None:
    """Test GET /api/v1/invoices returns parsed invoices list."""
    response = client.get("/api/v1/invoices")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_download_excel_endpoint(client: TestClient) -> None:
    """Test GET /api/v1/download-excel returns Excel file if exists."""
    response = client.get("/api/v1/download-excel?month=2026-08")
    assert response.status_code in (200, 404)


# ==============================================================================
# 2. Extract Single Invoice
# ==============================================================================

def test_extract_invoice_unsupported_format(client: TestClient) -> None:
    """Test POST /api/v1/extract rejects unsupported extensions with HTTP 400."""
    files = {"file": ("unsupported.txt", b"dummy content", "text/plain")}
    response = client.post("/api/v1/extract", files=files)
    assert response.status_code == 400
    assert "Unsupported file format" in response.json()["detail"]


def test_extract_invoice_success(
    client: TestClient,
    sample_pdf_bytes: bytes,
    mock_vlm_invoice: VLMInvoice,
) -> None:
    """Test POST /api/v1/extract successfully processes a PDF invoice."""
    mock_llm_client = MagicMock()
    mock_llm_client.model = DEFAULT_MODEL
    mock_llm_client.base_url = DEFAULT_PROXY_URL
    mock_llm_client.parse_invoice_vision.return_value = mock_vlm_invoice

    with patch("service.get_client", return_value=mock_llm_client):
        files = {"file": ("test_inv.pdf", sample_pdf_bytes, "application/pdf")}
        data = {"target_month": "2026-08", "no_cache": "true"}
        response = client.post("/api/v1/extract", files=files, data=data)

    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "VERIFIED"
    assert res["vendor_name"] == "ACME TEST SUPPLIES INC"
    assert res["invoice_no"] == "INV-API-001"
    assert res["grand_total"] == "20.00"
    assert len(res["line_items"]) == 1


def test_extract_invoice_dry_run(
    client: TestClient,
    sample_pdf_bytes: bytes,
) -> None:
    """Test POST /api/v1/extract with dry_run=True halts before calling LLM."""
    mock_llm_client = MagicMock()
    with patch("service.get_client", return_value=mock_llm_client):
        files = {"file": ("dry_run.pdf", sample_pdf_bytes, "application/pdf")}
        data = {"dry_run": "true"}
        response = client.post("/api/v1/extract", files=files, data=data)

    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "REVIEW_NEEDED"
    assert "dry_run" in res["review_reasons"]
    mock_llm_client.parse_invoice_vision.assert_not_called()


# ==============================================================================
# 3. Extract Batch
# ==============================================================================

def test_extract_batch_success(
    client: TestClient,
    sample_pdf_bytes: bytes,
    mock_vlm_invoice: VLMInvoice,
) -> None:
    """Test POST /api/v1/extract-batch processes multiple files concurrently."""
    mock_llm_client = MagicMock()
    mock_llm_client.model = DEFAULT_MODEL
    mock_llm_client.base_url = DEFAULT_PROXY_URL
    mock_llm_client.parse_invoice_vision.return_value = mock_vlm_invoice

    with patch("service.get_client", return_value=mock_llm_client):
        files = [
            ("files", ("inv1.pdf", sample_pdf_bytes, "application/pdf")),
            ("files", ("inv2.pdf", sample_pdf_bytes, "application/pdf")),
        ]
        data = {"target_month": "2026-08", "workers": "2", "no_cache": "true"}
        response = client.post("/api/v1/extract-batch", files=files, data=data)

    assert response.status_code == 200
    res = response.json()
    assert res["total_files"] == 2
    assert len(res["invoices"]) == 2
    assert res["duplicate_count"] >= 1  # exact duplicate sha256


# ==============================================================================
# 4. Export Excel Summary
# ==============================================================================

def test_export_excel_endpoint(
    client: TestClient,
    sample_pdf_bytes: bytes,
    mock_vlm_invoice: VLMInvoice,
) -> None:
    """Test POST /api/v1/export-excel returns valid 4-sheet Excel summary workbook."""
    mock_llm_client = MagicMock()
    mock_llm_client.model = DEFAULT_MODEL
    mock_llm_client.base_url = DEFAULT_PROXY_URL
    mock_llm_client.parse_invoice_vision.return_value = mock_vlm_invoice

    with patch("service.get_client", return_value=mock_llm_client):
        files = [
            ("files", ("inv1.pdf", sample_pdf_bytes, "application/pdf")),
        ]
        data = {"target_month": "2026-08", "workers": "1", "no_cache": "true"}
        response = client.post("/api/v1/export-excel", files=files, data=data)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    # Verify openpyxl can parse the returned bytes
    wb = openpyxl.load_workbook(io.BytesIO(response.content))
    assert len(wb.sheetnames) == 4
    assert wb.sheetnames[0] == "Invoice Overview"
    wb.close()
