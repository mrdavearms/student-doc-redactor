#!/bin/bash
# Run script for Student Doc Redactor

cd "$(dirname "$0")"
source venv/bin/activate
streamlit run app.py
