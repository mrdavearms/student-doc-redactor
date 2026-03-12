"""
Streamlit UI Screens
Thin UI layer — all business logic delegated to services.
"""

import streamlit as st
from pathlib import Path
import subprocess
from src.core import session_state
from src.core.pii_detector import PIIMatch
from src.services.conversion_service import ConversionService
from src.services.detection_service import DetectionService
from src.services.redaction_service import RedactionService, RedactionRequest


def folder_selection_screen():
    """Screen 1: Folder Selection and Setup"""

    st.markdown("### Step 1: Select Folder and Enter Student Details")

    # Folder selection
    st.markdown("#### Select Input Folder")

    st.info("**How to get the folder path**: In Finder, right-click the folder "
            "-> hold Option key -> select 'Copy \"foldername\" as Pathname' -> paste below")

    folder_input = st.text_input(
        "Folder path containing student documents:",
        value=str(st.session_state.folder_path) if st.session_state.folder_path else "",
        placeholder="/Users/username/Documents/Student_Docs",
        help="Paste the full path to the folder containing PDF and Word documents"
    )

    if folder_input and Path(folder_input).exists():
        st.session_state.folder_path = Path(folder_input)
        st.success(f"Folder found: {folder_input}")
    elif folder_input:
        st.error("Folder not found. Please check the path.")

    st.divider()

    # Student details
    st.markdown("#### Student Information")

    student_name = st.text_input(
        "Student full name (required):",
        value=st.session_state.student_name,
        placeholder="e.g., John Smith",
        help="This will be used to detect name variations"
    )

    parent_names = st.text_input(
        "Parent/Guardian names (optional, comma-separated):",
        value=st.session_state.parent_names,
        placeholder="e.g., Jane Smith, Robert Smith",
        help="Enter known parent/guardian names to improve detection accuracy"
    )

    family_names = st.text_input(
        "Other family members (optional, comma-separated):",
        value=st.session_state.family_names,
        placeholder="e.g., Emma Smith, Tom Smith",
        help="Enter sibling or other family member names"
    )

    # Save inputs to session state
    st.session_state.student_name = student_name
    st.session_state.parent_names = parent_names
    st.session_state.family_names = family_names

    st.divider()

    # Validation and start button
    can_proceed = (
        st.session_state.folder_path is not None
        and st.session_state.folder_path.exists()
        and student_name.strip() != ""
    )

    if not can_proceed:
        st.warning("Please select a valid folder and enter the student's name to continue")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("Start Processing", disabled=not can_proceed, use_container_width=True, type="primary"):
            session_state.navigate_to('conversion_status')


