@echo off
rem Fallback if eshell launches .cmd instead of .ps1 directly
>>C:\tmp\boot-kick.txt echo %date% %time% OO_Security.cmd
>>C:\Platform\Security\oo-security.log echo [%date% %time%] OO_Security.cmd wrapper
powershell.exe -NoLogo -NonInteractive -NoProfile -ExecutionPolicy Bypass -File "C:\Platform\Security\OO_Security.ps1" %*
exit /b 0
