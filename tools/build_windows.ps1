# Builds dist\Battop.exe in a separate venv (.venv-build) so the dev venv stays clean.
# Native tools log to stderr; Windows PowerShell 5.1 would turn that into an error, so check exit codes only.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path .venv-build)) { python -m venv .venv-build }
$py = ".\.venv-build\Scripts\python.exe"
& $py -m pip install --quiet --upgrade pip pyinstaller pystray Pillow
if ($LASTEXITCODE) { throw "pip install failed" }

& $py -m PyInstaller --noconfirm --clean battop.spec
if ($LASTEXITCODE) { throw "PyInstaller failed" }

Write-Host "Built dist\Battop.exe (unsigned: SmartScreen will warn on first run)."
