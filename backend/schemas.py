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


# ── Folder Processing (Conversion) ────────────────────────────────────────

class ProcessFolderRequest(BaseModel):
    folder_path: str


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


class DocumentResultResponse(BaseModel):
    document_name: str
    output_path: Optional[str]
    success: bool
    items_redacted: int
    verification_failures: List[str]
    ocr_warnings: List[str]
    error_message: Optional[str] = None


class RedactionResultsResponse(BaseModel):
    redacted_folder: str
    document_results: List[DocumentResultResponse]
    log_content: str
    log_path: Optional[str] = None
    total_documents: int
    successfully_redacted: int
    verification_failures: List[Dict[str, str]]  # [{filename, message}]
    ocr_warnings: List[Dict[str, int]]  # [{filename, count}]


# ── Utility ───────────────────────────────────────────────────────────────

class OpenFolderRequest(BaseModel):
    folder_path: str


class HealthResponse(BaseModel):
    status: str
    version: str
