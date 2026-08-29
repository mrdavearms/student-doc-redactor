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
import threading
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
from src.core.pseudonym_map import ASSIGNABLE_ROLES, ROLE_LABELS
from src.core.pii_detector import PIIMatch
from src.services.text_cleanup_service import BLOCK, blackout, deidentify_paste
from src.core.text_deidentifier import strip_labels
from src.core.pii_orchestrator import find_person_entities
from src.core.text_pdf import render as render_text_pdf

from backend.schemas import (
    ConversionResultsResponse,
    DependencyStatusResponse,
    DeidentifyDocumentResultResponse,
    DeidentifyRequestBody,
    DeidentifyResultsResponse,
    LabelPreviewResponse,
    PeopleResponse,
    PersonInfoResponse,
    CleanTextRequest,
    CleanTextResponse,
    SaveTextRequest,
    SaveTextResponse,
    KeyEntry,
    DetectPIIRequest,
    DetectTextRequest,
    DetectionResultsResponse,
    DocumentPIIResponse,
    DocumentResultResponse,
    HealthResponse,
    OcrWarning,
    OpenFolderRequest,
    PIIMatchResponse,
    PreviewRequest,
    PreviewResponse,
    ReadOutputRequest,
    ReadOutputResponse,
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

# Both detect endpoints (documents and pasted text) are synchronous `def`
# handlers, so Starlette runs each on a threadpool — and a client disconnect
# (the user pressing Back mid-scan) does NOT cancel the in-flight work. Two
# scans can therefore genuinely overlap: whichever finishes last used to win
# the cache outright, regardless of which one the user is actually looking
# at. If an older, slower scan then overwrote a newer one the user had
# already started reviewing, "Clean" would act on text/documents the user
# never saw or approved — the worst class of bug in a privacy tool.
#
# The fix is a generation counter: only the newest detection to have STARTED
# may publish. _begin_detection() is called right before the slow detection
# work starts and claims the next generation number; _publish_detection() is
# called once that work finishes, and only commits the results if no newer
# detection has started in the meantime. The lock is held only for these two
# O(1) operations — never across the detection work itself, or the app would
# become single-threaded for the slowest part of the whole pipeline.
_detection_lock = threading.Lock()
_detection_generation = 0


def _begin_detection() -> int:
    """Claim the next detection generation. Call this immediately before the
    slow detection work starts, after input validation."""
    global _detection_generation
    with _detection_lock:
        _detection_generation += 1
        return _detection_generation


def _publish_detection(generation: int, entries: Dict[str, Dict]) -> bool:
    """
    Commit `entries` to the shared cache if `generation` is still the newest
    one to have started detection. Returns False (and leaves the cache
    untouched) if a newer detection has started since — the caller's results
    are stale and must not be published.
    """
    global _detection_generation
    with _detection_lock:
        if generation != _detection_generation:
            return False
        _detection_cache.clear()
        _detection_cache.update(entries)
        return True

# Reserved detection-cache key for the paste pathway. Chosen because "<" and ">"
# are invalid in Windows filenames and this is not an absolute POSIX path, so it
# can never collide with a real document — and because fitz.open() on it raises,
# so anything that mistakes it for a document degrades safely.
PASTE_KEY = "<pasted-text>"

# Detection cost depends heavily on how many names appear, not just length —
# pii_orchestrator.py runs the whole slab as a single "page" (the document
# pathway calls it once per ~3K-char page instead). Measured after the
# newline-offset/bisect fix for the O(occurrences x text length) line-number
# hot spot: ~50K chars of ordinary prose ~7-8s; a behaviour log naming the
# student on every line, ~35K chars, ~8s. Text that repeats the same one or
# two names very heavily (the same sentence copy-pasted hundreds of times)
# can still take over a minute — that residual cost is a second, separate
# hot spot (re-searching the whole text for every NER-discovered occurrence)
# that this fix does not touch. Past PASTE_MAX_CHARS a paste is document-
# sized, and the document pathway handles it better.
PASTE_MAX_CHARS = 50_000

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
def health_check(request: Request):
    """
    Liveness, plus whether the caller is talking to the process it spawned.

    Deliberately still UNAUTHENTICATED (the one endpoint the token middleware
    skips) so the renderer's backend-down poller keeps working — a mismatched
    or absent token is reported in the body, never as a 401.

    `instance_match` exists because a healthy port does not mean the backend is
    ours: an orphan left by a force-quit, or a second copy of the app, answers
    here first while our own uvicorn is still loading spaCy and has not yet
    failed to bind. See CLAUDE.md rule 55.
    """
    expected = os.environ.get("REDACTION_API_TOKEN", "")
    if not expected:
        # No identity configured (manual uvicorn, pytest) — nothing to check.
        match = True
    else:
        provided = request.headers.get("x-api-token", "")
        match = secrets.compare_digest(
            provided.encode("utf-8", "ignore"), expected.encode("utf-8")
        )
    return HealthResponse(status="ok", version="2.0.0", instance_match=match)


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

    if PASTE_KEY in req.pdf_paths:
        raise HTTPException(status_code=400, detail="Invalid document path.")

    for p in pdf_paths:
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"File not found: {p}")

    generation = _begin_detection()

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

    # Build response and cache entries locally — nothing is written to the
    # shared cache until we know this is still the newest detection to have
    # started (see _begin_detection/_publish_detection).
    doc_responses = []
    cache_entries: Dict[str, Dict] = {}

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

        cache_entries[doc_key] = {
            "matches": doc_pii.matches,  # Keep original PIIMatch objects
            "text_data": doc_pii.text_data,
        }

        doc_responses.append(DocumentPIIResponse(
            path=doc_key,
            filename=doc_path.name,
            matches=match_responses,
            ocr_pages=ocr_pages,
        ))

    if not _publish_detection(generation, cache_entries):
        # A newer detection has already started (and likely finished) since
        # this one began — e.g. the user pressed Back and re-scanned while
        # this request was still running. This request's results are NOT in
        # the shared cache, so returning them as 200 would let the caller
        # review or clean a document nobody else is looking at. In practice
        # the caller is a fetch the renderer already abandoned (AbortError),
        # so nobody sees this response.
        raise HTTPException(
            status_code=409,
            detail="A newer scan has already started. These results are out of date.",
        )

    return DetectionResultsResponse(
        documents=doc_responses,
        total_matches=results.total_matches,
    )


