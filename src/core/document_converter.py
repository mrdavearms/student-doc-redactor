"""
Document Converter
Converts Word documents to PDF using LibreOffice in headless mode.
"""

import subprocess
from pathlib import Path
from typing import Dict, List, Tuple
import fitz  # PyMuPDF

class DocumentConverter:
    """Handles conversion of Word documents to PDF"""

    def __init__(self):
        # Path to LibreOffice binary (installed via Homebrew)
        self.soffice_path = "/opt/homebrew/bin/soffice"

    def check_libreoffice_installed(self) -> Tuple[bool, str]:
        """
        Check if LibreOffice is installed and accessible

        Returns:
            Tuple of (is_installed, message)
        """
        try:
            result = subprocess.run(
                [self.soffice_path, '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True, f"LibreOffice found: {result.stdout.strip()}"
            else:
                return False, "LibreOffice not responding correctly"
        except FileNotFoundError:
            return False, "LibreOffice not found. Please install via: brew install --cask libreoffice"
        except subprocess.TimeoutExpired:
            return False, "LibreOffice check timed out"
        except Exception as e:
            return False, f"Error checking LibreOffice: {str(e)}"

    def convert_to_pdf(self, input_file: Path, output_dir: Path) -> Tuple[bool, str, Path]:
        """
        Convert a Word document to PDF

        Args:
            input_file: Path to .doc or .docx file
            output_dir: Directory to save the PDF

        Returns:
            Tuple of (success, message, output_path)
        """
        if input_file.suffix.lower() not in ['.doc', '.docx']:
            return False, f"Not a Word document: {input_file.suffix}", None

        try:
            # Use LibreOffice in headless mode to convert
            result = subprocess.run(
                [
                    self.soffice_path,
                    '--headless',
                    '--convert-to', 'pdf',
                    '--outdir', str(output_dir),
                    str(input_file)
                ],
                capture_output=True,
                text=True,
                timeout=60  # 60 second timeout for conversion
            )

            # Expected output filename
            output_file = output_dir / f"{input_file.stem}.pdf"

            if result.returncode == 0 and output_file.exists():
                return True, "Conversion successful", output_file
            else:
                error_msg = result.stderr if result.stderr else result.stdout
                return False, f"Conversion failed: {error_msg}", None

        except subprocess.TimeoutExpired:
            return False, "Conversion timed out (>60s)", None
        except Exception as e:
            return False, f"Error during conversion: {str(e)}", None

    def check_pdf_password_protected(self, pdf_path: Path) -> Tuple[bool, str]:
        """
        Check if a PDF is password protected

        Args:
            pdf_path: Path to PDF file

        Returns:
            Tuple of (is_protected, message)
        """
        try:
            doc = fitz.open(str(pdf_path))
            if doc.is_encrypted:
                doc.close()
                return True, "PDF is password protected"
            doc.close()
            return False, "PDF is accessible"
        except Exception as e:
            return True, f"Error checking PDF: {str(e)}"

    def process_folder(self, folder_path: Path) -> Dict:
        """
        Process all documents in a folder

        Args:
            folder_path: Path to folder containing documents

        Returns:
            Dictionary with conversion results:
            {
                'pdf_files': List[Path],  # Original PDFs
                'converted_files': List[Path],  # Converted PDFs
                'failed_conversions': List[Tuple[Path, str]],  # Failed files with reason
                'password_protected': List[Path]  # Password-protected PDFs
            }
        """
        results = {
            'pdf_files': [],
            'converted_files': [],
            'failed_conversions': [],
            'password_protected': []
        }

        # Create temp directory for converted files
        temp_dir = folder_path / '.temp_converted'
        temp_dir.mkdir(exist_ok=True)

        # Find all documents
        word_files = list(folder_path.glob('*.doc')) + list(folder_path.glob('*.docx'))
        pdf_files = list(folder_path.glob('*.pdf'))

        # Process Word files
        for word_file in word_files:
            success, message, output_path = self.convert_to_pdf(word_file, temp_dir)
            if success:
                results['converted_files'].append(output_path)
            else:
                results['failed_conversions'].append((word_file, message))

        # Check PDF files for password protection
        for pdf_file in pdf_files:
            is_protected, message = self.check_pdf_password_protected(pdf_file)
            if is_protected:
                results['password_protected'].append(pdf_file)
            else:
                results['pdf_files'].append(pdf_file)

        return results
