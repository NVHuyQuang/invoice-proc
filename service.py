"""FastAPI Microservice for Multimodal Invoice Processing & Financial Validation.

Endpoints:
- GET  /health: Service readiness and model status.
- POST /api/v1/extract: Extract & validate a single invoice document (PDF, PNG, JPG, HEIC, WEBP).
- POST /api/v1/extract-batch: Extract & validate multiple invoice documents concurrently.
- POST /api/v1/export-excel: Process multiple documents and download the 4-sheet Excel summary workbook.
"""

from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from config import DEFAULT_MODEL, DEFAULT_PROXY_URL, SCHEMA_VERSION
from core.dedup import deduplicate_invoices
from core.llm_cache import LLMCache
from core.llm_parser import LLMClient
from core.pipeline import process_invoice_file
from exporters.excel_exporter import export_excel_summary
from models.schema import CanonicalInvoice, InvoiceStatus

logger = logging.getLogger("invoice_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic"})

# Shared client instances across requests
_llm_client: Optional[LLMClient] = None
_llm_cache: Optional[LLMCache] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared components upon server startup."""
    global _llm_client, _llm_cache
    _llm_client = LLMClient()
    _llm_cache = LLMCache(cache_dir="cache")
    logger.info("Invoice Processor Microservice active (Model: %s, Proxy: %s)", _llm_client.model, _llm_client.base_url)
    yield


app = FastAPI(
    title="Invoice Processor Microservice",
    description="Multimodal VLM-powered Invoice Extraction, Math Validation, and Reporting API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_client() -> LLMClient:
    """Return active LLMClient instance."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def get_cache(no_cache: bool = False) -> Optional[LLMCache]:
    """Return LLMCache or None if disabled."""
    global _llm_cache
    if no_cache:
        return None
    if _llm_cache is None:
        _llm_cache = LLMCache(cache_dir="cache")
    return _llm_cache


# ==============================================================================
# Response Schemas
# ==============================================================================

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    schema_version: str = SCHEMA_VERSION
    model: str
    proxy_url: str


class BatchSummaryResponse(BaseModel):
    total_files: int
    verified_count: int
    review_needed_count: int
    failed_count: int
    duplicate_count: int
    execution_time_seconds: float
    invoices: List[Dict[str, Any]]


# ==============================================================================
# Endpoints
# ==============================================================================

