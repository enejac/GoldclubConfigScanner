#Requires -Version 5.1
# STA thread: spin AccessControlForm briefly to run CreateQR and read Pins.
$log = 'C:\Platform\Security\bios-fetch-pins.log'
function L([string]$m) { Add-Content $log "[$(Get-Date -Format HH:mm:ss.fff)] $m" -Encoding ASCII }
try {
    if (Test-Path $log) { Remove-Item $log -Force }
    L 'start'
    Set-Location 'G:\BiOS'
    Add-Type -AssemblyName System.Windows.Forms
    foreach ($dll in @('GoldClub.Logging.dll','GoldClub.Interfaces.dll','GoldClub.Settings.dll',
        'LicenseValidator.dll','AWSSDK.Core.dll','AWSSDK.S3.dll','Newtonsoft.Json.dll','QRCoder.dll',
        'MultiHardware.dll','GoldClub.HW.SubSysClient.dll')) {
        if (Test-Path $dll) { [void][Reflection.Assembly]::LoadFrom((Resolve-Path $dll).Path) }
    }
    $asm = [Reflection.Assembly]::LoadFrom('G:\BiOS\BiOS2.exe')
    $formType = $asm.GetType('BiOS2.AccessControlForm')
    $form = [Activator]::CreateInstance($formType)
    L 'form created'
    $createQr = $formType.GetMethod('CreateQR', [Reflection.BindingFlags]'Instance,Public,NonPublic')
    if ($createQr) {
        $createQr.Invoke($form, @())
        L 'CreateQR invoked'
    }
    $acType = $asm.GetType('BiOS2.Utils.AccessControl')
    $ac = $acType.GetMethod('GetInstance').Invoke($null, @())
    L "phrase=$($ac.LoginPhrase) pins=$($ac.Pins.Count)"
    foreach ($kv in $ac.Pins.GetEnumerator()) {
        L "PIN $($kv.Key)=$([string]$kv.Value)"
    }
    $form.Dispose()
    L 'done'
} catch {
    L "ERR $($_.Exception.Message)"
    exit 1
}
