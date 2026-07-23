"""
FastAPI Backend — HTTP API wrapping the service layer.
Run with: uvicorn backend.main:app --port 8765 --reload
"""

import base64
import os
import platform
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

# Core modules use bare imports (e.g., "from pii_detector import ...").
# Add src/core to sys.path so they resolve correctly.
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src" / "core"))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from src.services.conversion_service import ConversionService
from src.services.detection_service import DetectionService
from src.services.redaction_service import RedactionService, RedactionRequest
from src.core.pii_detector import PIIMatch

from backend.schemas import (
    ConversionResultsResponse,
    DependencyStatusResponse,
    DetectPIIRequest,
    DetectionResultsResponse,
    DocumentPIIResponse,
    DocumentResultResponse,
    HealthResponse,
    OpenFolderRequest,
    PIIMatchResponse,
    PreviewRequest,
    PreviewResponse,
    ProcessFolderRequest,
    RedactRequest,
    RedactionResultsResponse,
    CleanupListRequest,
    CleanupListResponse,
    CleanupRequest,
    CleanupResponse,
    CleanupFailure,
    AddManualPIIRequest,
    AddManualPIIResponse,
)

app = FastAPI(title="Redaction Tool API", version="2.0.0")

# ── API token auth ────────────────────────────────────────────────────────
# The Electron shell generates a random per-session token, passes it to this
# process via REDACTION_API_TOKEN, and the renderer sends it on every request.
# Requests without the token are rejected, so a webpage open in the user's
# browser cannot drive this API. When the env var is unset (manual `uvicorn`
# runs, pytest), auth is disabled.
#
# Registered BEFORE CORSMiddleware on purpose: Starlette's add_middleware
# inserts at index 0, so the LAST registration is outermost. Defining this
# first leaves CORS outermost, which is what lets a 401 carry the
# Access-Control-Allow-Origin header the dev renderer needs to read it.
@app.middleware("http")
async def require_api_token(request: Request, call_next):
    expected = os.environ.get("REDACTION_API_TOKEN", "")
    if expected and request.method != "OPTIONS" and request.url.path != "/api/health":
        provided = request.headers.get("x-api-token", "")
        # Compare as bytes: compare_digest raises TypeError on non-ASCII str,
        # which would turn a bad header into a 500 + traceback.
        if not secrets.compare_digest(
            provided.encode("utf-8", "ignore"), expected.encode("utf-8")
        ):
            return JSONResponse(status_code=401,
                                content={"detail": "Invalid or missing API token"})
    return await call_next(request)


# Allow the Electron/Vite frontend to connect. Origins are pinned to the Vite
# dev server only. The packaged app loads via file:// and sends NO Origin
# header, triggers no preflight, and works with no CORS headers at all — so it
# needs no entry here. "null" is deliberately NOT allowed: that is the origin
# sandboxed iframes and data:/blob: documents send. The real access control is
# the API token above; CORS only stops browser pages reading responses.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory cache for detection results ─────────────────────────────────
# The detection step produces PIIMatch objects with bboxes etc. that the
# redaction step needs. We store them server-side keyed by doc path so the
# frontend only needs to send back selection keys.
_detection_cache: Dict[str, Dict] = {}


# ── Health ────────────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(status="ok", version="2.0.0")


# ── Dependencies ──────────────────────────────────────────────────────────

@app.get("/api/dependencies/check", response_model=DependencyStatusResponse)
def check_dependencies():
    service = ConversionService()
    deps = service.check_dependencies()

    # Check NER availability
    ner_ok = False
    ner_message = "Not available"
    try:
        from src.core.pii_orchestrator import PIIOrchestrator
        test_orch = PIIOrchestrator("test", require_ner=True)
        if test_orch.presidio_analyzer is not None:
            ner_ok = True
            ner_message = "spaCy + Presidio loaded"
    except Exception as e:
        ner_message = str(e)

    return DependencyStatusResponse(
        libreoffice_ok=deps.libreoffice_ok,
        libreoffice_message=deps.libreoffice_message,
        tesseract_ok=deps.tesseract_ok,
        can_convert_word=deps.can_convert_word,
        ner_ok=ner_ok,
        ner_message=ner_message,
    )


# ── Folder Processing ────────────────────────────────────────────────────

@app.post("/api/folder/process", response_model=ConversionResultsResponse)
def process_folder(req: ProcessFolderRequest):
    folder = Path(req.folder_path)
    if not folder.exists():
        raise HTTPException(status_code=400, detail=f"Folder not found: {req.folder_path}")

    try:
        service = ConversionService()
        results = service.process_folder(folder)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Folder processing failed: {e}") from e

    return ConversionResultsResponse(
        pdf_files=[str(p) for p in results.pdf_files],
        converted_files=[str(p) for p in results.converted_files],
        failed_conversions=[
            {"path": str(p), "reason": r} for p, r in results.failed_conversions
        ],
        password_protected=[str(p) for p in results.password_protected],
        total_files=results.total_files,
        processable_count=results.processable_count,
        flagged_count=results.flagged_count,
    )


