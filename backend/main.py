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
from src.services.deidentification_service import (
    DeidentificationService,
    DeidentifyRequest,
)
from src.core.pii_detector import PIIMatch

from backend.schemas import (
    ConversionResultsResponse,
    DependencyStatusResponse,
    DeidentifyDocumentResultResponse,
    DeidentifyRequestBody,
    DeidentifyResultsResponse,
    DetectPIIRequest,
    DetectionResultsResponse,
    DocumentPIIResponse,
    DocumentResultResponse,
    HealthResponse,
    OcrWarning,
    OpenFolderRequest,
    PIIMatchResponse,
    PreviewRequest,
    PreviewResponse,
    ProcessFileRequest,
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
    if expected and request.method != "OPTIONS" and request.url.path.rstrip("/") != "/api/health":
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

# Cooperative cancel flag for the in-flight redaction run. This is a single
# process-global, which is correct only under the app's single-user,
# one-redaction-at-a-time model (the desktop UI awaits /api/redact before it can
# start another). redact_documents() resets it on entry so a stale flag can't
# phantom-cancel the next run. If concurrent redaction runs ever become
# possible, this must become per-run (e.g. keyed by a run id) or a second run
# would share — and wrongly trip — the first run's cancel flag.
_redaction_control = {"cancel_requested": False}


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


@app.post("/api/file/process", response_model=ConversionResultsResponse)
def process_file(req: ProcessFileRequest):
    """Single-document mode: prepare one file instead of scanning a folder."""
    file_path = Path(req.file_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {req.file_path}")

    try:
        service = ConversionService()
        results = service.process_file(file_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File processing failed: {e}") from e

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

@app.post("/api/redact/cancel")
def cancel_redaction():
    """Ask an in-flight /api/redact run to stop after the current document."""
    _redaction_control["cancel_requested"] = True
    return {"status": "cancel_requested"}


def _resolve_cached_selections(documents: List[str], selected_keys: List[str]):
    """
    Rebuild the detected-PII map and per-match selection flags from the
    server-side detection cache.

    Shared by /api/redact and /api/deidentify so both derive selection keys the
    same way. Index order is load-bearing — a manual PII item's key is its
    position in the cached list (see CLAUDE.md rule 31).
    """
    detected_pii: Dict[Path, dict] = {}
    for doc_path_str in documents:
        cached = _detection_cache.get(doc_path_str)
        if not cached:
            raise HTTPException(
                status_code=400,
                detail=f"No cached detection data for {doc_path_str}. Run detection first.",
            )
        detected_pii[Path(doc_path_str)] = cached

    user_selections: Dict[str, bool] = {}
    for doc_path_str in documents:
        doc_path = Path(doc_path_str)
        matches = detected_pii[doc_path].get("matches", [])
        for idx in range(len(matches)):
            # The frontend sends keys as "doc_path_idx"
            user_selections[f"{doc_path}_{idx}"] = f"{doc_path_str}_{idx}" in selected_keys

    return detected_pii, user_selections


@app.post("/api/redact", response_model=RedactionResultsResponse)
def redact_documents(req: RedactRequest):
    _redaction_control["cancel_requested"] = False
    folder_path = Path(req.folder_path)
    documents = [Path(p) for p in req.documents]

    detected_pii, user_selections = _resolve_cached_selections(
        req.documents, req.selected_keys
    )

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
            custom_output_filename=req.custom_output_filename,
            parent_names=req.parent_names,
            family_names=req.family_names,
            organisation_names=req.organisation_names,
            redact_header_footer=req.redact_header_footer,
        )

        results = service.execute(
            request,
            should_cancel=lambda: _redaction_control["cancel_requested"],
        )

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
                    quarantine_path=str(r.quarantine_path) if r.quarantine_path else None,
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
                OcrWarning(filename=f, count=c) for f, c in results.ocr_warnings
            ],
            cancelled=results.cancelled,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redaction failed: {e}") from e


# ── De-identification ────────────────────────────────────────────────────

@app.post("/api/deidentify", response_model=DeidentifyResultsResponse)
def deidentify_documents(req: DeidentifyRequestBody):
    """
    Replace PII with non-identifying labels and write plain-text output.

    A sibling of /api/redact: same cache, same selections, same cooperative
    cancel. Only the output differs.
    """
    _redaction_control["cancel_requested"] = False
    detected_pii, user_selections = _resolve_cached_selections(
        req.documents, req.selected_keys
    )

    try:
        service = DeidentificationService()
        request = DeidentifyRequest(
            folder_path=Path(req.folder_path),
            student_name=req.student_name,
            documents=[Path(p) for p in req.documents],
            detected_pii=detected_pii,
            user_selections=user_selections,
            folder_action=req.folder_action,
            custom_output_path=Path(req.custom_output_path) if req.custom_output_path else None,
            custom_output_filename=req.custom_output_filename,
            parent_names=req.parent_names,
            family_names=req.family_names,
            organisation_names=req.organisation_names,
            redact_header_footer=req.redact_header_footer,
        )

        results = service.execute(
            request,
            should_cancel=lambda: _redaction_control["cancel_requested"],
        )

        return DeidentifyResultsResponse(
            output_folder=str(results.output_folder),
            key_file_path=str(results.key_file_path) if results.key_file_path else None,
            output_folder_holds_originals=results.output_folder_holds_originals,
            document_results=[
                DeidentifyDocumentResultResponse(
                    document_name=r.document_name,
                    output_path=str(r.output_path) if r.output_path else None,
                    success=r.success,
                    items_replaced=r.items_replaced,
                    verification_failures=r.verification_failures,
                    ocr_warnings=r.ocr_warnings,
                    image_warnings=r.image_warnings,
                    error_message=r.error_message,
                    quarantine_path=str(r.quarantine_path) if r.quarantine_path else None,
                )
                for r in results.document_results
            ],
            log_content=results.log_content,
            log_path=str(results.log_path) if results.log_path else None,
            total_documents=results.total_documents,
            successfully_deidentified=results.successfully_deidentified,
            verification_failures=[
                {"filename": f, "message": m} for f, m in results.verification_failures
            ],
            ocr_warnings=[
                OcrWarning(filename=f, count=c) for f, c in results.ocr_warnings
            ],
            cancelled=results.cancelled,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"De-identification failed: {e}") from e


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


@app.post("/api/file/validate")
def validate_file(req: ProcessFileRequest):
    """Check a single document path, and whether it is a type we can handle."""
    file_path = Path(req.file_path)
    exists = file_path.exists()
    is_file = file_path.is_file() if exists else False
    supported = file_path.suffix.lower() in (".pdf", ".doc", ".docx")
    return {
        "exists": exists,
        "is_file": is_file,
        "supported": supported,
        "path": req.file_path,
    }


# ── Cleanup ──────────────────────────────────────────────────────────────

# Only files this app generates may be deleted. Both the list and the delete
# endpoint enforce it independently — the delete endpoint must never trust that
# a path came from the list. The de-identify key file is deliberately absent:
# it never lives in an output folder, and must not be deletable through here.
_CLEANUP_GLOBS = ("*_redacted.pdf", "*.UNVERIFIED.pdf",
                  "*_deidentified.txt", "*.UNVERIFIED.txt")
_CLEANUP_SUFFIXES = ("_redacted.pdf", ".UNVERIFIED.pdf",
                     "_deidentified.txt", ".UNVERIFIED.txt")


@app.post("/api/cleanup/list", response_model=CleanupListResponse)
def cleanup_list(req: CleanupListRequest):
    folder = Path(req.output_path)
    if not folder.exists() or not folder.is_dir():
        return CleanupListResponse(files=[])
    files = [str(p) for pattern in _CLEANUP_GLOBS for p in folder.glob(pattern)]
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
        if path.suffix not in (".pdf", ".txt"):
            failed.append(CleanupFailure(path=p, reason="not a PDF or text file"))
            continue
        if not path.name.endswith(_CLEANUP_SUFFIXES):
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
