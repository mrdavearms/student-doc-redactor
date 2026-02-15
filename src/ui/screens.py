"""
Streamlit UI Screens
All 5 screens for the Student Doc Redactor application.
"""

import streamlit as st
from pathlib import Path
import time
from src.core import session_state
from src.core.document_converter import DocumentConverter
from src.core.text_extractor import TextExtractor
from src.core.pii_detector import PIIDetector, PIIMatch
from src.core.redactor import PDFRedactor, RedactionItem
from src.core.logger import RedactionLogger, LogEntry
import subprocess

def folder_selection_screen():
    """Screen 1: Folder Selection and Setup"""

    st.markdown("### 📁 Step 1: Select Folder and Enter Student Details")

    # Folder selection
    st.markdown("#### Select Input Folder")

    # Show helpful tip for getting folder path
    st.info("💡 **How to get the folder path**: In Finder, right-click the folder → hold Option key → select 'Copy \"foldername\" as Pathname' → paste below")

    # Quick sample folder button
    sample_folder = "/Users/davidarmstrong/Antigravity/redaction tool/sample"
    if st.button("📂 Use Sample Folder (Joe Bloggs)", use_container_width=True):
        st.session_state.folder_path = Path(sample_folder)
        st.rerun()

    folder_input = st.text_input(
        "Folder path containing student documents:",
        value=str(st.session_state.folder_path) if st.session_state.folder_path else "",
        placeholder="/Users/username/Documents/Student_Docs",
        help="Paste the full path to the folder containing PDF and Word documents"
    )

    if folder_input and Path(folder_input).exists():
        st.session_state.folder_path = Path(folder_input)
        st.success(f"✓ Folder found: {folder_input}")
    elif folder_input:
        st.error("❌ Folder not found. Please check the path.")

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
        st.warning("⚠️ Please select a valid folder and enter the student's name to continue")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🚀 Start Processing", disabled=not can_proceed, use_container_width=True, type="primary"):
            # Navigate to conversion status
            session_state.navigate_to('conversion_status')


