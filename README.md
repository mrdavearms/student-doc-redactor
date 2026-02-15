# Student Doc Redactor

A standalone Mac application for redacting personally identifiable information (PII) from student assessment documents.

## Quick Start

### Running the Application

1. Open Terminal
2. Navigate to this folder:
   ```bash
   cd "/Users/davidarmstrong/Antigravity/redaction tool"
   ```
3. Run the application:
   ```bash
   ./run.sh
   ```
4. Your browser will open automatically to `http://localhost:8501`

### Alternative: Run Directly

```bash
source venv/bin/activate
streamlit run app.py
```

## Features

- ✅ Converts Word documents to PDF automatically
- ✅ Detects Australian PII (names, addresses, phone numbers, Medicare numbers, etc.)
- ✅ OCR support for scanned documents
- ✅ Human review of all detected PII
- ✅ Permanent redaction (text cannot be recovered)
- ✅ Detailed audit logging
- ✅ Preserves original files

## Usage Workflow

1. **Select Folder**: Choose folder containing student documents
2. **Enter Details**: Provide student name and optional family member names
3. **Review Conversion**: Check which documents were successfully converted
4. **Review PII**: Go through each document and approve/reject detected items
5. **Confirm**: Review summary before creating redacted copies
6. **Complete**: View results and access redacted documents

## Sample Data

Test the application with the sample documents in the `sample/` folder:
- Student: Joe Bloggs
- Contains various PDF and Word documents

## System Requirements

- macOS (Apple Silicon or Intel)
- Python 3.11 or later
- LibreOffice (installed via Homebrew)
- Tesseract OCR (installed via Homebrew)

## Dependencies

All Python dependencies are installed in the virtual environment:
- Streamlit (UI framework)
- PyMuPDF (PDF processing)
- pytesseract (OCR)
- Pillow (Image processing)
- python-docx (Word document handling)

External dependencies:
- LibreOffice: For Word to PDF conversion
- Tesseract: For OCR on scanned documents

## Troubleshooting

### "LibreOffice not found"
Install LibreOffice:
```bash
brew install --cask libreoffice
```

### "Tesseract not found"
Install Tesseract:
```bash
brew install tesseract
```

### Port already in use
If port 8501 is busy, Streamlit will automatically use the next available port.

### Browser doesn't open automatically
Manually navigate to: http://localhost:8501

## File Structure

```
redaction tool/
├── app.py                 # Main application entry point
├── run.sh                 # Quick launch script
├── requirements.txt       # Python dependencies
├── venv/                  # Virtual environment
├── sample/                # Sample documents for testing
└── src/
    ├── core/              # Core processing modules
    │   ├── pii_detector.py       # PII detection engine
    │   ├── document_converter.py # Word to PDF conversion
    │   ├── text_extractor.py     # Text extraction with OCR
    │   ├── redactor.py           # Redaction engine
    │   ├── logger.py             # Audit logging
    │   └── session_state.py      # Session management
    └── ui/
        └── screens.py     # All 5 Streamlit screens
```

## Output

When processing is complete, you'll find:

1. **redacted/** folder: Contains redacted PDFs with `_redacted` suffix
2. **redaction_log.txt**: Detailed audit log in the original folder

## Security Notes

- Original files are NEVER modified
- Redacted text is permanently removed (not just visually covered)
- All processing happens locally on your Mac
- No data is sent to external services

## Next Steps

To package as a standalone .app bundle, we'll use PyInstaller or py2app (not yet implemented).

## Support

For issues or questions, refer to the technical specification document.
