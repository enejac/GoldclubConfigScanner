# onlogon.ps1 - self-contained (no helper files required). Copy via CopyOnlogon.bat to C:\goldclub\platform\user\init\
# Stock OO_Security passes -WorkingDirectory as a *script* argument. Accept it
# so onlogon does not die before Start-StockGoldClubGame (black screen).
param(
    [switch]$StackOnly,
    [string]$WorkingDirectory
)
$ErrorActionPreference = 'Continue'

function Write-OnlogonRunLog {
    param([string]$Message)
    $line = "[$(Get-Date -Format o)] $Message"
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    $paths = New-Object System.Collections.Generic.List[string]
    if ($PSScriptRoot) { [void]$paths.Add((Join-Path $PSScriptRoot 'onlogon-run.log')) }
    [void]$paths.Add('C:\Platform\Security\onlogon.log')
    try {
        $gd = [IO.DriveInfo]::new('G:\')
        if ($gd.IsReady -and [IO.File]::Exists('G:\Bootstrap.exe')) {
            # NOT onlogon.log: the stock chain Tee-Objects that path, and Tee
            # truncates, so our timestamped lines were being wiped by whichever
            # of the two finished last. Keeping them apart is what makes it
            # possible to tell which boot a serial-port entry came from.
            [void]$paths.Add('G:\var\log\onlogon-lab.log')
        }
    }
    catch {}
    if ($script:UsbRoot) {
        [void]$paths.Add((Join-Path $script:UsbRoot 'onlogon-run.log'))
        $usbScripts = Join-Path $script:UsbRoot 'usb_scripts'
        if (Test-Path -LiteralPath $usbScripts) { [void]$paths.Add((Join-Path $usbScripts 'onlogon-run.log')) }
    }
    foreach ($logPath in ($paths | Select-Object -Unique)) {
        try {
            $dir = Split-Path -Parent $logPath
            if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            [IO.File]::AppendAllText($logPath, $line + [Environment]::NewLine, $utf8)
        } catch {}
    }
    Write-Host $line
}

Write-OnlogonRunLog '========== ONLOGON RUN START =========='
Write-OnlogonRunLog "script=$PSCommandPath psscriptroot=$PSScriptRoot user=$env:USERDOMAIN\$env:USERNAME computer=$env:COMPUTERNAME"

Get-Module | Where-Object -Property 'Name' -Like 'goldclub.*' | Remove-Module
Write-OnlogonRunLog 'removed goldclub.* modules'

function Test-GoldClubVolumeReady {
    try {
        $d = [IO.DriveInfo]::new('G:\')
        return [bool]($d.IsReady -and [IO.File]::Exists('G:\Bootstrap.exe'))
    }
    catch {
        return $false
    }
}

$initDir = $PSScriptRoot
if (Test-GoldClubVolumeReady -and (Test-Path -LiteralPath 'G:\platform\user\init\init.json')) {
    $initDir = 'G:\platform\user\init'
}
$initModule = Join-Path $initDir '..\..\bin\lib\powershell\goldclub.init.1'
$initJson = Join-Path $initDir 'init.json'
Write-OnlogonRunLog "init module=$initModule exists=$(Test-Path -LiteralPath $initModule)"
Write-OnlogonRunLog "init json=$initJson exists=$(Test-Path -LiteralPath $initJson)"

$script:InitPlatformOk = $false
try {
    Write-OnlogonRunLog 'Initialize-Platform: starting'
    Import-Module $initModule -ErrorAction Stop
    goldclub.init.1\Initialize-Platform -taskToRun ($initDir + '/onlogon') -configFile $initJson -ErrorAction Stop -Verbose
    $script:InitPlatformOk = $true
    Write-OnlogonRunLog 'Initialize-Platform: OK'
}
catch {
    Write-OnlogonRunLog "Initialize-Platform: FAILED - $($_.Exception.Message)"
}

function Invoke-PendingRamClear {
    # Stock consumer is platform\user\init\onlogon\05-04-CheckForRamClear.ps1. It never
    # runs on this image: goldclub.init.1 is absent, Initialize-Platform bails, and the
    # whole stock onlogon.d chain is skipped. Without this, begin-ramclear.cmd only
    # reboots and OneHand keeps raising "RAMCLEAR REQUIRED" after a licence change.
    if (-not (Test-GoldClubVolumeReady)) { return }
    $marker = 'G:\var\state\maintenance\invoke-task-ramclear'
    if (-not (Test-Path -LiteralPath $marker)) { return }
    $runner = 'G:\bin\RunManteinanceTasks.1.ps1'
    $tasks = 'G:\maintenance\tasks\ramclear\'
    if (-not ((Test-Path -LiteralPath $runner) -and (Test-Path -LiteralPath $tasks))) {
        Write-OnlogonRunLog 'ramclear: marker present but maintenance tasks missing'
        return
    }
    Write-OnlogonRunLog 'ramclear: marker found - running maintenance tasks'
    try {
        Remove-Item -LiteralPath $marker -Force -ErrorAction Stop
    }
    catch {
        Write-OnlogonRunLog "ramclear: marker remove failed: $($_.Exception.Message)"
        return
    }
    # Deliberately not -nested: the runner must set PSModulePath / Path itself so the
    # tasks find Import-Ini, UpdateFactoryDefaults.1 and 7za.exe.
    try {
        $proc = Start-Process -FilePath 'powershell.exe' `
            -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $runner, '-path', $tasks `
            -WorkingDirectory 'G:\bin' -PassThru -WindowStyle Hidden -ErrorAction Stop
        if (-not $proc.WaitForExit(300000)) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Write-OnlogonRunLog 'ramclear: timeout after 300s'
        }
        else {
            Write-OnlogonRunLog ("ramclear: done exit={0}" -f $proc.ExitCode)
        }
    }
    catch {
        Write-OnlogonRunLog "ramclear: failed: $($_.Exception.Message)"
    }
}

function Test-IsGoldClubGameVolume {
    param([string]$Root)
    $base = $Root.TrimEnd('\')
    return (
        (Test-Path -LiteralPath "$base\slot\OneHand.exe") -or
        (Test-Path -LiteralPath "$base\ruleta\Ruleta.exe")
    )
}

function Test-GoldClubGameRunning {
    return [bool]@(Get-Process -Name 'Bootstrap', 'game-start', 'Start-Game', 'OneHand', 'HIH', 'Ruleta' -ErrorAction SilentlyContinue)
}

function Start-StockGoldClubGame {
    # Slot images often ship without goldclub.init.1. USB extras must not be
    # required to get a game on screen.
    if (Test-GoldClubGameRunning) {
        Write-OnlogonRunLog 'Game already running - skip stock start'
        return
    }
    $candidates = @(
        'G:\Bootstrap.exe',
        'G:\slot\game-start.exe',
        'G:\bin\HIH.exe',
        'G:\bin\Start-Game.exe',
        'G:\bin\game-start.exe'
    )
    foreach ($exe in $candidates) {
        if (Test-Path -LiteralPath $exe) {
            Write-OnlogonRunLog "Starting stock game: $exe"
            try {
                Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe) -ErrorAction Stop
            }
            catch {
                Write-OnlogonRunLog "stock game start failed: $($_.Exception.Message)"
            }
            return
        }
    }
    Write-OnlogonRunLog 'Stock game launcher not found'
}

function Get-GoldClubServicesRoot {
    foreach ($root in @('G:\Services', 'G:\services', 'C:\Services')) {
        if (Test-Path -LiteralPath (Join-Path $root 'LogDaemon\GoldClub.Logging.LogDaemon.exe')) {
            return $root
        }
    }
    return 'G:\services'
}

function Test-NamedGoldClubService {
    param([string]$Name)
    $svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($svc) { return $svc }
    return (Get-Service -DisplayName $Name -ErrorAction SilentlyContinue)
}

function Install-GoldClubExeService {
    param(
        [string]$ExePath,
        [string]$InstallArg = '--install'
    )
    if (-not (Test-Path -LiteralPath $ExePath)) {
        Write-OnlogonRunLog "stack install skip (missing): $ExePath"
        return
    }
    $dir = Split-Path -Parent $ExePath
    Write-OnlogonRunLog "stack install: $ExePath $InstallArg"
    try {
        $p = Start-Process -FilePath $ExePath -ArgumentList $InstallArg -WorkingDirectory $dir -PassThru -WindowStyle Hidden -ErrorAction Stop
        if (-not $p.WaitForExit(12000)) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            Write-OnlogonRunLog "stack install timeout: $ExePath"
        }
        else {
            Write-OnlogonRunLog ("stack install exit={0}" -f $p.ExitCode)
        }
    }
    catch {
        Write-OnlogonRunLog "stack install failed: $($_.Exception.Message)"
    }
}

