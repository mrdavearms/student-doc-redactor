"""
Session State Management
Handles all session state initialization and management for the Streamlit app.
"""

import streamlit as st

def init_session_state():
    """Initialize all session state variables"""

    # Screen navigation
    if 'current_screen' not in st.session_state:
        st.session_state.current_screen = 'folder_selection'

    # User inputs
    if 'folder_path' not in st.session_state:
        st.session_state.folder_path = None
    if 'student_name' not in st.session_state:
        st.session_state.student_name = ''
    if 'parent_names' not in st.session_state:
        st.session_state.parent_names = ''
    if 'family_names' not in st.session_state:
        st.session_state.family_names = ''

    # Processing state
    if 'documents' not in st.session_state:
        st.session_state.documents = []
    if 'conversion_results' not in st.session_state:
        st.session_state.conversion_results = {}
    if 'flagged_files' not in st.session_state:
        st.session_state.flagged_files = []

    # PII detection results
    if 'detected_pii' not in st.session_state:
        st.session_state.detected_pii = {}
    if 'current_doc_index' not in st.session_state:
        st.session_state.current_doc_index = 0
    if 'user_selections' not in st.session_state:
        st.session_state.user_selections = {}
    if 'global_decisions' not in st.session_state:
        st.session_state.global_decisions = {}

    # Redaction results
    if 'redacted_folder' not in st.session_state:
        st.session_state.redacted_folder = None
    if 'log_content' not in st.session_state:
        st.session_state.log_content = ''
    if 'processing_complete' not in st.session_state:
        st.session_state.processing_complete = False

def reset_session():
    """Reset all session state variables for processing a new folder"""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    init_session_state()

def navigate_to(screen_name):
    """Navigate to a specific screen"""
    st.session_state.current_screen = screen_name
    st.rerun()
