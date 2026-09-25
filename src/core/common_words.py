"""
Ordinary English words, for the NOT_LOWERCASE rule in case_rules.py.

A Python module rather than a text file on purpose: the packaged app ships
only the *.py files under src/ (desktop/package.json, extraResources), so a
.txt beside this file would be missing from every .dmg and .exe.
"""

COMMON_WORDS = frozenset()