function Start-NamedGoldClubService {
    param([string]$Name)
    $svc = Test-NamedGoldClubService -Name $Name
    if (-not $svc) {
        Write-OnlogonRunLog "stack service missing: $Name"
        return
    }
    if ($svc.Status -eq 'Running') {
        Write-OnlogonRunLog "stack already Running: $($svc.Name)"
        return
    }
    try {
        Start-Service -InputObject $svc -ErrorAction Stop
        Write-OnlogonRunLog "stack started: $($svc.Name)"
    }
    catch {
        Write-OnlogonRunLog "stack start failed $($svc.Name): $($_.Exception.Message)"
    }
}

function Start-SlotFullStack {
    # Slot GOLDCLUB on a Windows image that never had services registered:
    # OneHand then dies in AurumEGM..ctor (empty seed + no Aurum/CommCtrl/HW).
    # Use G:\ only - C:\goldclub is a BitLocker junction and hangs if USB stole G:.
    Write-OnlogonRunLog 'Start-SlotFullStack: begin'
    if (-not (Test-GoldClubVolumeReady)) {
        Write-OnlogonRunLog 'Start-SlotFullStack: G: GOLDCLUB not ready - skip hardware'
        return
    }
    foreach ($dir in @(
            'C:\tmp',
            'G:\var\state\OneHand\Aurum',
            'G:\var\state\goldclub.aurum.services\GCMessenger\gm2au',
            'G:\var\state\goldclub.aurum.services\GCMessenger\SASControler1',
            'G:\var\state\maintenance',
            'G:\services\aurum\config\gm2au',
            'G:\var\run\tmp'
        )) {
        try {
            if (-not (Test-Path -LiteralPath $dir)) {
                New-Item -ItemType Directory -Path $dir -Force | Out-Null
                Write-OnlogonRunLog "stack mkdir $dir"
            }
        }
        catch {
            Write-OnlogonRunLog "stack mkdir failed $dir : $($_.Exception.Message)"
        }
    }
    foreach ($seedName in @('seedProvider_1', 'seedProvider_2')) {
        $src = Join-Path 'G:\bin\AurumConfigurer' $seedName
        $dst = Join-Path 'G:\var\state\goldclub.aurum.services' $seedName
        if ((Test-Path -LiteralPath $src) -and -not (Test-Path -LiteralPath $dst)) {
            try {
                Copy-Item -LiteralPath $src -Destination $dst -Force
                Write-OnlogonRunLog "stack copied $seedName"
            }
            catch {
                Write-OnlogonRunLog "stack seed copy failed: $($_.Exception.Message)"
            }
        }
    }

    $psn = 'G:\var\state\maintenance\ProductSerialNumber.conf'
    if (-not (Test-Path -LiteralPath $psn)) {
        $machine = $env:COMPUTERNAME
        $setup = 'G:\services\aurum\config\AurumSetup.xml'
        if (Test-Path -LiteralPath $setup) {
            $raw = [IO.File]::ReadAllText($setup)
            if ($raw -match '<NetworkHostName>([^<]+)</NetworkHostName>') { $machine = $Matches[1].Trim() }
        }
        $serial = ($machine -replace '\D', '')
        if (-not $serial) { $serial = '0' }
        $text = @"
[Config]
ProductKind: ST
ProductSerialNumber: $serial
ProductPart: -
MachineName: $machine
"@
        try {
            [IO.File]::WriteAllText($psn, $text, [Text.UTF8Encoding]::new($false))
            Write-OnlogonRunLog "stack wrote $psn MachineName=$machine"
        }
        catch {
            Write-OnlogonRunLog "stack psn failed: $($_.Exception.Message)"
        }
    }

    $setup = 'G:\services\aurum\config\AurumSetup.xml'
    if (Test-Path -LiteralPath $setup) {
        $raw = [IO.File]::ReadAllText($setup)
        if ($raw -match '<NetworkHostName>([^<]+)</NetworkHostName>') {
            $aurumHost = $Matches[1].Trim()
            if ($aurumHost -and ($env:COMPUTERNAME -ine $aurumHost)) {
                $hostsFile = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
                try {
                    $cur = [IO.File]::ReadAllText($hostsFile)
                    if ($cur -notmatch ("(?m)^\s*127\.0\.0\.1\s+$([regex]::Escape($aurumHost))\b")) {
                        [IO.File]::AppendAllText($hostsFile, "`r`n127.0.0.1 $aurumHost`r`n")
                        Write-OnlogonRunLog "stack hosts 127.0.0.1 $aurumHost (AurumSetup host != $($env:COMPUTERNAME))"
                    }
                }
                catch {
                    Write-OnlogonRunLog "stack hosts failed: $($_.Exception.Message)"
                }
            }
        }
    }

    $svcRoot = Get-GoldClubServicesRoot
    Write-OnlogonRunLog "stack services root=$svcRoot"

    if (-not (Test-NamedGoldClubService -Name 'GoldClub.Logging.LogDaemon')) {
        Install-GoldClubExeService -ExePath (Join-Path $svcRoot 'LogDaemon\GoldClub.Logging.LogDaemon.exe')
    }
    if (-not (Test-NamedGoldClubService -Name 'GoldClub Serial Communication Gateway')) {
        Install-GoldClubExeService -ExePath (Join-Path $svcRoot 'CommCtrl\XYNTService.exe') -InstallArg '-i'
    }
    if (-not (Test-NamedGoldClubService -Name 'GoldClub Serial Communication Gateway SAS')) {
        Install-GoldClubExeService -ExePath (Join-Path $svcRoot 'CommCtrlSAS\XYNTService.exe') -InstallArg '-i'
    }
    if (-not (Test-NamedGoldClubService -Name 'GoldClub Hardware Subsystem')) {
        $hw = Join-Path $svcRoot 'HWSubsys\hwsubsys.exe'
        if (-not (Test-Path -LiteralPath $hw)) { $hw = Join-Path $svcRoot 'HWSubsys\HWSubsys.exe' }
        Install-GoldClubExeService -ExePath $hw
    }
    if (-not (Test-NamedGoldClubService -Name 'GoldClub.Aurum.Services')) {
        $bin = 'G:\services\aurum\bin\GoldClub.Aurum.Services.exe'
        Write-OnlogonRunLog 'stack sc create GoldClub.Aurum.Services (--install is modal / rolls back)'
        cmd /c "sc.exe create GoldClub.Aurum.Services binPath= `"$bin`" start= auto DisplayName= `"GoldClub.Aurum.Services`"" | ForEach-Object { Write-OnlogonRunLog "sc: $_" }
    }

    foreach ($name in @(
            'GoldClub.Logging.LogDaemon',
            'GoldClub Serial Communication Gateway',
            'GoldClub Serial Communication Gateway SAS',
            'GoldClub Hardware Subsystem',
            'GoldClub.Aurum.Services'
        )) {
        Start-NamedGoldClubService -Name $name
        Start-Sleep -Seconds 1
    }
    # goldclub's filtered token cannot Start-Service. SYSTEM task can.
    Write-OnlogonRunLog 'Start-SlotFullStack: kicking GoldClub-Ensure-HwStack'
    cmd /c 'schtasks /Run /TN "GoldClub-Ensure-HwStack" /I' 2>&1 | ForEach-Object {
        Write-OnlogonRunLog ("ensure-hw: " + $_)
    }
    Ensure-SlotDallasKey
    Write-OnlogonRunLog 'Start-SlotFullStack: end'
}

