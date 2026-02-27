"""
Redaction Logger
Generates detailed audit logs of all redaction operations.
"""

from pathlib import Path
from datetime import datetime
from typing import List, Dict
from dataclasses import dataclass

@dataclass
class LogEntry:
    """Single redaction log entry"""
    document_name: str
    output_name: str
    page_num: int
    line_num: int
    text: str
    category: str
    confidence: float
    notes: str = ""

class RedactionLogger:
    """Creates detailed audit logs for redaction operations"""

    def __init__(self, folder_path: Path, student_name: str):
        self.folder_path = folder_path
        self.student_name = student_name
        self.log_entries: List[LogEntry] = []
        self.flagged_files: List[tuple] = []
        self.total_documents = 0
        self.successfully_redacted = 0

    def add_entry(self, entry: LogEntry):
        """Add a log entry"""
        self.log_entries.append(entry)

    def add_flagged_file(self, filename: str, reason: str):
        """Add a file flagged for manual review"""
        self.flagged_files.append((filename, reason))

    def set_totals(self, total: int, successful: int):
        """Set document totals"""
        self.total_documents = total
        self.successfully_redacted = successful

    def generate_log(self) -> str:
        """
        Generate the complete log file content

        Returns:
            Log file content as string
        """
        lines = []

        # Header
        lines.append("STUDENT DOC REDACTOR - REDACTION LOG")
        lines.append("=" * 61)
        lines.append(f"Folder: {self.folder_path}")
        lines.append(f"Student: {self.student_name}")
        lines.append(f"Processed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Total documents: {self.total_documents}")
        lines.append(f"Successfully redacted: {self.successfully_redacted}")
        lines.append(f"Flagged for manual review: {len(self.flagged_files)}")
        lines.append("")

        # Group entries by document
        docs = {}
        for entry in self.log_entries:
            key = (entry.document_name, entry.output_name)
            if key not in docs:
                docs[key] = []
            docs[key].append(entry)

        # Write document sections
        for (doc_name, output_name), entries in docs.items():
            lines.append(f"DOCUMENT: {doc_name} → {output_name}")
            lines.append("─" * 76)

            # Sort entries by page and line
            entries.sort(key=lambda e: (e.page_num, e.line_num))

            for entry in entries:
                conf_label = 'high' if entry.confidence >= 0.8 else ('medium' if entry.confidence >= 0.5 else 'low')
                line = f"Page {entry.page_num}, Line {entry.line_num}: \"{entry.text}\" [{entry.category}] [{conf_label} confidence]"
                lines.append(line)

                if entry.notes:
                    lines.append(f"    Note: {entry.notes}")

            lines.append("")

        # Flagged files section
        if self.flagged_files:
            lines.append("FLAGGED FOR MANUAL REVIEW")
            lines.append("─" * 25)
            for filename, reason in self.flagged_files:
                lines.append(f"- {filename}: {reason}")
            lines.append("")

        # Footer
        lines.append("END OF LOG")

        return "\n".join(lines)

    def save_log(self, filename: str = "redaction_log.txt") -> Path:
        """
        Save the log to a file

        Args:
            filename: Name of log file

        Returns:
            Path to saved log file
        """
        log_path = self.folder_path / filename
        log_content = self.generate_log()

        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(log_content)

        return log_path

    def get_summary_stats(self) -> Dict:
        """
        Get summary statistics for the log

        Returns:
            Dictionary with summary statistics
        """
        # Count by category
        category_counts = {}
        for entry in self.log_entries:
            category_counts[entry.category] = category_counts.get(entry.category, 0) + 1

        # Count by confidence (bucket into high/medium/low)
        confidence_counts = {}
        for entry in self.log_entries:
            label = 'high' if entry.confidence >= 0.8 else ('medium' if entry.confidence >= 0.5 else 'low')
            confidence_counts[label] = confidence_counts.get(label, 0) + 1

        return {
            'total_redactions': len(self.log_entries),
            'total_documents': self.total_documents,
            'successful_documents': self.successfully_redacted,
            'flagged_files': len(self.flagged_files),
            'category_breakdown': category_counts,
            'confidence_breakdown': confidence_counts
        }
