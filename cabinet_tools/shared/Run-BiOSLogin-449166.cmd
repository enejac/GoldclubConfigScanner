@echo off
powershell.exe -NoProfile -Sta -ExecutionPolicy Bypass -File C:\Platform\Security\Invoke-BiOSQrLogin.ps1 -Role Service -LoginPin 449166 -LoginBody "AB4cOZzI2/KCc+DVFW/vQzyX3fLUkgKCmnId4ylfHdDeO/PSC1BrszAsJqHQiVQnGflitcelI2Bv71DRbpoPL6pos9Xqty5BTPFE5vbscsiiV5899DFUCvOM1uC+JZVEiYUJFAdypm4ohxpWDR1i7jqPs6toCQWh4u55jRFgdWc=" -PinPollSeconds 0