# ── PII Detection ────────────────────────────────────────────────────────

@app.post("/api/pii/detect", response_model=DetectionResultsResponse)
def detect_pii(req: DetectPIIRequest):
    pdf_paths = [Path(p) for p in req.pdf_paths]

    for p in pdf_paths:
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"File not found: {p}")

    try:
        service = DetectionService(
            student_name=req.student_name,
            parent_names=req.parent_names,
            family_names=req.family_names,
            organisation_names=req.organisation_names,
            require_ner=True,
        )

        results = service.detect_all(pdf_paths)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Detection failed: {e}") from e

    # Build response and cache results for redaction step
    doc_responses = []
    _detection_cache.clear()

    for doc_path, doc_pii in results.pii_by_document.items():
        doc_key = str(doc_path)
        ocr_pages = doc_pii.text_data.get("ocr_pages", [])

        match_responses = []
        match_dicts = []

        for match in doc_pii.matches:
            match_responses.append(PIIMatchResponse(
                text=match.text,
                category=match.category,
                confidence=match.confidence,
                confidence_label=match.confidence_label,
                page_num=match.page_num,
                line_num=match.line_num,
                context=match.context,
                source=match.source,
                bbox=list(match.bbox) if match.bbox else None,
            ))
            # Store the raw match data for the redaction step
            match_dicts.append({
                "text": match.text,
                "category": match.category,
                "confidence": match.confidence,
                "page_num": match.page_num,
                "line_num": match.line_num,
                "context": match.context,
                "source": match.source,
                "bbox": list(match.bbox) if match.bbox else None,
            })

        _detection_cache[doc_key] = {
            "matches": doc_pii.matches,  # Keep original PIIMatch objects
            "text_data": doc_pii.text_data,
        }

        doc_responses.append(DocumentPIIResponse(
            path=doc_key,
            filename=doc_path.name,
            matches=match_responses,
            ocr_pages=ocr_pages,
        ))

    return DetectionResultsResponse(
        documents=doc_responses,
        total_matches=results.total_matches,
    )


@app.post("/api/pii/manual", response_model=AddManualPIIResponse)
def add_manual_pii(req: AddManualPIIRequest):
    """
    Append a user-identified PII item the detection engines missed.

    Stored in the same server-side cache /api/redact reads from, so once
    the frontend marks it selected it is redacted exactly like any other
    detected match — no changes needed to the redact endpoint itself.
    """
    import fitz

    cached = _detection_cache.get(req.doc_path)
    if not cached:
        raise HTTPException(
            status_code=400,
            detail=f"No cached detection data for {req.doc_path}. Run detection first.",
        )

    text = req.text.strip()
    if len(text) < 3:
        raise HTTPException(status_code=400, detail="Manual PII text must be at least 3 characters.")

    doc_path = Path(req.doc_path)
    if not doc_path.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {doc_path}")

    try:
        pdf = fitz.open(str(doc_path))
        total_pages = len(pdf)
        pdf.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot open PDF: {e}")

    if req.page_num < 1 or req.page_num > total_pages:
        raise HTTPException(
            status_code=400,
            detail=f"Page {req.page_num} does not exist in this document (it has {total_pages} pages).",
        )

    match = PIIMatch(
        text=text,
        category=req.category,
        confidence=1.0,
        page_num=req.page_num,
        line_num=0,
        context=text,
        source="manual",
        bbox=None,
    )
    cached["matches"].append(match)
    index = len(cached["matches"]) - 1

    return AddManualPIIResponse(
        match=PIIMatchResponse(
            text=match.text,
            category=match.category,
            confidence=match.confidence,
            confidence_label=match.confidence_label,
            page_num=match.page_num,
            line_num=match.line_num,
            context=match.context,
            source=match.source,
            bbox=None,
        ),
        index=index,
    )


# ── Redaction ─────────────────────────────────────────────────────────────

