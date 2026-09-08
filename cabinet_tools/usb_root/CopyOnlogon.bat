@echo off
setlocal EnableExtensions
rem USB root shortcut -> usb_scripts\shared (onlogon + OO_Security)
set "TARGET=%~dp0usb_scripts\shared\CopyOnlogon.bat"
if not exist "%TARGET%" (
  echo ERROR: missing %TARGET%
  echo Expected layout: usb_scripts\shared\CopyOnlogon.bat + onlogon.ps1 + OO_Security.ps1
  pause
  exit /b 1
)
call "%TARGET%" %*
exit /b %ERRORLEVEL%