@app.post("/api/text/detect", response_model=DetectionResultsResponse)
def detect_text(req: DetectTextRequest):
    """
    Detection over pasted text, cached under PASTE_KEY.

    ocr_pages stays EMPTY deliberately: marking the page OCR-sourced would arm
    the fuzzy verification pass (CLAUDE.md rule 45), which is right for scans
    and wrong for typed text, where a classmate "Smyth" against student "Smith"
    is edit-distance 1 and would falsely quarantine correct output.
    """
    text = req.text or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="No text was provided.")
    if len(text) > PASTE_MAX_CHARS:
        raise HTTPException(
            status_code=400,
            detail=(f"That text is {len(text):,} characters, over the "
                    f"{PASTE_MAX_CHARS:,} limit. Save it as a document and use "
                    "the document pathway instead."),
        )
    # A lone UTF-16 surrogate is valid JSON (JS strings permit it) but not
    # valid Unicode text — it can arrive from corrupted clipboard data. Left
    # unchecked it reaches spaCy/Presidio's NER analysis, which needs to
    # encode the text and raises deep inside with an internal exception
    # string. Reject up front with a message a teacher can act on, rather
    # than sanitising it ourselves: this is a privacy tool, and silently
    # rewriting the pasted text (even just to drop or replace one character)
    # risks altering something the user needs redacted exactly as they pasted
    # it. The document pathway can never hit this — PDF text extraction never
    # hands back unpaired surrogates.
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise HTTPException(
            status_code=400,
            detail=(
                "That text has a character that can't be read properly — this "
                "can happen with text copied from certain sources. Try copying "
                "it again, or paste a different section."
            ),
        )

    generation = _begin_detection()

    try:
        service = DetectionService(
            student_name=req.student_name,
            parent_names=req.parent_names,
            family_names=req.family_names,
            organisation_names=req.organisation_names,
            require_ner=True,
        )
        matches = service.detect_in_text(text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Detection failed: {e}") from e

    cache_entries = {
        PASTE_KEY: {
            "matches": matches,
            "text_data": {"pages": {1: {"text": text}}, "ocr_pages": []},
        }
    }

    if not _publish_detection(generation, cache_entries):
        # See the matching comment in detect_pii — a newer detection (paste
        # or document) has already started, so these results must not
        # overwrite it.
        raise HTTPException(
            status_code=409,
            detail="A newer scan has already started. These results are out of date.",
        )

    return DetectionResultsResponse(
        documents=[DocumentPIIResponse(
            path=PASTE_KEY,
            filename="Pasted text",
            matches=[PIIMatchResponse(
                text=m.text, category=m.category, confidence=m.confidence,
                confidence_label=m.confidence_label, page_num=m.page_num,
                line_num=m.line_num, context=m.context, source=m.source,
                bbox=list(m.bbox) if m.bbox else None,
            ) for m in matches],
            ocr_pages=[],
        )],
        total_matches=len(matches),
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

    if req.doc_path == PASTE_KEY:
        # No file on disk for pasted text — it lives entirely in the cache
        # under a single synthetic page (see detect_text). The exists()/page-
        # count probes below are meaningless for it and must not run.
        page_num = 1
    else:
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
        page_num = req.page_num

    match = PIIMatch(
        text=text,
        category=req.category,
        confidence=1.0,
        page_num=page_num,
        line_num=0,
        context=text,
        source="manual",
        bbox=None,
    )
    with _detection_lock:
        # Re-fetch under the lock rather than reusing the `cached` object
        # from above: a detection publish could have replaced the cache
        # entry (with a fresh dict) while we were validating the page
        # number, and appending to the stale object would silently vanish.
        cached = _detection_cache.get(req.doc_path)
        if not cached:
            raise HTTPException(
                status_code=400,
                detail=f"No cached detection data for {req.doc_path}. Run detection first.",
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


@app.post("/api/detection/discard")
def discard_detection():
    """
    Forget the last run: the extracted document text and everything detected
    in it.

    The cache exists to bridge detect -> redact (rule 25) and is otherwise
    resident for the life of the backend process. The paste pathway could
    already say "I'm finished" via /api/text/discard, but the document pathway
    could not — so the last student's document text stayed in memory until the
    next run replaced it, or the app closed.

    Called by the store's reset(), which is the app's only "start over" and is
    reached from both completion screens, the no-PII screen, and the error
    boundary. Safe there because reset() also blanks detectionParamsKey, so the
    next run re-detects rather than skipping on a stale fingerprint (rule 41).

    Claims a generation first for the same reason /api/text/discard does: a
    scan the renderer abandoned is still running, and would otherwise publish
    itself back into the cache after the clear.
    """
    _begin_detection()
    discarded = len(_detection_cache)
    _detection_cache.clear()
    return {"discarded": discarded}


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

    Deliberately does NOT refuse PASTE_KEY here: /api/deidentify/people and
    /api/deidentify/labels also call through this (via
    _deidentify_request_from), and the paste pathway's own /api/text/people
    and /api/text/labels legitimately route through those two with
    documents=[PASTE_KEY] (see _paste_deidentify_body). The reserved-key guard
    instead sits in /api/redact and /api/deidentify themselves, the two
    endpoints that write to disk and have no legitimate paste caller.
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
    if PASTE_KEY in req.documents:
        raise HTTPException(status_code=400, detail="Invalid document path.")

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

def _deidentify_request_from(req: DeidentifyRequestBody) -> DeidentifyRequest:
    """One place that maps the API body onto the service request, so the
    people/labels endpoints build exactly the map execute() will."""
    detected_pii, user_selections = _resolve_cached_selections(
        req.documents, req.selected_keys
    )
    return DeidentifyRequest(
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
        person_roles=req.person_roles,
        person_custom_labels=req.person_custom_labels,
        ignored_people=req.ignored_people,
    )


@app.post("/api/deidentify/people", response_model=PeopleResponse)
def deidentify_people(req: DeidentifyRequestBody):
    """Everyone the run will label, with a proposed role and its evidence."""
    request = _deidentify_request_from(req)
    try:
        people = DeidentificationService.describe_people(request)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reading people failed: {e}") from e

    return PeopleResponse(
        people=[PersonInfoResponse(**p) for p in people],
        roles=[{"key": k, "label": ROLE_LABELS[k]} for k in ASSIGNABLE_ROLES],
    )


@app.post("/api/deidentify/labels", response_model=LabelPreviewResponse)
def deidentify_label_preview(req: DeidentifyRequestBody):
    """Labels for a proposed assignment, so the screen never reimplements the
    numbering rules in TypeScript."""
    request = _deidentify_request_from(req)
    try:
        return LabelPreviewResponse(labels=DeidentificationService.preview_labels(request))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Label preview failed: {e}") from e


def _paste_deidentify_body(req: CleanTextRequest) -> DeidentifyRequestBody:
    """
    The paste request as a document-shaped one.

    folder_path is PASTE_KEY and is never read: build_map() does not touch it,
    and nothing in the paste pathway writes to disk. Building it here rather
    than in the renderer keeps the frontend from inventing paths.
    """
    return DeidentifyRequestBody(
        folder_path=PASTE_KEY,
        student_name=req.student_name,
        documents=[PASTE_KEY],
        selected_keys=req.selected_keys,
        parent_names=req.parent_names,
        family_names=req.family_names,
        organisation_names=req.organisation_names,
        person_roles=req.person_roles,
        person_custom_labels=req.person_custom_labels,
        ignored_people=req.ignored_people,
    )


@app.post("/api/text/people", response_model=PeopleResponse)
def text_people(req: CleanTextRequest):
    """Who's who, for pasted text. Same map the clean step will build."""
    return deidentify_people(_paste_deidentify_body(req))


@app.post("/api/text/labels", response_model=LabelPreviewResponse)
def text_labels(req: CleanTextRequest):
    """Label preview for pasted text."""
    return deidentify_label_preview(_paste_deidentify_body(req))


@app.post("/api/text/clean", response_model=CleanTextResponse)
def clean_text(req: CleanTextRequest):
    """
    Blackout or de-identify the cached pasted text.

    key_entries and leftover_name_warnings carry REAL NAMES. They are response
    only — shown in the local UI, never written to disk and never logged
    (CLAUDE.md rules 43 and 54c).
    """
    cached = _detection_cache.get(PASTE_KEY)
    if not cached:
        raise HTTPException(
            status_code=400,
            detail="No cached detection data for the pasted text. Run detection first.",
        )

    text = cached["text_data"]["pages"][1]["text"]
    matches = cached["matches"]
    chosen = set(req.selected_keys)
    selected = [m for i, m in enumerate(matches) if f"{PASTE_KEY}_{i}" in chosen]

    try:
        if req.mode == "deidentify":
            request = _deidentify_request_from(_paste_deidentify_body(req))
            pmap, _ = DeidentificationService.build_map(request)
            cleaned, count, leftovers = deidentify_paste(text, selected, pmap)
            # Same convention as deidentification_service.py:662 — the
            # strip-list before the NER sweep is every label the map can
            # emit, not just the ones used for people. A narrower list would
            # leave category/fallback labels (e.g. "[Phone number]",
            # "[Other person]") unstripped, and the sweep below would then
            # misread an inserted label as a surviving name.
            labels = list(pmap.all_labels())
            key_entries = [KeyEntry(label=l, real_name=n) for l, n in pmap.key_entries()]
            notes = pmap.ambiguity_notes()
        else:
            cleaned, count, leftovers = blackout(text, selected)
            labels = [BLOCK]
            key_entries, notes = [], []
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleaning text failed: {e}") from e

    # The net under everything (rule 54c): sweep the OUTPUT for anything NER
    # still reads as a person. Warnings, never quarantine — NER false positives
    # would block correct output. Deliberately deselected strings are excluded
    # because the user's choice stands.
    deselected = {
        (m.text or "").strip().lower()
        for i, m in enumerate(matches) if f"{PASTE_KEY}_{i}" not in chosen
    }
    warnings = []
    for name in find_person_entities(strip_labels(cleaned, labels)):
        if name.lower() in deselected:
            continue
        warnings.append(name)
        if len(warnings) >= 10:
            break

    return CleanTextResponse(
        text=cleaned,
        replacements=count,
        leftovers=leftovers,
        key_entries=key_entries,
        ambiguity_notes=notes,
        leftover_name_warnings=warnings,
    )


@app.post("/api/text/discard")
def discard_text():
    """
    Drop the pasted text from the cache when the user leaves the flow.

    Claims a generation first. Detect endpoints are synchronous, so a scan the
    renderer abandoned keeps running and would otherwise publish the very slab
    the user just asked to discard back into the cache — leaving it resident
    with nothing on screen to explain why. Superseding it makes the discard
    stick. The pop itself needs no lock: it is one atomic dict operation.
    """
    _begin_detection()
    return {"discarded": _detection_cache.pop(PASTE_KEY, None) is not None}


@app.post("/api/text/save", response_model=SaveTextResponse)
def save_text(req: SaveTextRequest):
    """The only thing in the paste pathway that touches disk, and only on a
    path the user picked in a native Save dialog."""
    if req.kind not in ("pdf", "txt"):
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    out = Path(req.path)
    unsupported: list = []
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        if req.kind == "txt":
            out.write_text(req.text, encoding="utf-8")
        else:
            # A save always succeeds even if some characters can't be shown
            # (see src/core/text_pdf.py) -- the warning travels back in the
            # response rather than blocking the write.
            unsupported = render_text_pdf(req.text, out, block=BLOCK)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Saving failed: {e}") from e

    return SaveTextResponse(path=str(out), unsupported_characters=unsupported)


@app.post("/api/deidentify", response_model=DeidentifyResultsResponse)
def deidentify_documents(req: DeidentifyRequestBody):
    """
    Replace PII with non-identifying labels and write plain-text output.

    A sibling of /api/redact: same cache, same selections, same cooperative
    cancel. Only the output differs.

    PASTE_KEY is refused here (unlike in _deidentify_request_from, which this
    calls into) because THIS endpoint writes to disk — a real-name key file
    included — using req.folder_path as the destination. /api/deidentify/people
    and /api/deidentify/labels share that helper but never write anything, and
    the paste pathway's own /api/text/people and /api/text/labels legitimately
    call through them with documents=[PASTE_KEY] (see _paste_deidentify_body),
    so the guard cannot live in the shared helper without breaking those.
    """
    if PASTE_KEY in req.documents:
        raise HTTPException(status_code=400, detail="Invalid document path.")

    _redaction_control["cancel_requested"] = False
    request = _deidentify_request_from(req)

    try:
        service = DeidentificationService()
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
                    leftover_name_warnings=r.leftover_name_warnings,
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


_READ_OUTPUT_MAX_BYTES = 2 * 1024 * 1024


@app.post("/api/output/read", response_model=ReadOutputResponse)
def read_output(req: ReadOutputRequest):
    """
    Return a de-identified output file's text for in-app preview/copy.

    Narrower than the cleanup allowlist on purpose: only *_deidentified.txt.
    Quarantined .UNVERIFIED.txt may still contain PII and must be opened in an
    editor deliberately, not surfaced casually; the key file matches neither
    pattern and can never be read through here.
    """
    folder = Path(req.output_folder).resolve()
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Folder not found: {req.output_folder}")

    path = Path(req.file_path).resolve()
    if not path.is_relative_to(folder):
        raise HTTPException(status_code=400, detail="File is outside the output folder")
    if not path.name.endswith("_deidentified.txt"):
        raise HTTPException(status_code=400, detail="Not a de-identified output file")
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {req.file_path}")
    if path.stat().st_size > _READ_OUTPUT_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Output file too large to preview")

    return ReadOutputResponse(content=path.read_text(encoding="utf-8", errors="replace"))


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
