param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$appRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $appRoot
# Use a separate build environment; do not modify the user's Python install.
$venvPath = Join-Path $repoRoot "build\windows-venv"
& $Python -m venv $venvPath
if ($LASTEXITCODE -ne 0) { throw "Creating the Windows build environment failed." }
$buildPython = Join-Path $venvPath "Scripts\python.exe"
& $buildPython -m pip install -r (Join-Path $PSScriptRoot "windows-build-requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Installing Windows build dependencies failed." }
& $buildPython -m PyInstaller --noconfirm --clean --onefile --windowed --name EarLink `
    --paths $appRoot --distpath (Join-Path $repoRoot "build\windows") `
    --workpath (Join-Path $repoRoot "build\windows-work") `
    --specpath (Join-Path $repoRoot "build\windows-work") `
    (Join-Path $PSScriptRoot "windows-launcher.py")
if ($LASTEXITCODE -ne 0) { throw "Building EarLink.exe failed." }
Write-Output (Join-Path $repoRoot "build\windows\EarLink.exe")
