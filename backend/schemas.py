"""
Pydantic request/response models for the FastAPI backend.
These translate between JSON-friendly shapes and the service layer's dataclasses.
"""

from pydantic import BaseModel
from typing import Dict, List, Optional, Tuple


# ── Dependency Check ──────────────────────────────────────────────────────

class DependencyStatusResponse(BaseModel):
    libreoffice_ok: bool
    libreoffice_message: str
    tesseract_ok: bool
    can_convert_word: bool
    ner_ok: bool = False
    ner_message: str = ""


# ── Folder Processing (Conversion) ────────────────────────────────────────

class ProcessFolderRequest(BaseModel):
    folder_path: str


class ProcessFileRequest(BaseModel):
    """Single-document mode — one file instead of a whole folder."""
    file_path: str


class ConversionResultsResponse(BaseModel):
    pdf_files: List[str]
    converted_files: List[str]
    failed_conversions: List[Dict[str, str]]  # [{path, reason}]
    password_protected: List[str]
    total_files: int
    processable_count: int
    flagged_count: int


# ── PII Detection ─────────────────────────────────────────────────────────

class DetectPIIRequest(BaseModel):
    pdf_paths: List[str]
    student_name: str
    parent_names: List[str] = []
    family_names: List[str] = []
    organisation_names: List[str] = []


class PIIMatchResponse(BaseModel):
    text: str
    category: str
    confidence: float
    confidence_label: str
    page_num: int
    line_num: int
    context: str
    source: str
    bbox: Optional[List[float]] = None


class DocumentPIIResponse(BaseModel):
    path: str
    filename: str
    matches: List[PIIMatchResponse]
    ocr_pages: List[int]


class DetectionResultsResponse(BaseModel):
    documents: List[DocumentPIIResponse]
    total_matches: int


class AddManualPIIRequest(BaseModel):
    doc_path: str
    text: str
    page_num: int  # 1-indexed, matches PIIMatch.page_num convention
    category: str = "Manual"


class AddManualPIIResponse(BaseModel):
    match: PIIMatchResponse
    index: int


# ── Redaction ─────────────────────────────────────────────────────────────

class RedactionSelection(BaseModel):
    """One selected PII match to redact."""
    doc_path: str
    match_index: int


class RedactRequest(BaseModel):
    folder_path: str
    student_name: str
    documents: List[str]  # PDF paths
    detected_pii: Dict[str, List[Dict]]  # {doc_path: [match_dicts]}
    selected_keys: List[str]  # ["<doc_path>_<idx>", ...]
    folder_action: Optional[str] = None  # 'overwrite' | 'new' | None
    custom_output_path: Optional[str] = None  # User-chosen output folder
    # User-chosen output filename from the Save As dialog (single document only)
    custom_output_filename: Optional[str] = None
    parent_names: List[str] = []
    family_names: List[str] = []
    organisation_names: List[str] = []
    redact_header_footer: bool = False


class DocumentResultResponse(BaseModel):
    document_name: str
    output_path: Optional[str]
    success: bool
    items_redacted: int
    verification_failures: List[str]
    ocr_warnings: List[str]
    error_message: Optional[str] = None
    quarantine_path: Optional[str] = None


class OcrWarning(BaseModel):
    """
    One document's count of PII items that sat on scanned (image-only) pages.

    A typed model, NOT Dict[str, int]: the dict form claimed both values were
    ints, so the str filename failed validation and every redaction of a
    scanned document returned a 500 instead of its results.
    """
    filename: str
    count: int


class RedactionResultsResponse(BaseModel):
    redacted_folder: str
    document_results: List[DocumentResultResponse]
    log_content: str
    log_path: Optional[str] = None
    total_documents: int
    successfully_redacted: int
    verification_failures: List[Dict[str, str]]  # [{filename, message}]
    ocr_warnings: List[OcrWarning]
    cancelled: bool = False


# ── De-identification ────────────────────────────────────────────────────