def conversion_status_screen():
    """Screen 2: Conversion Status"""

    st.markdown("### Step 2: Document Conversion")

    # Check dependencies via service
    st.markdown("#### Checking Dependencies...")
    service = ConversionService()
    deps = service.check_dependencies()

    col1, col2 = st.columns(2)
    with col1:
        if deps.libreoffice_ok:
            st.success(f"LibreOffice: {deps.libreoffice_message}")
        else:
            st.error(f"LibreOffice: {deps.libreoffice_message}")
    with col2:
        if deps.tesseract_ok:
            st.success("Tesseract OCR: Available")
        else:
            st.warning("Tesseract OCR: Not available (OCR features disabled)")

    if not deps.can_convert_word:
        st.error("Cannot proceed without LibreOffice. Please install it first.")
        if st.button("Back"):
            session_state.navigate_to('folder_selection')
        return

    st.divider()

    # Process documents via service
    st.markdown("#### Processing Documents...")

    with st.spinner("Converting Word documents and checking PDFs..."):
        results = service.process_folder(st.session_state.folder_path)
        st.session_state.conversion_results = results

    # Display results
    st.markdown("#### Conversion Results")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Files", results.total_files)
    with col2:
        st.metric("PDFs Ready", results.processable_count)
    with col3:
        st.metric("Converted", len(results.converted_files))
    with col4:
        st.metric("Flagged", results.flagged_count)

    # Show details
    if results.pdf_files:
        with st.expander(f"Original PDFs ({len(results.pdf_files)})"):
            for pdf in results.pdf_files:
                st.text(f"  {pdf.name}")

    if results.converted_files:
        with st.expander(f"Converted from Word ({len(results.converted_files)})"):
            for pdf in results.converted_files:
                st.text(f"  {pdf.name}")

    if results.password_protected:
        with st.expander(f"Password Protected ({len(results.password_protected)})", expanded=True):
            st.warning("These files are password protected and will be skipped. "
                       "Please unlock them manually if needed.")
            for pdf in results.password_protected:
                st.text(f"  {pdf.name}")

    if results.failed_conversions:
        with st.expander(f"Failed Conversions ({len(results.failed_conversions)})", expanded=True):
            st.error("These files could not be converted and will be skipped.")
            for file_path, reason in results.failed_conversions:
                st.text(f"  {file_path.name}: {reason}")

    st.divider()

    # Auto-run detection
    if results.processable_count == 0:
        st.error("No files available for processing. Please check your folder and try again.")
        if st.button("Back to Folder Selection"):
            session_state.navigate_to('folder_selection')
    else:
        if st.session_state.get('detected_pii'):
            # Detection already completed — navigate directly
            session_state.navigate_to('document_review')
        else:
            st.info(f"Ready to process {results.processable_count} documents")
            try:
                with st.spinner("Scanning for PII..."):
                    _run_detection()
                session_state.navigate_to('document_review')
            except Exception as e:
                st.error(f"Detection failed: {e}")
                if st.button("Back to Folder Selection"):
                    session_state.navigate_to('folder_selection')


def _run_detection():
    """Run PII detection via service and store results in session state."""
    results = st.session_state.conversion_results
    all_pdfs = results.all_processable_pdfs

    parent_list = [n.strip() for n in st.session_state.parent_names.split(',') if n.strip()]
    family_list = [n.strip() for n in st.session_state.family_names.split(',') if n.strip()]

    service = DetectionService(
        student_name=st.session_state.student_name,
        parent_names=parent_list,
        family_names=family_list,
    )

    detection_results = service.detect_all(all_pdfs)

    # Store in session state (convert DetectionResults to the dict format screens expect)
    st.session_state.detected_pii = {
        doc: {
            'matches': doc_pii.matches,
            'text_data': doc_pii.text_data,
        }
        for doc, doc_pii in detection_results.pii_by_document.items()
    }
    st.session_state.documents = detection_results.documents
    st.session_state.current_doc_index = 0


