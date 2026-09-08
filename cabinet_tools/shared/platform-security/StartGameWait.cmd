@echo off
rem Do not probe the SYSTEM goldclub junction (BitLocker hang). GOLDCLUB is G: after UnlockerDisk.
ping -n 31 127.0.0.1 >nul
if not exist G:\Bootstrap.exe exit /b 1
cd /d G:\
start "" /D "G:\" "G:\Bootstrap.exe"
exit /b 0