@app.get("/", response_class=FileResponse)
@app.get("/app", response_class=FileResponse)
def serve_ui():
    """Serve the Snowmelt Financial Audit Dashboard UI."""
    index_file = Path("static/index.html")
    if not index_file.is_file():
        raise HTTPException(status_code=404, detail="Dashboard UI not found")
    return FileResponse(index_file)


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Health and status check endpoint."""
    client = get_client()
    return HealthResponse(
        status="ok",
        version="1.0.0",
        schema_version=SCHEMA_VERSION,
        model=client.model,
        proxy_url=client.base_url,
    )


@app.get("/api/v1/invoices", response_model=List[Dict[str, Any]])
def get_current_invoices():
    """Retrieve currently processed invoices from the latest batch output."""
    import json
    invoices = []
    default_jsonl = Path("output_aug26/invoices.jsonl")
    if default_jsonl.is_file():
        try:
            with open(default_jsonl, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        invoices.append(json.loads(line))
            return invoices
        except Exception as e:
            logger.warning("Failed to read output_aug26/invoices.jsonl: %s", e)
    return []


@app.get("/api/v1/download-excel")
def download_excel_file(month: str = Query("2026-08", description="Target month")):
    """Download the generated Excel summary workbook."""
    candidates = [
        Path(f"output_aug26/Summary_{month}.xlsx"),
        Path(f"output/Summary_{month}.xlsx"),
    ]
    for p in candidates:
        if p.is_file():
            return FileResponse(
                path=str(p),
                filename=f"Summary_{month}.xlsx",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
    raise HTTPException(status_code=404, detail=f"Summary_{month}.xlsx not found")


@app.post("/api/v1/extract", response_model=Dict[str, Any])
async def extract_invoice(
    file: UploadFile = File(..., description="Invoice file (PDF, PNG, JPG, JPEG, WEBP, HEIC)"),
    target_month: Optional[str] = Form(None, description="Target accounting month (YYYY-MM)"),
    no_cache: bool = Form(False, description="Bypass cache lookup"),
    dry_run: bool = Form(False, description="Run validation check without calling LLM"),
) -> Dict[str, Any]:
    """Extract and validate a single uploaded invoice file."""
    filename = file.filename or "invoice.pdf"
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{suffix}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}",
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_file = Path(tmp_dir) / filename
        with open(temp_file, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)

        client = get_client()
        cache = get_cache(no_cache)

        try:
            invoice = process_invoice_file(
                file_path=temp_file,
                llm_client=client,
                cache=cache,
                target_month=target_month,
                dry_run=dry_run,
                use_vision=True,
            )
        except Exception as exc:
            logger.error("Processing error on file %s: %s", filename, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Extraction failure: {type(exc).__name__}",
            ) from exc

        return invoice.to_jsonl_dict()


@app.post("/api/v1/extract-batch", response_model=BatchSummaryResponse)
async def extract_invoices_batch(
    files: List[UploadFile] = File(..., description="Multiple invoice files"),
    target_month: Optional[str] = Form("2026-08", description="Target accounting month (YYYY-MM)"),
    workers: int = Form(4, ge=1, le=20, description="Parallel worker count"),
    no_cache: bool = Form(False, description="Bypass cache lookup"),
) -> BatchSummaryResponse:
    """Extract and validate multiple uploaded invoice files in parallel."""
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded",
        )

    start_time = time.time()
    client = get_client()
    cache = get_cache(no_cache)

    with tempfile.TemporaryDirectory() as tmp_dir:
        saved_files: List[Path] = []
        for upload in files:
            name = upload.filename or f"invoice_{len(saved_files)}.pdf"
            dest = Path(tmp_dir) / name
            with open(dest, "wb") as f_out:
                shutil.copyfileobj(upload.file, f_out)
            saved_files.append(dest)

        def _process_one(path: Path) -> CanonicalInvoice:
            return process_invoice_file(
                file_path=path,
                llm_client=client,
                cache=cache,
                target_month=target_month,
                dry_run=False,
                use_vision=True,
            )

        with ThreadPoolExecutor(max_workers=min(workers, len(saved_files))) as executor:
            invoices = list(executor.map(_process_one, saved_files))

        # Deduplication
        deduped, _ = deduplicate_invoices(invoices)

        v_count = sum(1 for inv in deduped if inv.status == InvoiceStatus.VERIFIED)
        r_count = sum(1 for inv in deduped if inv.status == InvoiceStatus.REVIEW_NEEDED)
        f_count = sum(1 for inv in deduped if inv.status == InvoiceStatus.FAILED)
        d_count = sum(1 for inv in deduped if inv.status == InvoiceStatus.DUPLICATE or inv.is_duplicate)

        return BatchSummaryResponse(
            total_files=len(deduped),
            verified_count=v_count,
            review_needed_count=r_count,
            failed_count=f_count,
            duplicate_count=d_count,
            execution_time_seconds=round(time.time() - start_time, 2),
            invoices=[inv.to_jsonl_dict() for inv in deduped],
        )


@app.post("/api/v1/export-excel")
async def export_excel_endpoint(
    files: List[UploadFile] = File(..., description="Invoice files to process and export"),
    target_month: str = Form("2026-08", description="Target accounting month (YYYY-MM)"),
    workers: int = Form(4, ge=1, le=20, description="Parallel worker count"),
    no_cache: bool = Form(False, description="Bypass cache lookup"),
):
    """Process multiple invoice files and return a downloadable 4-sheet Excel summary."""
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded",
        )

    client = get_client()
    cache = get_cache(no_cache)

    temp_dir = tempfile.mkdtemp()
    saved_files: List[Path] = []
    for upload in files:
        name = upload.filename or f"invoice_{len(saved_files)}.pdf"
        dest = Path(temp_dir) / name
        with open(dest, "wb") as f_out:
            shutil.copyfileobj(upload.file, f_out)
        saved_files.append(dest)

    def _process_one(path: Path) -> CanonicalInvoice:
        return process_invoice_file(
            file_path=path,
            llm_client=client,
            cache=cache,
            target_month=target_month,
            dry_run=False,
            use_vision=True,
        )

    with ThreadPoolExecutor(max_workers=min(workers, len(saved_files))) as executor:
        invoices = list(executor.map(_process_one, saved_files))

    deduped, duplicate_pairs = deduplicate_invoices(invoices)
    excel_path = export_excel_summary(
        invoices=deduped,
        duplicates=duplicate_pairs,
        output_dir=temp_dir,
        month=target_month,
    )

    if not excel_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate Excel summary",
        )

    return FileResponse(
        path=str(excel_path),
        filename=f"Summary_{target_month}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("service:app", host="0.0.0.0", port=8000, reload=True)