def document_review_screen():
    """Screen 3: Document Review"""

    st.markdown("### Step 3: Review Detected PII")

    # ── Accept All shortcut ──────────────────────────────────────────────
    if st.button(
        "✓ Accept All & Continue to Summary",
        use_container_width=True,
        type="primary",
        help="Mark all detected PII across every document for redaction and skip to the summary.",
    ):
        for doc in st.session_state.documents:
            matches = st.session_state.detected_pii.get(doc, {}).get('matches', [])
            for i in range(len(matches)):
                st.session_state.user_selections[f"{doc}_{i}"] = True
        session_state.navigate_to('final_confirmation')
    st.caption("All detected PII will be marked for redaction — or review each document below.")
    st.divider()

    if not st.session_state.documents:
        st.error("No documents to review")
        return

    current_idx = st.session_state.current_doc_index
    total_docs = len(st.session_state.documents)
    # ── Auto-skip zero-PII documents ─────────────────────────────────────
    docs_with_pii = [
        i for i, doc in enumerate(st.session_state.documents)
        if st.session_state.detected_pii.get(doc, {}).get('matches', [])
    ]
    future_pii = [i for i in docs_with_pii if i >= current_idx]
    if not future_pii:
        session_state.navigate_to('final_confirmation')
        return
    next_pii_idx = future_pii[0]
    if next_pii_idx != current_idx:
        skipped_names = [
            st.session_state.documents[i].name
            for i in range(current_idx, next_pii_idx)
        ]
        st.session_state.current_doc_index = next_pii_idx
        current_idx = next_pii_idx
        st.info(
            f"Skipped {len(skipped_names)} document(s) with no PII detected: "
            + ", ".join(skipped_names)
        )
    current_doc = st.session_state.documents[current_idx]

    # Progress indicator
    st.progress((current_idx + 1) / total_docs, text=f"Document {current_idx + 1} of {total_docs}")

    # Document name
    st.markdown(f"#### {current_doc.name}")

    # Get PII matches for current document
    doc_data = st.session_state.detected_pii.get(current_doc, {})
    matches = doc_data.get('matches', [])

    if not matches:
        st.info("No PII detected in this document")
    else:
        st.markdown(f"**Found {len(matches)} potential PII items**")

        # Select/Deselect all buttons
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Select All", use_container_width=True):
                for i in range(len(matches)):
                    st.session_state.user_selections[f"{current_doc}_{i}"] = True
                st.rerun()
        with col2:
            if st.button("Deselect All", use_container_width=True):
                for i in range(len(matches)):
                    st.session_state.user_selections[f"{current_doc}_{i}"] = False
                st.rerun()

        st.divider()

        # Display each match
        for idx, match in enumerate(matches):
            key = f"{current_doc}_{idx}"

            if key not in st.session_state.user_selections:
                st.session_state.user_selections[key] = True

            conf_color = {
                'high': '🟢',
                'medium': '🟡',
                'low': '🔴'
            }.get(match.confidence_label, '⚪')

            col1, col2 = st.columns([1, 20])
            with col1:
                checked = st.checkbox(
                    "",
                    value=st.session_state.user_selections[key],
                    key=f"cb_{key}"
                )
                st.session_state.user_selections[key] = checked

            with col2:
                st.markdown(f"""
                **Page {match.page_num}, Line {match.line_num}** {conf_color} {match.confidence_label.title()} confidence

                Category: `{match.category}`

                Context: {match.context}
                """)

            st.divider()

    # Navigation buttons
    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        if current_idx > 0:
            if st.button("Previous Document", use_container_width=True):
                st.session_state.current_doc_index -= 1
                st.rerun()

    with col2:
        if st.button("Cancel", use_container_width=True):
            session_state.navigate_to('folder_selection')

    with col3:
        if current_idx < total_docs - 1:
            if st.button("Next Document", use_container_width=True, type="primary"):
                st.session_state.current_doc_index += 1
                st.rerun()
        else:
            if st.button("Review Summary", use_container_width=True, type="primary"):
                session_state.navigate_to('final_confirmation')


def final_confirmation_screen():
    """Screen 4: Final Confirmation"""

    st.markdown("### Step 4: Final Confirmation")

    st.markdown("#### Ready to create redacted documents")

    # Calculate totals
    total_selected = sum(1 for selected in st.session_state.user_selections.values() if selected)
    total_docs = len(st.session_state.documents)

    # Count by category
    category_counts = {}
    for doc in st.session_state.documents:
        matches = st.session_state.detected_pii.get(doc, {}).get('matches', [])
        for idx, match in enumerate(matches):
            key = f"{doc}_{idx}"
            if st.session_state.user_selections.get(key, False):
                category_counts[match.category] = category_counts.get(match.category, 0) + 1

    # Display summary
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Items to Redact", total_selected)
    with col2:
        st.metric("Across Documents", total_docs)

    st.divider()

    st.markdown("#### Breakdown by Category")

    if category_counts:
        for category, count in sorted(category_counts.items()):
            st.text(f"  {category}: {count}")
    else:
        st.info("No items selected for redaction")

    st.divider()

    st.warning("This action cannot be undone. Original files will not be modified.")

    # Check for existing redacted folder
    redacted_folder = st.session_state.folder_path / "redacted"
    folder_action = None

    if redacted_folder.exists():
        st.info("A 'redacted' folder already exists — it will be overwritten.")
        create_new = st.checkbox("Create a new folder instead (redacted_2)")
        folder_action = "Create new folder (redacted_2)" if create_new else "Overwrite existing folder"
    else:
        folder_action = "Overwrite existing folder"

    # Buttons
    st.divider()
    col1, col2, col3 = st.columns([1, 2, 1])

    with col1:
        if st.button("Back to Review", use_container_width=True):
            session_state.navigate_to('document_review')

    with col2:
        if st.button("Cancel", use_container_width=True):
            session_state.navigate_to('folder_selection')

    with col3:
        if st.button("Create Redacted Documents", use_container_width=True, type="primary"):
            with st.spinner("Redacting documents..."):
                _run_redaction(folder_action)
            session_state.navigate_to('completion')


