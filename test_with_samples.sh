#!/bin/bash
# Quick test script for Student Doc Redactor

echo "🔒 Student Doc Redactor - Quick Test"
echo "===================================="
echo ""
echo "This will launch the app and show you the sample folder path."
echo ""
echo "Sample folder path (copy this):"
echo "/Users/davidarmstrong/Antigravity/redaction tool/sample"
echo ""
echo "Student name: Joe Bloggs"
echo ""
echo "Press Enter to launch the app..."
read

cd "$(dirname "$0")"
source venv/bin/activate
streamlit run app.py