class DeidentifyRequestBody(BaseModel):
    """
    Same inputs as a redaction run. redact_header_footer is kept and
    reinterpreted: it drops header/footer-zone text from the output instead of
    blanking those zones in a PDF.
    """
    folder_path: str
    student_name: str
    documents: List[str]
    selected_keys: List[str]  # ["<doc_path>_<idx>", ...]
    folder_action: Optional[str] = None
    custom_output_path: Optional[str] = None
    custom_output_filename: Optional[str] = None
    parent_names: List[str] = []
    family_names: List[str] = []
    organisation_names: List[str] = []
    redact_header_footer: bool = False
    # Answers from the "Who's who?" screen, keyed by discovered full name.
    person_roles: Dict[str, str] = {}
    person_custom_labels: Dict[str, str] = {}
    ignored_people: List[str] = []


class PersonInfoResponse(BaseModel):
    """One person for the classification screen.

    Carries a REAL NAME by construction — response only. Never written to disk,
    never into the audit log.
    """
    full_name: str
    label: str
    role: str
    custom_label: Optional[str] = None
    suggested_role: str
    confidence: str          # 'likely' | 'possible' | 'unknown' | 'entered'
    evidence: str = ""
    snippet: str = ""
    occurrences: int = 0
    source: str              # 'entered' | 'detected'


class PeopleResponse(BaseModel):
    people: List[PersonInfoResponse]
    roles: List[Dict[str, str]]   # [{key, label}] for the dropdown, in order


class LabelPreviewResponse(BaseModel):
    labels: Dict[str, str]        # full_name -> label under the proposal


class DeidentifyDocumentResultResponse(BaseModel):
    document_name: str
    output_path: Optional[str]
    success: bool
    items_replaced: int
    verification_failures: List[str]
    ocr_warnings: List[str]
    # Images can't carry into a text output, so their content is absent rather
    # than de-identified — surfaced so the omission isn't silent.
    image_warnings: List[str] = []
    # Real names by construction (post-run NER sweep) — response-only, never
    # logged or written to any file.
    leftover_name_warnings: List[str] = []
    error_message: Optional[str] = None
    quarantine_path: Optional[str] = None


class DeidentifyResultsResponse(BaseModel):
    output_folder: str
    # Written next to the ORIGINALS, never into output_folder — everything in
    # the output folder must stay safe to upload.
    key_file_path: Optional[str] = None
    # True when the user chose to write output into the folder holding the
    # originals. The folder then contains the originals and the key too, so the
    # UI must warn instead of reassuring.
    output_folder_holds_originals: bool = False
    document_results: List[DeidentifyDocumentResultResponse]
    log_content: str
    log_path: Optional[str] = None
    total_documents: int
    successfully_deidentified: int
    verification_failures: List[Dict[str, str]]  # [{filename, message}]
    ocr_warnings: List[OcrWarning]
    cancelled: bool = False


class ReadOutputRequest(BaseModel):
    output_folder: str
    file_path: str


class ReadOutputResponse(BaseModel):
    content: str


# ── Preview ──────────────────────────────────────────────────────────────

class PreviewRequest(BaseModel):
    pdf_path: str
    page_num: int  # 0-indexed


class PreviewResponse(BaseModel):
    image_base64: str
    total_pages: int
    page_num: int


# ── Utility ───────────────────────────────────────────────────────────────

class OpenFolderRequest(BaseModel):
    folder_path: str


class HealthResponse(BaseModel):
    status: str
    version: str
    # Whether the caller's X-Api-Token matches THIS process's token. Lets the
    # Electron launcher tell its own freshly-spawned backend apart from an
    # orphan (or a second copy of the app) already holding the port. True when
    # no token is configured at all — there is then no identity to check, and
    # a manually-run uvicorn must still look healthy.
    instance_match: bool = True


# ── Cleanup ──────────────────────────────────────────────────────────────

class CleanupListRequest(BaseModel):
    output_path: str


class CleanupListResponse(BaseModel):
    files: List[str]


class CleanupRequest(BaseModel):
    output_folder: str
    file_paths: List[str]


class CleanupFailure(BaseModel):
    path: str
    reason: str


class CleanupResponse(BaseModel):
    deleted: List[str]
    failed: List[CleanupFailure]