def _run_redaction(folder_action_label):
    """Run redaction via service and store results in session state."""
    # Map UI label to service action
    action_map = {
        "Overwrite existing folder": "overwrite",
        "Create new folder (redacted_2)": "new",
        None: None,
    }
    folder_action = action_map.get(folder_action_label)

    _parent_list = [n.strip() for n in st.session_state.parent_names.split(',') if n.strip()]
    _family_list = [n.strip() for n in st.session_state.family_names.split(',') if n.strip()]

    service = RedactionService()
    request = RedactionRequest(
        folder_path=st.session_state.folder_path,
        student_name=st.session_state.student_name,
        documents=st.session_state.documents,
        detected_pii=st.session_state.detected_pii,
        user_selections=st.session_state.user_selections,
        folder_action=folder_action,
        parent_names=_parent_list,
        family_names=_family_list,
    )

    results = service.execute(request)

    # Store results in session state
    st.session_state.redacted_folder = results.redacted_folder
    st.session_state.log_content = results.log_content
    st.session_state.verification_failures = results.verification_failures
    st.session_state.ocr_warnings = results.ocr_warnings
    st.session_state.document_results = results.document_results
    st.session_state.processing_complete = True


def completion_screen():
    """Screen 5: Completion"""

    st.markdown("### Step 5: Processing Complete")

    if not st.session_state.processing_complete:
        st.error("Processing not complete")
        return

    st.success("Successfully processed documents!")

    verification_failures = st.session_state.get('verification_failures', [])
    ocr_warnings = st.session_state.get('ocr_warnings', [])

    if verification_failures:
        st.error(f"{len(verification_failures)} document(s) failed redaction verification "
                 "- the original text may still be present. "
                 "Review the log and check these files manually.")

    if ocr_warnings:
        total_ocr_items = sum(count for _, count in ocr_warnings)
        st.warning(f"{total_ocr_items} item(s) across {len(ocr_warnings)} document(s) "
                   "are on image-only (scanned) pages and could not be automatically "
                   "redacted - manual review required.")

    # Show redacted folder
    st.markdown("#### Redacted Documents")
    st.info(f"Saved to: `{st.session_state.redacted_folder}`")

    # Filename mapping table — shows original → redacted name for audit trail
    document_results = st.session_state.get('document_results', [])
    if document_results:
        renamed = [
            r for r in document_results
            if r.output_path and r.output_path.name != f"{Path(r.document_name).stem}_redacted.pdf"
        ]
        if renamed:
            st.markdown("**Filename changes (PII removed from names):**")
            for r in renamed:
                original_stem = Path(r.document_name).stem
                new_name = r.output_path.name
                st.markdown(f"- `{original_stem}.pdf` → `{new_name}`")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Open Redacted Folder", use_container_width=True):
            subprocess.run(['open', str(st.session_state.redacted_folder)])

    st.divider()

    # Display log
    st.markdown("#### Redaction Log")

    with st.expander("View Full Log", expanded=True):
        st.code(st.session_state.log_content, language=None)

    st.divider()

    # Process another folder
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("Process Another Folder", use_container_width=True, type="primary"):
            session_state.reset_session()
            st.rerun()