function Ensure-SlotDallasKey {
    # Physical iButton on GST22377 / 10.0.0.111 (SlotLog: Dallas code received).
    # HardwareConfig shipped 0100000000000282 (IGTKeyAudit placeholder only).
    $code = '01D68A721B000019'
    $hw = $null
    foreach ($cand in @(
            'G:\slot\themes\HardwareConfig.xml',
            'G:\Slot\themes\HardwareConfig.xml'
        )) {
        if (Test-Path -LiteralPath $cand) { $hw = $cand; break }
    }
    if (-not $hw) {
        Write-OnlogonRunLog 'Dallas: HardwareConfig.xml missing'
        return
    }
    try {
        $raw = [IO.File]::ReadAllText($hw)
    }
    catch {
        Write-OnlogonRunLog "Dallas: read failed: $($_.Exception.Message)"
        return
    }
    if ($raw -match [regex]::Escape($code)) {
        Write-OnlogonRunLog "Dallas: $code already in HardwareConfig"
        return
    }
    $block = @"
      <DallasKey>
        <Code>$code</Code>
        <Groups>
          <string>Service</string>
        </Groups>
        <Unlock>true</Unlock>
      </DallasKey>
"@
    $updated = $null
    $hit = [regex]::Match($raw, '(?s)(<DallasKeySettings>.*?<Permissions>)')
    if ($hit.Success) {
        $updated = $raw.Insert($hit.Index + $hit.Length, "`r`n" + $block)
    }
    if (-not $updated) {
        Write-OnlogonRunLog 'Dallas: Permissions node not found'
        return
    }
    try {
        $bak = $hw + '.bak-dallas'
        if (-not (Test-Path -LiteralPath $bak)) {
            [IO.File]::Copy($hw, $bak, $false)
        }
        [IO.File]::WriteAllText($hw, $updated, [Text.UTF8Encoding]::new($false))
        Write-OnlogonRunLog "Dallas: wrote $code Service/Unlock into HardwareConfig"
    }
    catch {
        Write-OnlogonRunLog "Dallas: write failed: $($_.Exception.Message)"
    }
}

