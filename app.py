"""
Student Doc Redactor - Main Application
A standalone Mac application for redacting PII from student assessment documents.
"""

import streamlit as st
from pathlib import Path
import sys

# Import modules
from src.ui import screens
from src.core import session_state

# Configure Streamlit page
st.set_page_config(
    page_title="Student Doc Redactor",
    page_icon="🔒",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize session state
session_state.init_session_state()

def main():
    """Main application entry point"""

    # Custom CSS for better UI
    st.markdown("""
        <style>
        .main-header {
            font-size: 2.5rem;
            font-weight: bold;
            color: #1f77b4;
            margin-bottom: 1rem;
        }
        .sub-header {
            font-size: 1.2rem;
            color: #555;
            margin-bottom: 2rem;
        }
        .stButton>button {
            width: 100%;
            border-radius: 5px;
            height: 3em;
            font-weight: bold;
        }
        .success-box {
            padding: 1rem;
            border-radius: 5px;
            background-color: #d4edda;
            border: 1px solid #c3e6cb;
            color: #155724;
        }
        .warning-box {
            padding: 1rem;
            border-radius: 5px;
            background-color: #fff3cd;
            border: 1px solid #ffeeba;
            color: #856404;
        }
        .error-box {
            padding: 1rem;
            border-radius: 5px;
            background-color: #f8d7da;
            border: 1px solid #f5c6cb;
            color: #721c24;
        }
        </style>
    """, unsafe_allow_html=True)

    # Main header
    st.markdown('<div class="main-header">🔒 Student Doc Redactor</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Redact PII from student assessment documents with human oversight</div>', unsafe_allow_html=True)

    # Route to appropriate screen based on current step
    current_screen = st.session_state.get('current_screen', 'folder_selection')

    if current_screen == 'folder_selection':
        screens.folder_selection_screen()
    elif current_screen == 'conversion_status':
        screens.conversion_status_screen()
    elif current_screen == 'document_review':
        screens.document_review_screen()
    elif current_screen == 'final_confirmation':
        screens.final_confirmation_screen()
    elif current_screen == 'completion':
        screens.completion_screen()

if __name__ == "__main__":
    main()
