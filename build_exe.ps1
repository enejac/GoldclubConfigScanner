<#
.SYNOPSIS
    Build ConfigScanner.exe (config SHA1 scan / restore only).
#>
[CmdletBinding()]
param(
    [switch]$InstallDeps
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing PyInstaller..." -ForegroundColor Yellow
    python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

if ($InstallDeps) {
    python -m pip install -r requirements.txt
}

$exe = Join-Path $PSScriptRoot "dist\ConfigScanner.exe"
python -m PyInstaller --noconfirm --clean ConfigScanner.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (-not (Test-Path $exe)) {
    Write-Host "Build finished but exe not found at $exe" -ForegroundColor Red
    exit 1
}

$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Copy-Item -LiteralPath $exe -Destination (Join-Path $PSScriptRoot "ConfigScanner.exe") -Force
Write-Host ("Build complete: {0} ({1} MB)" -f $exe, $sizeMb) -ForegroundColor Green
