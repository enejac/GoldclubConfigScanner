@echo off
rem Winlogon Userinit — returns immediately so the GoldClub shell can start.
start "" "C:\Platform\Security\UnlockerDisk.exe"
start "" "C:\Platform\Security\StartGameWait.cmd"
exit /b 0
