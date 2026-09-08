@echo off
setlocal EnableExtensions
rem Copy lab onlogon + OO_Security onto the cabinet. Safe if dest folders are missing.
set "SRC=%~dp0"
if exist "%SRC%usb_scripts\shared\onlogon.ps1" set "SRC=%SRC%usb_scripts\shared\"

mkdir "c:\Goldclub\platform\user\init\" 2>nul
mkdir "c:\Goldclub\platform\user\init\onlogon\" 2>nul
mkdir "c:\Platform\Security\" 2>nul

set "ERR=0"
if exist "%SRC%onlogon.ps1" (
  copy /Y "%SRC%onlogon.ps1" "c:\Goldclub\platform\user\init\onlogon.ps1" >nul
  copy /Y "%SRC%onlogon.ps1" "c:\Platform\Security\onlogon.ps1" >nul
  if errorlevel 1 (
    echo Error: Failed to copy onlogon.ps1
    set "ERR=1"
  ) else (
    echo Copied onlogon.ps1 to c:\Goldclub\platform\user\init\
  )
) else (
  echo Error: onlogon.ps1 not next to this bat
  set "ERR=1"
)

if exist "%SRC%OO_Security.ps1" (
  copy /Y "%SRC%OO_Security.ps1" "c:\Platform\Security\OO_Security.ps1" >nul
  if errorlevel 1 (
    echo Error: Failed to copy OO_Security.ps1
    set "ERR=1"
  ) else (
    echo Copied OO_Security.ps1 to c:\Platform\Security\
  )
) else if exist "%SRC%..\..\platform-security\OO_Security.ps1" (
  copy /Y "%SRC%..\..\platform-security\OO_Security.ps1" "c:\Platform\Security\OO_Security.ps1" >nul
  if errorlevel 1 (
    echo Error: Failed to copy OO_Security.ps1
    set "ERR=1"
  ) else (
    echo Copied OO_Security.ps1 to c:\Platform\Security\
  )
) else (
  echo Note: OO_Security.ps1 not next to this bat - skipped
)

if exist "%SRC%StartGame.cmd" (
  copy /Y "%SRC%StartGame.cmd" "c:\Platform\Security\StartGame.cmd" >nul
  copy /Y "%SRC%StartGameWait.cmd" "c:\Platform\Security\StartGameWait.cmd" >nul
) else if exist "%SRC%platform-security\StartGame.cmd" (
  copy /Y "%SRC%platform-security\StartGame.cmd" "c:\Platform\Security\StartGame.cmd" >nul
  copy /Y "%SRC%platform-security\StartGameWait.cmd" "c:\Platform\Security\StartGameWait.cmd" >nul
)

if exist "%SRC%Start-LabDesktop.ps1" copy /Y "%SRC%Start-LabDesktop.ps1" "c:\Platform\Security\Start-LabDesktop.ps1" >nul
if exist "%SRC%Apply-CsRestore.ps1" copy /Y "%SRC%Apply-CsRestore.ps1" "c:\Platform\Security\Apply-CsRestore.ps1" >nul
if exist "%SRC%Start-GoldClubHardware.ps1" copy /Y "%SRC%Start-GoldClubHardware.ps1" "c:\Platform\Security\Start-GoldClubHardware.ps1" >nul
if exist "%SRC%Launch-LabUsbTool.ps1" copy /Y "%SRC%Launch-LabUsbTool.ps1" "c:\Platform\Security\Launch-LabUsbTool.ps1" >nul

exit /b %ERR%
