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
# Bake date+clock into the window title so lab builds are easy to tell apart.
python -c "from datetime import datetime; from pathlib import Path; stamp = datetime.now().strftime('%Y-%m-%d %H:%M'); Path('config_scanner/_build_stamp.py').write_text('BUILD_STAMP = %r\n' % stamp, encoding='utf-8'); print('Build stamp: ' + stamp)"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts/generate_link2win_hashes.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m PyInstaller --noconfirm --clean ConfigScanner.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (-not (Test-Path $exe)) {
    Write-Host "Build finished but exe not found at $exe" -ForegroundColor Red
    exit 1
}

$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Copy-Item -LiteralPath $exe -Destination (Join-Path $PSScriptRoot "ConfigScanner.exe") -Force
python -c "from pathlib import Path; from config_scanner.tool_sidecar import stage_sidecar_tools; d=Path(r'dist')/'tools'; stage_sidecar_tools(d); print('Staged tools ->', d)"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -c "from pathlib import Path; from config_scanner.tool_sidecar import stage_sidecar_tools; stage_sidecar_tools(Path(r'.')/'tools'); print('Staged tools -> repo root tools')"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$rootCrypt = Join-Path $PSScriptRoot "CRYPT_TOOLS"
if (Test-Path -LiteralPath $rootCrypt) {
    Remove-Item -LiteralPath $rootCrypt -Recurse -Force
}
python -c "from datetime import date; from pathlib import Path; from config_scanner.tool_sidecar import build_portable_zip; name='ConfigScanner-'+date.today().strftime('%Y-%m-%d'); z=Path('dist')/(name+'.zip'); build_portable_zip(Path(r'dist')/'ConfigScanner.exe', z, folder_name=name); import shutil; shutil.copy2(z, Path(name+'.zip')); print('Zip:', z.resolve())"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Copied tools next to ConfigScanner.exe" -ForegroundColor Green
Write-Host ("Build complete: {0} ({1} MB)" -f $exe, $sizeMb) -ForegroundColor Green