def conversion_status_screen():
    """Screen 2: Conversion Status"""

    st.markdown("### ⚙️ Step 2: Document Conversion")

    # Check dependencies
    st.markdown("#### Checking Dependencies...")
    converter = DocumentConverter()

    libreoffice_ok, libreoffice_msg = converter.check_libreoffice_installed()

    col1, col2 = st.columns(2)
    with col1:
        if libreoffice_ok:
            st.success(f"✓ LibreOffice: {libreoffice_msg}")
        else:
            st.error(f"❌ LibreOffice: {libreoffice_msg}")

    with col2:
        extractor = TextExtractor()
        if extractor.tesseract_available:
            st.success("✓ Tesseract OCR: Available")
        else:
            st.warning("⚠️ Tesseract OCR: Not available (OCR features disabled)")

    if not libreoffice_ok:
        st.error("Cannot proceed without LibreOffice. Please install it first.")
        if st.button("← Back"):
            session_state.navigate_to('folder_selection')
        return

    st.divider()

    # Process documents
    st.markdown("#### Processing Documents...")

    with st.spinner("Converting Word documents and checking PDFs..."):
        results = converter.process_folder(st.session_state.folder_path)
        st.session_state.conversion_results = results

    # Display results
    st.markdown("#### Conversion Results")

    total_files = (
        len(results['pdf_files'])
        + len(results['converted_files'])
        + len(results['failed_conversions'])
        + len(results['password_protected'])
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Files", total_files)
    with col2:
        st.metric("PDFs Ready", len(results['pdf_files']) + len(results['converted_files']))
    with col3:
        st.metric("Converted", len(results['converted_files']))
    with col4:
        flagged_count = len(results['failed_conversions']) + len(results['password_protected'])
        st.metric("Flagged", flagged_count)

    # Show details
    if results['pdf_files']:
        with st.expander(f"✓ Original PDFs ({len(results['pdf_files'])})"):
            for pdf in results['pdf_files']:
                st.text(f"  ✓ {pdf.name}")

    if results['converted_files']:
        with st.expander(f"✓ Converted from Word ({len(results['converted_files'])})"):
            for pdf in results['converted_files']:
                st.text(f"  ✓ {pdf.name}")

    if results['password_protected']:
        with st.expander(f"⚠️ Password Protected ({len(results['password_protected'])})", expanded=True):
            st.warning("These files are password protected and will be skipped. Please unlock them manually if needed.")
            for pdf in results['password_protected']:
                st.text(f"  ⚠️ {pdf.name}")

    if results['failed_conversions']:
        with st.expander(f"❌ Failed Conversions ({len(results['failed_conversions'])})", expanded=True):
            st.error("These files could not be converted and will be skipped.")
            for file_path, reason in results['failed_conversions']:
                st.text(f"  ❌ {file_path.name}: {reason}")

    st.divider()

    # Continue button
    processable_files = len(results['pdf_files']) + len(results['converted_files'])

    if processable_files == 0:
        st.error("No files available for processing. Please check your folder and try again.")
        if st.button("← Back to Folder Selection"):
            session_state.navigate_to('folder_selection')
    else:
        st.info(f"✓ Ready to process {processable_files} documents")

        col1, col2, col3 = st.columns([1, 2, 1])
        with col1:
            if st.button("← Back", use_container_width=True):
                session_state.navigate_to('folder_selection')
        with col3:
            if st.button("Continue →", use_container_width=True, type="primary"):
                # Extract text and detect PII
                _process_documents_for_pii()
                session_state.navigate_to('document_review')


def _process_documents_for_pii():
    """Helper function to extract text and detect PII"""

    results = st.session_state.conversion_results
    all_pdfs = results['pdf_files'] + results['converted_files']

    # Initialize detector
    parent_list = [n.strip() for n in st.session_state.parent_names.split(',') if n.strip()]
    family_list = [n.strip() for n in st.session_state.family_names.split(',') if n.strip()]

    detector = PIIDetector(
        student_name=st.session_state.student_name,
        parent_names=parent_list,
        family_names=family_list
    )

    extractor = TextExtractor()

    # Process each PDF
    detected_pii = {}

    for pdf_path in all_pdfs:
        # Extract text
        text_data = extractor.extract_text_from_pdf(pdf_path)

        # Detect PII in each page
        pii_matches = []
        for page_num, page_data in text_data['pages'].items():
            matches = detector.detect_pii_in_text(page_data['text'], page_num)
            pii_matches.extend(matches)

        # Store results
        detected_pii[pdf_path] = {
            'matches': pii_matches,
            'text_data': text_data
        }

    st.session_state.detected_pii = detected_pii
    st.session_state.documents = all_pdfs
    st.session_state.current_doc_index = 0


def document_review_screen():
    """Screen 3: Document Review"""

    st.markdown("### 📋 Step 3: Review Detected PII")

    if not st.session_state.documents:
        st.error("No documents to review")
        return

    current_idx = st.session_state.current_doc_index
    total_docs = len(st.session_state.documents)
    current_doc = st.session_state.documents[current_idx]

    # Progress indicator
    st.progress((current_idx + 1) / total_docs, text=f"Document {current_idx + 1} of {total_docs}")

    # Document name
    st.markdown(f"#### 📄 {current_doc.name}")

    # Get PII matches for current document
    doc_data = st.session_state.detected_pii.get(current_doc, {})
    matches = doc_data.get('matches', [])

    if not matches:
        st.info("✓ No PII detected in this document")
    else:
        st.markdown(f"**Found {len(matches)} potential PII items**")

        # Select/Deselect all buttons
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✓ Select All", use_container_width=True):
                for i in range(len(matches)):
                    st.session_state.user_selections[f"{current_doc}_{i}"] = True
                st.rerun()
        with col2:
            if st.button("✗ Deselect All", use_container_width=True):
                for i in range(len(matches)):
                    st.session_state.user_selections[f"{current_doc}_{i}"] = False
                st.rerun()

        st.divider()

        # Display each match
        for idx, match in enumerate(matches):
            key = f"{current_doc}_{idx}"

            # Default to checked
            if key not in st.session_state.user_selections:
                st.session_state.user_selections[key] = True

            # Confidence color
            conf_color = {
                'high': '🟢',
                'medium': '🟡',
                'low': '🔴'
            }.get(match.confidence, '⚪')

            # Create checkbox with details
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
                **Page {match.page_num}, Line {match.line_num}** {conf_color} {match.confidence.title()} confidence

                Category: `{match.category}`

                Context: {match.context}
                """)

            st.divider()

    # Navigation buttons
    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        if current_idx > 0:
            if st.button("← Previous Document", use_container_width=True):
                st.session_state.current_doc_index -= 1
                st.rerun()

    with col2:
        if st.button("Cancel", use_container_width=True):
            session_state.navigate_to('folder_selection')

    with col3:
        if current_idx < total_docs - 1:
            if st.button("Next Document →", use_container_width=True, type="primary"):
                st.session_state.current_doc_index += 1
                st.rerun()
        else:
            if st.button("Review Summary →", use_container_width=True, type="primary"):
                session_state.navigate_to('final_confirmation')


def final_confirmation_screen():
    """Screen 4: Final Confirmation"""

    st.markdown("### ✅ Step 4: Final Confirmation")

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
            st.text(f"  • {category}: {count}")
    else:
        st.info("No items selected for redaction")

    st.divider()

    # Warning
    st.warning("⚠️ This action cannot be undone. Original files will not be modified.")

    # Check for existing redacted folder
    redacted_folder = st.session_state.folder_path / "redacted"
    folder_action = None

    if redacted_folder.exists():
        st.info("📁 A 'redacted' folder already exists")
        folder_action = st.radio(
            "Choose an action:",
            ["Overwrite existing folder", "Create new folder (redacted_2)", "Cancel"],
            index=0
        )

    # Buttons
    st.divider()
    col1, col2, col3 = st.columns([1, 2, 1])

    with col1:
        if st.button("← Back to Review", use_container_width=True):
            session_state.navigate_to('document_review')

    with col2:
        if st.button("❌ Cancel", use_container_width=True):
            session_state.navigate_to('folder_selection')

    with col3:
        disabled = (folder_action == "Cancel") if folder_action else False
        if st.button("✅ Create Redacted Documents", use_container_width=True, type="primary", disabled=disabled):
            _perform_redaction(folder_action)
            session_state.navigate_to('completion')


def _perform_redaction(folder_action):
    """Helper function to perform actual redaction"""

    # Determine output folder
    redacted_folder = st.session_state.folder_path / "redacted"

    if folder_action == "Overwrite existing folder":
        # Delete existing folder
        import shutil
        if redacted_folder.exists():
            shutil.rmtree(redacted_folder)
        redacted_folder.mkdir()
    elif folder_action == "Create new folder (redacted_2)":
        # Find next available number
        counter = 2
        while (st.session_state.folder_path / f"redacted_{counter}").exists():
            counter += 1
        redacted_folder = st.session_state.folder_path / f"redacted_{counter}"
        redacted_folder.mkdir()
    else:
        # No existing folder
        redacted_folder.mkdir(exist_ok=True)

    st.session_state.redacted_folder = redacted_folder

    # Initialize logger
    logger = RedactionLogger(st.session_state.folder_path, st.session_state.student_name)

    # Initialize redactor
    redactor = PDFRedactor()

    # Process each document
    successfully_redacted = 0

    for doc in st.session_state.documents:
        matches = st.session_state.detected_pii.get(doc, {}).get('matches', [])

        # Filter to only selected items
        selected_matches = []
        for idx, match in enumerate(matches):
            key = f"{doc}_{idx}"
            if st.session_state.user_selections.get(key, False):
                selected_matches.append(match)

        # Create redaction items
        redaction_items = []
        for match in selected_matches:
            redaction_items.append(RedactionItem(
                page_num=match.page_num,
                text=match.text,
                bbox=match.bbox
            ))

            # Add to log
            logger.add_entry(LogEntry(
                document_name=doc.name,
                output_name=f"{doc.stem}_redacted.pdf",
                page_num=match.page_num,
                line_num=match.line_num,
                text=match.text,
                category=match.category,
                confidence=match.confidence
            ))

        # Perform redaction
        output_path = redacted_folder / f"{doc.stem}_redacted.pdf"
        success, message = redactor.redact_pdf(doc, output_path, redaction_items)

        if success:
            successfully_redacted += 1

    # Add flagged files to log
    for flagged_file in st.session_state.conversion_results.get('password_protected', []):
        logger.add_flagged_file(flagged_file.name, "Password protected (skipped)")

    for file_path, reason in st.session_state.conversion_results.get('failed_conversions', []):
        logger.add_flagged_file(file_path.name, reason)

    # Set totals
    logger.set_totals(len(st.session_state.documents), successfully_redacted)

    # Generate and save log
    log_path = logger.save_log()
    st.session_state.log_content = logger.generate_log()
    st.session_state.processing_complete = True


def completion_screen():
    """Screen 5: Completion"""

    st.markdown("### 🎉 Step 5: Processing Complete")

    if not st.session_state.processing_complete:
        st.error("Processing not complete")
        return

    st.success(f"✓ Successfully processed documents!")

    # Show redacted folder
    st.markdown("#### Redacted Documents")
    st.info(f"📁 Saved to: `{st.session_state.redacted_folder}`")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("📂 Open Redacted Folder", use_container_width=True):
            subprocess.run(['open', str(st.session_state.redacted_folder)])

    st.divider()

    # Display log
    st.markdown("#### Redaction Log")

    with st.expander("📜 View Full Log", expanded=True):
        st.code(st.session_state.log_content, language=None)

    st.divider()

    # Process another folder
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🔄 Process Another Folder", use_container_width=True, type="primary"):
            session_state.reset_session()
            st.rerun()
