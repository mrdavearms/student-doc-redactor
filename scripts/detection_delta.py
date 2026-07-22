"""Developer tool: category counts for the current detector over sample/ PDFs.

Run before and after a detection-pattern change and diff the two outputs:

    git stash && venv/bin/python3.13 scripts/detection_delta.py > /tmp/before.txt
    git stash pop && venv/bin/python3.13 scripts/detection_delta.py > /tmp/after.txt
    diff /tmp/before.txt /tmp/after.txt

Unit tests cannot see noise regressions across real documents; this can.
"""

import collections
import glob
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src" / "core"))

import fitz  # noqa: E402
from pii_detector import PIIDetector  # noqa: E402

# The sample corpus is one student; adjust these if the sample data changes.
STUDENT = "Jobe Fenn"
PARENTS = ["Louisa Fenn"]


def main():
    pdfs = sorted(glob.glob(str(_ROOT / "sample" / "**" / "*.pdf"), recursive=True))
    if not pdfs:
        print("No sample PDFs found — nothing to compare.")
        return

    detector = PIIDetector(STUDENT, parent_names=PARENTS)
    counts = collections.Counter()
    items = set()

    for path in pdfs:
        with fitz.open(path) as doc:
            for page in doc:
                for m in detector.detect_pii_in_text(page.get_text(), page_num=page.number + 1):
                    counts[m.category] += 1
                    items.add((Path(path).name, m.category, m.text))

    print(f"documents: {len(pdfs)}")
    print(f"{'category':36s} {'count':>6s}")
    for category in sorted(counts):
        print(f"{category:36s} {counts[category]:6d}")
    print("\nall distinct items (file | category | text):")
    for item in sorted(items):
        print("  " + " | ".join(item))


if __name__ == "__main__":
    main()
