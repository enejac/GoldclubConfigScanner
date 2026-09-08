#Requires -Version 5.1
<#
  BiOS2 QR session login (session 1).
  Set LoginPhrase from QR body, Validate PIN, write Session.lic via CreateSessionFile.
#>
param(
    [ValidateSet('Service','Operator','SuperUser')]
    [string]$Role = 'Service',
    [string]$LoginPin = '',
    [string]$LoginBody = '',
    [int]$PinPollSeconds = 45,
    [string]$LogPath = 'C:\Platform\Security\bios-auto-login.log'
)

function L([string]$m) { Add-Content -LiteralPath $LogPath -Value "[$(Get-Date -Format 'HH:mm:ss.fff')] $m" -Encoding ASCII }

try {
    if (Test-Path $LogPath) { Remove-Item $LogPath -Force }
    L "START role=$Role"
    Add-Type -AssemblyName System.Windows.Forms,System.Drawing
    Set-Location 'G:\BiOS'
    foreach ($dll in @(
        'GoldClub.Logging.dll','GoldClub.Interfaces.dll','GoldClub.Settings.dll',
        'LicenseValidator.dll','AWSSDK.Core.dll','AWSSDK.S3.dll','Newtonsoft.Json.dll','QRCoder.dll'
    )) { if (Test-Path $dll) { [void][Reflection.Assembly]::LoadFrom((Resolve-Path $dll).Path) } }

    $asm = [Reflection.Assembly]::LoadFrom('G:\BiOS\BiOS2.exe')
    $acType = $asm.GetType('BiOS2.Utils.AccessControl')
    $svType = $asm.GetType('BiOS2.Model.SessionValidatorDLL')
    $ac = $acType.GetMethod('GetInstance').Invoke($null, @())

    if ($LoginBody) {
        $ac.LoginPhrase = $LoginBody.Trim()
        L "LoginPhrase set len=$($ac.LoginPhrase.Length)"
    } else {
        $formType = $asm.GetType('BiOS2.AccessControlForm')
        if ($formType) {
            try {
                $form = [Activator]::CreateInstance($formType)
                $createQr = $formType.GetMethod('CreateQR', [Reflection.BindingFlags]'Instance,Public,NonPublic')
                if ($createQr) {
                    $createQr.Invoke($form, @())
                    L "CreateQR invoked phrase len=$($ac.LoginPhrase.Length)"
                }
                $form.Dispose()
            } catch {
                L "CreateQR skip: $($_.Exception.Message)"
            }
        }
    }

    $pin = $null
    if ($LoginPin) {
        $pin = $LoginPin.Trim()
        L "Using supplied PIN len=$($pin.Length)"
    } else {
        $deadline = (Get-Date).AddSeconds($PinPollSeconds)
        while ((Get-Date) -lt $deadline -and -not $pin) {
            $ac = $acType.GetMethod('GetInstance').Invoke($null, @())
            if ($ac.Pins -and $ac.Pins.Count -gt 0) {
                L "Pins=$($ac.Pins.Count)"
                foreach ($kv in $ac.Pins.GetEnumerator()) {
                    $p = ([string]$kv.Value).Trim()
                    L "  role=$($kv.Key) pin=$p"
                    if ([string]$kv.Key -eq $Role) {
                        $ok = $acType.GetMethod('Validate').Invoke($ac, @($p))
                        L "Validate($p)=$ok"
                        if ($ok) { $pin = $p; break }
                    }
                }
            }
            Start-Sleep -Seconds 2
        }
    }

    if (-not $pin) {
        L 'No PIN available'
        exit 2
    }

    $okPin = $acType.GetMethod('Validate').Invoke($ac, @($pin))
    L "Validate($pin)=$okPin"
    if (-not $okPin) {
        L 'PIN rejected for current LoginPhrase (QR may have rotated)'
        exit 3
    }

    $machine = [Environment]::MachineName
    $serial = [string]$ac.SerialNumber
    if ([string]::IsNullOrWhiteSpace($serial)) { $serial = '1232' }
    L "Serial=$serial Machine=$machine"

    $sessionPath = 'c:/goldclub/bios/License/Session.lic'
    $written = $svType.GetMethod('CreateSessionFile').Invoke($null, @(
        $machine, [DateTimeOffset]::Now, 20, $serial, $Role, $pin, $sessionPath
    ))
    L "CreateSessionFile=$written"

    Start-Sleep -Milliseconds 500
    $lic = 'G:\bios\License\Session.lic'
    if ((Test-Path $lic) -and $written) {
        L 'SUCCESS Session.lic via API'
        exit 0
    }

    # SendKeys only if BiOS2 has a visible window
    $bios = Get-Process BiOS2 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($bios -and $bios.MainWindowHandle -ne [IntPtr]::Zero) {
        Add-Type @"
using System; using System.Runtime.InteropServices;
public class W32 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
"@
        L 'SendKeys fallback'
        [void][W32]::SetForegroundWindow($bios.MainWindowHandle)
        Start-Sleep -Milliseconds 500
        foreach ($ch in $pin.ToCharArray()) {
            [Windows.Forms.SendKeys]::SendWait($ch)
            Start-Sleep -Milliseconds 120
        }
        [Windows.Forms.SendKeys]::SendWait('{ENTER}')
        Start-Sleep -Seconds 5
        if (Test-Path $lic) { L 'SUCCESS Session.lic via SendKeys'; exit 0 }
    } else {
        L 'BiOS2 window not visible; API path only'
    }

    if (Test-Path $lic) { L 'SUCCESS Session.lic exists'; exit 0 }
    L 'FAILED'
    exit 1
}
catch {
    L "ERR $($_.Exception.Message)"
    exit 1
}
