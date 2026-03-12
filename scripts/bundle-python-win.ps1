# bundle-python-win.ps1
#
# Downloads a portable Python (python-build-standalone) and installs all
# project dependencies into it. Run from the repo root before `npm run dist:win`.
#
# Output:
#   bundled-python\   — portable Python installation
#   bundled-tesseract\ — Tesseract binary + tessdata (eng)
#
# Requirements: PowerShell 5+, internet access

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PythonDest = Join-Path $RepoRoot "bundled-python"
$TesseractDest = Join-Path $RepoRoot "bundled-tesseract"

# ── Python version and release ────────────────────────────────────────
$PythonVersion = "3.13.12"
$PbsTag = "20260310"
$PbsFilename = "cpython-${PythonVersion}+${PbsTag}-x86_64-pc-windows-msvc-install_only.tar.gz"
$PbsUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/${PbsTag}/${PbsFilename}"

Write-Host "==> Bundling portable Python ${PythonVersion} (Windows x64)..."

if (Test-Path $PythonDest) {
    Write-Host "    $PythonDest already exists — remove it to re-bundle. Skipping."
} else {
    $TmpFile = [System.IO.Path]::GetTempFileName() + ".tar.gz"
    Write-Host "    Downloading $PbsUrl ..."
    Invoke-WebRequest -Uri $PbsUrl -OutFile $TmpFile -UseBasicParsing
    Write-Host "    Extracting..."
    # Use tar (available in Windows 10 1803+)
    tar -xzf $TmpFile -C $RepoRoot
    Rename-Item -Path (Join-Path $RepoRoot "python") -NewName "bundled-python"
    Remove-Item $TmpFile
    Write-Host "    Python extracted to $PythonDest"
}

$PythonBin = Join-Path $PythonDest "python.exe"

Write-Host "==> Installing pip dependencies into bundled Python..."
& $PythonBin -m pip install --upgrade pip --quiet
& $PythonBin -m pip install -r (Join-Path $RepoRoot "requirements.txt") --quiet

Write-Host "==> Downloading spaCy model (en_core_web_lg)..."
& $PythonBin -m spacy download en_core_web_lg --quiet

Write-Host "==> Pre-warming GLiNER model (urchade/gliner_multi_pii-v1)..."
& $PythonBin -c @"
from gliner import GLiNER
model = GLiNER.from_pretrained('urchade/gliner_multi_pii-v1')
print('GLiNER model cached.')
"@

# ── Bundle Tesseract ──────────────────────────────────────────────────
Write-Host "==> Bundling Tesseract..."

if (Test-Path $TesseractDest) {
    Write-Host "    $TesseractDest already exists — skipping."
} else {
    $TessInstallPaths = @(
        "C:\Program Files\Tesseract-OCR",
        "C:\Program Files (x86)\Tesseract-OCR"
    )

    $TessInstall = $null
    foreach ($p in $TessInstallPaths) {
        if (Test-Path (Join-Path $p "tesseract.exe")) {
            $TessInstall = $p
            break
        }
    }

    if ($null -eq $TessInstall) {
        Write-Error "Tesseract not found. Install from https://github.com/UB-Mannheim/tesseract/wiki"
        exit 1
    }

    New-Item -ItemType Directory -Force -Path (Join-Path $TesseractDest "tessdata") | Out-Null
    Copy-Item (Join-Path $TessInstall "tesseract.exe") -Destination $TesseractDest

    # Copy required DLLs (Tesseract on Windows needs these alongside the exe)
    Get-ChildItem -Path $TessInstall -Filter "*.dll" | ForEach-Object {
        Copy-Item $_.FullName -Destination $TesseractDest
    }

    # Copy English language data only
    $TessData = Join-Path $TessInstall "tessdata"
    $EngData = Join-Path $TessData "eng.traineddata"
    if (Test-Path $EngData) {
        Copy-Item $EngData -Destination (Join-Path $TesseractDest "tessdata\")
        Write-Host "    Copied eng.traineddata"
    } else {
        Write-Warning "eng.traineddata not found at $TessData"
    }

    Write-Host "    Tesseract bundled to $TesseractDest"
}

Write-Host ""
Write-Host "OK Bundle complete."
Write-Host "  Python: $PythonDest"
Write-Host "  Tesseract: $TesseractDest"
Write-Host ""
Write-Host "Next: cd desktop && npm run dist:win"