@app.post("/api/redact", response_model=RedactionResultsResponse)
def redact_documents(req: RedactRequest):
    folder_path = Path(req.folder_path)
    documents = [Path(p) for p in req.documents]

    # Rebuild detected_pii dict from cache
    detected_pii: Dict[Path, dict] = {}
    for doc_path_str in req.documents:
        cached = _detection_cache.get(doc_path_str)
        if cached:
            detected_pii[Path(doc_path_str)] = cached
        else:
            raise HTTPException(
                status_code=400,
                detail=f"No cached detection data for {doc_path_str}. Run detection first.",
            )

    # Build user_selections: mark each frontend-sent selected key as True.
    user_selections: Dict[str, bool] = {}
    for doc_path_str in req.documents:
        doc_path = Path(doc_path_str)
        matches = detected_pii[doc_path].get("matches", [])
        for idx in range(len(matches)):
            key = f"{doc_path}_{idx}"
            # The frontend sends keys as "doc_path_idx"
            frontend_key = f"{doc_path_str}_{idx}"
            user_selections[key] = frontend_key in req.selected_keys

    try:
        service = RedactionService()
        request = RedactionRequest(
            folder_path=folder_path,
            student_name=req.student_name,
            documents=documents,
            detected_pii=detected_pii,
            user_selections=user_selections,
            folder_action=req.folder_action,
            custom_output_path=Path(req.custom_output_path) if req.custom_output_path else None,
            parent_names=req.parent_names,
            family_names=req.family_names,
            organisation_names=req.organisation_names,
            redact_header_footer=req.redact_header_footer,
        )

        results = service.execute(request)

        return RedactionResultsResponse(
            redacted_folder=str(results.redacted_folder),
            document_results=[
                DocumentResultResponse(
                    document_name=r.document_name,
                    output_path=str(r.output_path) if r.output_path else None,
                    success=r.success,
                    items_redacted=r.items_redacted,
                    verification_failures=r.verification_failures,
                    ocr_warnings=r.ocr_warnings,
                    error_message=r.error_message,
                )
                for r in results.document_results
            ],
            log_content=results.log_content,
            log_path=str(results.log_path) if results.log_path else None,
            total_documents=results.total_documents,
            successfully_redacted=results.successfully_redacted,
            verification_failures=[
                {"filename": f, "message": m} for f, m in results.verification_failures
            ],
            ocr_warnings=[
                {"filename": f, "count": c} for f, c in results.ocr_warnings
            ],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redaction failed: {e}") from e


# ── Preview ──────────────────────────────────────────────────────────────

@app.post("/api/preview", response_model=PreviewResponse)
def preview_page(req: PreviewRequest):
    """Render a single PDF page at 150 DPI and return as base64 PNG."""
    import fitz

    pdf_path = Path(req.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {req.pdf_path}")

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot open PDF: {e}")

    try:
        if req.page_num < 0 or req.page_num >= len(doc):
            raise HTTPException(
                status_code=400,
                detail=f"Page {req.page_num} out of range (0-{len(doc) - 1})",
            )

        page = doc[req.page_num]
        # 150 DPI: multiply by 150/72
        mat = fitz.Matrix(150 / 72, 150 / 72)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        total = len(doc)

        return PreviewResponse(
            image_base64=base64.b64encode(img_bytes).decode("ascii"),
            total_pages=total,
            page_num=req.page_num,
        )
    finally:
        doc.close()


# ── Utility ───────────────────────────────────────────────────────────────

@app.post("/api/folder/open")
def open_folder(req: OpenFolderRequest):
    folder = Path(req.folder_path)
    if not folder.exists():
        raise HTTPException(status_code=400, detail=f"Folder not found: {req.folder_path}")

    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", str(folder)])
    elif system == "Windows":
        subprocess.Popen(["explorer", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])

    return {"status": "opened"}


@app.post("/api/folder/validate")
def validate_folder(req: ProcessFolderRequest):
    folder = Path(req.folder_path)
    exists = folder.exists()
    is_dir = folder.is_dir() if exists else False
    return {"exists": exists, "is_directory": is_dir, "path": req.folder_path}


# ── Cleanup ──────────────────────────────────────────────────────────────

@app.post("/api/cleanup/list", response_model=CleanupListResponse)
def cleanup_list(req: CleanupListRequest):
    folder = Path(req.output_path)
    if not folder.exists() or not folder.is_dir():
        return CleanupListResponse(files=[])
    files = [str(p) for p in folder.glob("*_redacted.pdf")]
    files += [str(p) for p in folder.glob("*.UNVERIFIED.pdf")]
    return CleanupListResponse(files=sorted(files))


@app.post("/api/cleanup", response_model=CleanupResponse)
def cleanup(req: CleanupRequest):
    folder = Path(req.output_folder).resolve()
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Folder not found: {req.output_folder}")

    deleted: list[str] = []
    failed: list[CleanupFailure] = []

    for p in req.file_paths:
        path = Path(p).resolve()
        if not path.is_relative_to(folder):
            failed.append(CleanupFailure(path=p, reason="outside output folder"))
            continue
        if path.suffix != ".pdf":
            failed.append(CleanupFailure(path=p, reason="not a PDF"))
            continue
        if not (path.name.endswith("_redacted.pdf") or path.name.endswith(".UNVERIFIED.pdf")):
            failed.append(CleanupFailure(path=p, reason="not a redaction output file"))
            continue
        if not path.exists():
            continue  # Already gone — treat as no-op success
        try:
            path.unlink()
            deleted.append(str(path))
        except OSError as e:
            failed.append(CleanupFailure(path=p, reason=str(e)))

    return CleanupResponse(deleted=deleted, failed=failed)
