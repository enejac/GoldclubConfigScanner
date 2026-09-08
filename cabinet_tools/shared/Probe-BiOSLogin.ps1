#Requires -Version 5.1
Set-Location 'G:\BiOS'
Add-Type -AssemblyName System.Windows.Forms
foreach ($dll in @('GoldClub.Logging.dll','GoldClub.Interfaces.dll','GoldClub.Settings.dll',
    'LicenseValidator.dll','AWSSDK.Core.dll','AWSSDK.S3.dll','Newtonsoft.Json.dll','QRCoder.dll')) {
    if (Test-Path $dll) { [void][Reflection.Assembly]::LoadFrom((Resolve-Path $dll).Path) }
}
$asm = [Reflection.Assembly]::LoadFrom('G:\BiOS\BiOS2.exe')
$log = 'C:\Platform\Security\bios-probe.log'
function L($m) { Add-Content $log "[$(Get-Date -Format HH:mm:ss.fff)] $m" -Encoding ASCII }
Remove-Item $log -Force -EA SilentlyContinue
$body = 'AB4cOZzI2/KCc+DVFW/vQzyX3fLUkgKCmnId4ylfHdDeO/PSC1BrszAsJqHQiVQnGflitcelI2Bv71DRbpoPL6pos9Xqty5BTPFE5vbscsiiV5899DFUCvOM1uC+JZVEiYUJFAdypm4ohxpWDR1i7jqPs6toCQWh4u55jRFgdWc='
$acType = $asm.GetType('BiOS2.Utils.AccessControl')
$ac = $acType.GetMethod('GetInstance').Invoke($null, @())
$crypter = $asm.GetType('BiOS2.Utils.StringCrypter')
$dec = $crypter.GetMethod('Decrypt')
$loginUrl = [string]$acType.GetMethod('GetLoginUrl').Invoke($ac, @())
L "EncryptPWD len=$($ac.EncryptPWD.Length) loginUrl len=$loginUrl.Length"
foreach ($pwd in @('', 'GST22377', '1232', 'test', 'goldclub', $ac.EncryptPWD, $loginUrl)) {
    try {
        $plain = [string]$dec.Invoke($null, @($body, $pwd))
        if ($plain) {
            L "Decrypt ok pwd=[$pwd] plainLen=$($plain.Length) head=$($plain.Substring(0, [Math]::Min(40, $plain.Length)))"
            $ac.LoginPhrase = $plain
            $v = [bool]$acType.GetMethod('Validate').Invoke($ac, @('449166'))
            L "  Validate449166=$v"
        }
    } catch {
        L "Decrypt fail pwd=[$pwd] $($_.Exception.Message)"
    }
}
# Try AddPin then Validate
try {
    $addPin = $acType.GetMethod('AddPin')
    if ($addPin) {
        $addPin.Invoke($ac, @('Service', '449166'))
        L 'AddPin Service 449166'
        L "Validate449166=$([bool]$acType.GetMethod('Validate').Invoke($ac, @('449166')))"
    }
} catch { L "AddPin err $($_.Exception.Message)" }
$svType = $asm.GetType('BiOS2.Model.SessionValidatorDLL')
$written = $svType.GetMethod('CreateSessionFile').Invoke($null, @(
    [Environment]::MachineName, [DateTimeOffset]::Now, 20, '1232', 'Service', '449166', 'c:/goldclub/bios/License/Session.lic'
))
L "CreateSessionFile after AddPin=$written Session.lic=$([bool](Test-Path 'G:\bios\License\Session.lic'))"
Get-Content $log
