# First-Run Setup Screen & Cross-Platform Fixes

**Date:** 2026-03-15
**Status:** Approved

## Problem

1. Teachers installing the app on Windows (or Mac) hit a wall on screen 2 when LibreOffice is missing — with Mac-only install instructions ("brew install") and no guidance.
2. Several cross-platform bugs: Tesseract bundled path mismatch on Windows, Unix-only Python paths in Electron main process, macOS-only window options.
3. The "Check for Updates" button in the About modal is too small and easy to miss.
4. The GitHub repo is now public, unblocking `electron-updater` for both platforms.

## Design

### Part 1: Bug Fixes (both platforms)

#### 1a. Tesseract bundled path mismatch
- **File:** `src/core/binary_resolver.py`, line 35
- **Bug:** Windows candidate is `resources / "tesseract" / "tesseract.exe"` but the bundle script puts it at `resources / "bundled-tesseract" / "tesseract.exe"`
- **Fix:** Change Windows bundled candidate to `resources / "bundled-tesseract" / "tesseract.exe"`

#### 1b. Python spawn paths
- **File:** `desktop/electron/main.cjs`, lines 63-64
- **Bug:** Dev and prod paths hardcode Unix-style `venv/bin/python3.13` and `bundled-python/bin/python3`
- **Fix:** Add `process.platform` detection:
  - Windows dev: `venv/Scripts/python.exe`
  - Windows prod: `bundled-python/python.exe`
  - Mac dev: `venv/bin/python3.13`
  - Mac prod: `bundled-python/bin/python3`

#### 1c. titleBarStyle
- **File:** `desktop/electron/main.cjs`, line 103
- **Bug:** `titleBarStyle: 'hiddenInset'` is macOS-only (silently ignored on Windows but reflects platform-unaware code)
- **Fix:** Gate behind `process.platform === 'darwin'`

#### 1d. Folder placeholder
- **File:** `desktop/src/pages/FolderSelection.tsx`
- **Bug:** Shows `/Users/username/Documents/Student_Docs` on all platforms
- **Fix:** Use `window.electronAPI.platform` to show `C:\Users\username\Documents\Student_Docs` on Windows

#### 1e. Platform-aware LibreOffice error messages
- **File:** `src/core/document_converter.py` (already fixed)
- **Done:** `_libreoffice_install_hint()` returns platform-appropriate message

#### 1f. ConversionStatus no longer blocks PDF-only folders
- **File:** `desktop/src/pages/ConversionStatus.tsx` (already fixed)
- **Done:** Changed gate from `!deps?.can_convert_word` to `!deps`

### Part 2: Setup Screen

A lightweight gate screen that appears on first launch when LibreOffice is not found. Tesseract is bundled and invisible to the user.

#### Flow
```
App mounts → api.checkDependencies()
  → LibreOffice found? → folder_selection (normal)
  → LibreOffice missing? → setup screen
```

#### Screen layout
- Title: "Almost Ready" / subtitle: "One quick setup step before you start."
- Amber card explaining LibreOffice in teacher-friendly language: "LibreOffice is a free app that lets this tool read Word documents (.doc and .docx files)."
- "Download LibreOffice" button → opens system browser via `openExternal` to `https://www.libreoffice.org/download/download-libreoffice/` (auto-detects OS)
- "After installing, click the button below — no need to restart this app."
- "Check Again" button → re-calls `/api/dependencies/check` (fresh instance, re-resolves paths)
- "Skip for Now" button → proceeds to `folder_selection`
- Footer note: "Only needed for Word documents. If you only work with PDFs, you can skip this."

#### Success state (after Check Again finds LibreOffice)
- Title: "You're All Set" / subtitle: "Everything is ready to go."
- Two green checkmarks: "LibreOffice — Installed" and "Tesseract OCR — Built-in"
- "Get Started" button → navigates to `folder_selection`
- Auto-advances after 2 seconds if user doesn't click

#### Behaviors
- **Not permanently dismissible:** Reappears on next launch if LibreOffice is still missing (no localStorage flag for dismissal). "Skip for Now" only skips for current session.
- **Not a numbered step:** `'setup'` added to `Screen` type but NOT to `SCREENS` array. Sidebar only shows steps 1-5.
- **Initial screen stays `folder_selection`:** App.tsx checks deps on mount and redirects to `setup` if needed. This means returning users who have LibreOffice never see the setup screen.
- **No backend changes needed:** `/api/dependencies/check` already creates a fresh `ConversionService()` per request.

### Part 3: Update Pipeline Hardening

#### 3a. Release workflow
Already solid (`release.yml`). Push a `v*` tag → GitHub Actions builds Mac + Windows in parallel → artifacts land on the same GitHub Release. Repo is now public, so `electron-updater` pulls updates with no token.

#### 3b. More prominent "Check for Updates" in About modal
- Change from a tiny link to a proper button with visual weight
- Sits next to the version number so it's easy to find when sitting next to a teacher

#### 3c. Release process
1. Bump version in `desktop/package.json`
2. Commit, tag `v1.x.x`, push tag to GitHub
3. GitHub Actions builds both platforms, creates draft release
4. Review draft on GitHub, click "Publish"
5. Running apps pick up the update on next launch (10-second delay) or immediately via "Check for Updates"

### Not in scope
- No Tesseract download guidance (it's bundled)
- No auto-downloading of LibreOffice (teachers install themselves)
- No walkthrough changes (covers "how to use," not "is the app ready")
- No bundle script changes (already correct for both platforms)
- No CI/CD pipeline changes (already correct)

## Files to create/modify

| File | Action | Purpose |
|------|--------|---------|
| `src/core/binary_resolver.py` | Modify | Fix Tesseract bundled path on Windows |
| `desktop/electron/main.cjs` | Modify | Platform-aware Python paths, titleBarStyle gate |
| `desktop/src/types.ts` | Modify | Add `'setup'` to Screen type |
| `desktop/src/App.tsx` | Modify | Add dep check on mount, redirect to setup, add case |
| `desktop/src/pages/Setup.tsx` | Create | New setup screen component |
| `desktop/src/pages/FolderSelection.tsx` | Modify | Platform-aware placeholder |
| `desktop/src/components/AboutModal.tsx` | Modify | More prominent update button |