function Get-GoldClubUsbRoot {
    # Lab USB stick only. Never C: / G: (GOLDCLUB). Skip DriveInfo that is not
    # IsReady - Test-Path on a not-ready USB letter hangs onlogon forever.
    foreach ($d in [IO.DriveInfo]::GetDrives()) {
        try {
            if (-not $d.IsReady) { continue }
            $root = $d.Name.TrimEnd('\')
            if ($root -in @('C:', 'G:')) { continue }
            if ($d.DriveType -notin @('Removable', 'Fixed')) { continue }
            if (Test-IsGoldClubGameVolume -Root $root) { continue }
            foreach ($rel in @(
                    'CopyOnlogon.bat',
                    'TeamViewerPortable\TeamViewer.exe',
                    'totalcmd\TOTALCMD64.EXE',
                    'totalcmd\TOTALCMD.EXE',
                    'TeamViewer_LoginBackup\restore_tv_login.cmd'
                )) {
                if (Test-Path -LiteralPath (Join-Path $root $rel)) { return $root }
            }
        }
        catch {}
    }
    return $null
}

function Resolve-UsbShareBatch {
    param([string]$Root)
    foreach ($name in @('share.bat', '_share.bat')) {
        $path = Join-Path $Root $name
        if (Test-Path -LiteralPath $path) { return $path }
    }
    return $null
}

function Test-TotalCommanderRunning {
    return [bool]@(Get-Process -Name 'TOTALCMD', 'TOTALCMD64' -ErrorAction SilentlyContinue)
}

function Start-TotalCommanderFromUsb {
    param([string]$UsbRoot)
    if (Test-TotalCommanderRunning) {
        Write-OnlogonRunLog 'Total Commander already running - skip second instance'
        return
    }
    $candidates = @()
    if ($UsbRoot) {
        $candidates += (Join-Path $UsbRoot 'totalcmd\TOTALCMD64.EXE')
        $candidates += (Join-Path $UsbRoot 'totalcmd\TOTALCMD.EXE')
    }
    foreach ($exe in $candidates) {
        if ($exe -and (Test-Path -LiteralPath $exe)) {
            Write-OnlogonRunLog "Starting Total Commander: $exe"
            Start-Process -FilePath $exe -ArgumentList '/O' -WorkingDirectory (Split-Path -Parent $exe) -ErrorAction SilentlyContinue
            return
        }
    }
    Write-OnlogonRunLog 'Total Commander not found'
}

if ($StackOnly) {
    Invoke-PendingRamClear
    Start-SlotFullStack
    Write-OnlogonRunLog 'StackOnly - skip game and USB extras'
    Write-OnlogonRunLog '========== ONLOGON RUN END =========='
    return
}
# RAM clear before the stack: 01-StopServices stops every goldclub service.
Invoke-PendingRamClear
# Hardware stack before game (OneHand AurumEGM NRE on empty Slot images).
Start-SlotFullStack
Start-StockGoldClubGame

$script:UsbRoot = Get-GoldClubUsbRoot
$UsbRoot = $script:UsbRoot
if (-not $UsbRoot) {
    Write-OnlogonRunLog 'USB root not found - stock onlogon (game start without USB extras)'
}
else {
    Write-OnlogonRunLog "USB root: $UsbRoot"

    $tvCmd = Join-Path $UsbRoot 'TeamViewer_LoginBackup\restore_tv_login.cmd'
    if (Test-Path -LiteralPath $tvCmd) {
        Write-OnlogonRunLog 'before restore_tv_login'
        try {
            $tvProc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "`"$tvCmd`"" -PassThru
            if ($tvProc) { Wait-Process -Id $tvProc.Id -Timeout 90 -ErrorAction Stop }
            $tvExit = if ($tvProc) { $tvProc.ExitCode } else { 'N/A' }
            Write-OnlogonRunLog "after restore_tv_login exit=$tvExit"
        }
        catch {
            Write-OnlogonRunLog "restore_tv_login failed: $($_.Exception.Message)"
            if ($tvProc -and -not $tvProc.HasExited) { Stop-Process -Id $tvProc.Id -Force -ErrorAction SilentlyContinue }
        }
    }
    $fallback = Join-Path $UsbRoot 'TeamViewerPortable\TeamViewer.exe'
    if (Test-Path -LiteralPath $fallback) {
        if (-not (Get-Process -Name 'TeamViewer' -ErrorAction SilentlyContinue)) {
            Write-OnlogonRunLog "TeamViewer: $fallback"
            Start-Process -FilePath $fallback -WorkingDirectory (Split-Path -Parent $fallback) -ErrorAction SilentlyContinue
        }
    }

    $shareBat = Resolve-UsbShareBatch -Root $UsbRoot
    if ($shareBat) {
        Write-OnlogonRunLog "before share ($shareBat)"
        try {
            $shareProc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "`"$shareBat`" -nopause" -PassThru
            if ($shareProc) { Wait-Process -Id $shareProc.Id -Timeout 30 -ErrorAction Stop }
            $shareExit = if ($shareProc) { $shareProc.ExitCode } else { 'N/A' }
            Write-OnlogonRunLog "after share exit=$shareExit"
        }
        catch { Write-OnlogonRunLog "share failed: $($_.Exception.Message)" }
    }
    else { Write-OnlogonRunLog 'share skipped: share.bat / _share.bat not found' }

    if (Test-Path -LiteralPath 'G:\') {
        cmd /c 'net share slot=G:\ /grant:everyone,FULL' 2>&1 | ForEach-Object { Write-OnlogonRunLog "share-cmd: $_" }
    }
    cmd /c 'net user test' 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { cmd /c 'net user test test /add' 2>&1 | ForEach-Object { Write-OnlogonRunLog "user: $_" } }
    cmd /c 'net localgroup administrators test /add' 2>&1 | ForEach-Object { Write-OnlogonRunLog "admin: $_" }

    Start-TotalCommanderFromUsb -UsbRoot $UsbRoot
}

Write-OnlogonRunLog '========== ONLOGON RUN END =========='
