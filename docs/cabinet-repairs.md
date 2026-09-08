# Cabinet repairs

Field-proven fixes for GoldClub EGM cabinet states that stop the game from
starting or from leaving a lock screen. Each fault below is documented with the
symptom you actually see, the root cause, how it was proven, and the manual
procedure — and each one is automated in Config Scanner under
**More → Diagnose & repair cabinet…**.

The automation lives in [`config_scanner/cabinet_repairs.py`](../config_scanner/cabinet_repairs.py).
Every repair has a stable `id` (used by the GUI and tests) listed in its section.

> These repairs act on a **live cabinet** over SMB and WinRM. They never touch
> boot configuration (`bcdboot` / BCD / EFI / registry hives), and never rewrite
> the serial port board maps `layout.json` / `locations.json`. See
> `.cursor/rules/never-touch-goldclub-boot.mdc` and
> `.cursor/rules/never-edit-serialport-layout.mdc`.

## Quick reference

| id | Fault | Symptom on the cabinet | Transport |
|---|---|---|---|
| `slot_licence_placement` | Licence XMLs not next to `OneHand.exe` | `No licence!` / licence login (QR) screen | SMB |
| `aurum_setup_hostname` | `AurumSetup.xml` host block does not match the Windows hostname | `AurumEGM creation error`, NRE in `AurumEGM..ctor` | SMB |
| `mux_sas_com_port` | Ghost MUX device owns COM11 | `Locked by Host. NO SAS COMMUNICATIONS!` | SMB + WinRM |
| `goldclub_boot_tasks` | BitLocker unlock runs on a UAC-filtered token | Black screen after boot, game never starts | SMB + WinRM |
| `slot_ramclear_pending` | Trial blob missing from NVRAM | `RAMCLEAR REQUIRED`, `Trial expired…` | WinRM (destructive) |

---

## `slot_licence_placement` — "No licence!" although the licence is installed

**Symptom.** The game starts but shows `No licence!`, or drops to the licence
login screen with a QR code. This is *not* a Dallas key problem — the Dallas
iButton is read correctly and logged as `Dallas code received` even while this
screen is up.

**Root cause.** `OneHand.exe` resolves licence XMLs **relative to its own
directory**, which is `…\goldclub\slot\`. Installing the pack only into
`…\goldclub\Licenses\` leaves the game with nothing to read. The WIBU stub
`licence.dll` must also sit next to the executable.

**What the repair does.** Mirrors every licence XML found anywhere in the tree
(`Licenses/`, `Licences/`, `config/licences/`) into the three locations the
platform reads, and makes sure `licence.dll` is present beside `OneHand.exe`:

```
<goldclub>\slot\Licence*.xml      <- what OneHand.exe actually reads
<goldclub>\Licence*.xml           <- Bootstrap / older builds
<goldclub>\Licenses\Licence*.xml  <- pack install location
<goldclub>\slot\licence.dll
```

It only ever **copies**, never deletes, and it skips a destination whose bytes
already match. Hash-named Aurum XMLs (`802A33BC….xml`) are treated the same way.

**Related.** To roll a licence back to a snapshot instead, use
**More → Restore slot licence from snapshot…**
([`config_scanner/slot_licence.py`](../config_scanner/slot_licence.py)).

---

## `aurum_setup_hostname` — `AurumEGM creation error` / NullReferenceException

**Symptom.** OneHand throws a `NullReferenceException` inside `AurumEGM..ctor`
and shows an `AurumEGM creation error` dialog. In the Aurum service log:

```
CRIT Exception: CONFIG FOR SASControler1 NOT FOUND!   (at GCMessenger.Init)
```

and nothing listens on port **50011**.

**Root cause.** `services/aurum/config/AurumSetup.xml` contains one `<Network>`
block per host, and `AurumSetup.LoadSetup` selects the block by
`[Environment]::MachineName`. On GST22377 the only block was named `GST20664`
(the overlay identity), so `SelectedNetworkHostName` resolved to `GST22377` with
**no configs attached**. A `hosts` alias is *not* enough — the lookup never
touches DNS.

**Proven with the cabinet's own engine**, before and after:

```powershell
$t = ([Reflection.Assembly]::LoadFrom('G:\services\aurum\bin\lib\GoldClub.Aurum.Engine.dll')).GetTypes() |
    Where-Object Name -eq 'AurumSetup'
$a = [Activator]::CreateInstance($t)
$t.GetMethod('LoadSetup', [Type[]]@([string], $t)).Invoke($null, @('G:\services\aurum\config\AurumSetup.xml', $a))
$a.SelectedNetworkHostName; [bool]$a.Item('SASControler1')
```

**What the repair does.** Rewrites only the host tokens — `NetworkHostName`,
`ServiceURI`, `MessengerURI` — to the cabinet's real Windows hostname, in place,
after writing `AurumSetup.xml.bak-host-<oldname>`. It deliberately leaves the
EGM identity alone: `GCC_ST_20664_01` and `CabinetSerialNumber 20664` stay as
they are, because those are licensing identity, not networking.

Healthy afterwards means **50010** (OneHand GM2AU) and **50011** (Aurum SAS
host) both listening, and `Aurum EGM messenger created and started` in the log.

---

## `mux_sas_com_port` — `Locked by Host. NO SAS COMMUNICATIONS!`

**Symptom.** The game boots to a host lock:

```
Aurum egm state changed [lockerDevice:'communications:1', state:'hostDisabled'
                         message:'NO SAS COMMUNICATIONS!']
Lock item added: OnlineLock
```

A reboot sometimes clears it and sometimes does not, which makes it look
intermittent.

**Root cause — the MUX board does not report a stable USB serial.** A healthy
STM32 VCP derives its serial from the chip's immutable unique ID, so it is
identical on every enumeration. This board's is not, so Windows creates a **new
device node per identity**, each keeping its own COM number. On GST22377 there
were six nodes at the same physical location `Port_#0003.Hub_#0003`:

| serial | COM | present |
|---|---|---|
| `207C39555241` | COM3 | no |
| `206237634741` | COM10 | no |
| `2062375B4741` | **COM11** (`MUX/SAS (COM:11)`) | no |
| `206937794741` | COM12 | no |
| `205E31524B42` | COM13 | no |
| `206139555241` | COM14 | **yes** |

Only the ghost `2062375B4741` ever carried `PortName=COM11` and the `MUX/SAS`
friendly name, and it held COM11 reserved in the COM Name Arbiter. So
`CommCtrlSAS` could not open COM11 and fell back to listening on its control
port **40000** only; the generic `CommCtrl` picked the live board up on COM14
and exposed it at **31400** at the wrong baud; Aurum's `SASControler1` dialled
`localhost:31100`, found nothing, and `LockGameWhenNoComms=true` locked the game.

That also explains the "sometimes a reboot fixes it": it is a one-in-six
lottery on which identity the board happens to enumerate as.

**The configuration was never wrong.** `maintenance\config\serialports.conf`,
`platform\user\init\onlogon\Serial\USBtoSerialPorts.conf` and
`bios\etc\application\CommCtrlSAS\CommControler.ini` all agree on COM11 at
921600. Do **not** "fix" this by editing them, and do not blame
`17-SetSerialPorts.ps1`: `C:\Windows\INF\setupapi.dev.log` shows only five
identities created in fourteen months, all clustered on power events, and the
warm `devcon disable` / `enable` that script performs created none.

**What the repair does** — the sequence proven on 31 Aug 2026, with no reboot:

1. Remove the **non-present** `VID_0483&PID_5740` nodes with `devcon remove`,
   which releases their COM reservations. Refuses to act if no MUX is present,
   never touches the live node, and keeps the documented GoldClub numbers
   (COM3/4/6/7) reserved.
2. Run the stock `17-SetSerialPorts.ps1` so the vendor logic — not ours —
   assigns COM11 and the `MUX/SAS` name to the live node.
3. Stop `GoldClub Serial Communication Gateway SAS`, then
   `GoldClub Serial Communication Gateway`. **This step is what avoids a
   reboot**: while CommCtrl holds the port open, `devcon` can only report
   *"Disabled on reboot … requires reboot to complete"*.
4. `devcon disable` / `enable` the live MUX so the driver re-reads `PortName`.
5. Start both services again.

Verified result:

```
SERIALCOMM \Device\USBSER000 = COM11
CommCtrlSAS listening on 31100 and 40000 (same PID); bogus 31400 gone
127.0.0.1:31100 ESTABLISHED from the Aurum process
```

and OneHand cleared the lock by itself:

```
13:06:11 Lock item removed: OnlineLock
13:06:11 Information item removed: 'Locked by Host. NO SAS COMMUNICATIONS!'
13:06:11 Information item added:   'Unlocked by Host.'
13:06:14 Slot unlocked
13:06:16 'Select A Game'
```

No SAS host had to be added to the lab network — the ghost was the whole fault.

**This is a workaround, not a cure.** The unstable serial is a board-level
defect; the real fix is reflashing or replacing the MUX. The repair makes the
COM assignment deterministic in the meantime, and
`goldclub_boot_tasks` below makes it survive reboots.

Script: [`cabinet_tools/shared/platform-security/Repair-MuxSasPort.ps1`](../cabinet_tools/shared/platform-security/Repair-MuxSasPort.ps1)

---

## `goldclub_boot_tasks` — black screen after boot

**Symptom.** Windows boots, then a black screen. `oo-security.log` shows
`UnlockerDisk` running over and over and `FATAL: G:\Bootstrap.exe missing`.

**Root cause — a privilege problem, not a BitLocker race.** `eshell` launches
the custom shell `OO_Security.ps1` as `goldclub`. That account *is* in the
administrators group, which is why this looks like it should work, but the
shell's token reports:

```
BUILTIN\Administrators   Alias   S-1-5-32-544   Group used for deny only
```

BitLocker unlock of a data volume needs a real admin token, so
`UnlockerDisk.exe` **exits 0 and does nothing**. On the 12:11 boot the shell
retried 18 times over 8 minutes and never unlocked `G:`; a single elevated run
unlocked it in about 5 seconds. Confirmed with a controlled pair of scheduled
tasks: `/RL LIMITED` gives `elevated=False` and the deny-only group, `/RL
HIGHEST` gives `elevated=True`.

Adding more retries to the shell cannot help. The work has to run as SYSTEM.

**What the repair does.** Stages the three scripts to `C:\Platform\Security\`
over SMB and runs `Install-GoldClubBootTasks.ps1` elevated, which registers two
`/SC ONSTART /RU SYSTEM /RL HIGHEST` tasks:

| Task | Script | Job |
|---|---|---|
| `GoldClub-Unlock-Volume` | `Unlock-GoldClubVolume.ps1` | Unlock the BitLocker `G:` volume |
| `GoldClub-Clear-MuxGhosts` | `Clear-MuxGhostPorts.ps1` | Drop MUX ghosts before `17-SetSerialPorts` |

`devcon.exe` is staged to `C:\Platform\Security\` as well, because `G:` is still
locked when the MUX task runs. `pnputil` on 1809 (17763) has no
`/remove-device`, so devcon is required.

Two traps that these scripts have to keep respecting:

- They must be **pure ASCII**. They ship without a BOM, so PowerShell 5.1 reads
  them as ANSI, and one em dash in a comment is enough to break the parse — a
  copy deployed with 12 non-ASCII bytes produced 11 parse errors and would have
  black-screened the next boot. Guarded by
  `tests/test_onlogon_totalcmd.py::test_boot_scripts_are_ascii_for_powershell_51`.
- The lab `onlogon.ps1` logs to `G:\var\log\onlogon-lab.log`, never
  `onlogon.log`. The stock chain writes the latter with `Tee-Object`, which
  truncates, so sharing the file silently wipes lines.

**Boot order in `OO_Security.ps1`.** Unlock `G:` (waiting on the SYSTEM task),
then `G:\Bootstrap.exe` as the single unconditional game start, then
`Start-LabDesktop.ps1 -PollForUsb` asynchronously for USB extras, and only as a
fallback after 180 s with no game process, `Start-GoldClubHardware.ps1` +
`onlogon.ps1 -StackOnly`. Do not start the lab stack alongside Bootstrap — that
runs every step twice and races `17-SetSerialPorts` against `90-StartServices`.

---

## `slot_ramclear_pending` — `RAMCLEAR REQUIRED` (destructive)

**Symptom.** After a licence change, OneHand raises
`Object reference not set… RAMCLEAR REQUIRED` and
`Trial expired with trial type ErrorRegistryDataNotFound`.

**Root cause.** OneHand's trial state is a blob in **NVRAM** (which the platform
logs call "registry"), keyed to a hardware fingerprint. Changing the licence
invalidates it. This is a slot mechanism and has nothing to do with the roulette
`ERROR 30 / 99` keypad trial — do not go looking for `RouletteActivate.dat` or
roll the clock back on a slot machine.

**What the repair does.** Runs the vendor maintenance task, without `-nested` so
the runner builds its own `PSModulePath`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File G:\bin\RunManteinanceTasks.1.ps1 -path G:\maintenance\tasks\ramclear\
```

That backs up `slot\var`, aurum state and `bios\etc` to
`var\state\maintenance\ramclear\backup\*.7z`, then empties `slot\var`,
`var\state\OneHand`, `var\state\goldclub.aurum.services` and
`services\aurum\var`. It leaves `Licenses\`, `licence.dll` and
`HardwareConfig.xml` alone.

Because it clears meters, the GUI marks this repair **destructive**: it is never
included in "repair everything" and needs its own confirmation.

`begin-ramclear.cmd` only drops the marker
`var\state\maintenance\invoke-task-ramclear` and reboots; the consumer is stock
`05-04-CheckForRamClear.ps1`, which runs as part of the `Bootstrap.exe` chain.

**Re-apply the Dallas key afterwards if `HardwareConfig.xml` was replaced.** The
physical iButton on GST22377 is `01D68A721B000019`, stored in
`slot\themes\HardwareConfig.xml` under `DallasKeySettings/Permissions` as
`Service` with `Unlock=true`. `0100000000000282` is the shipped `IGTKeyAudit`
placeholder, not the stick.

---

## Adding a new repair

1. Implement `diagnose` / `repair` in
   [`config_scanner/cabinet_repairs.py`](../config_scanner/cabinet_repairs.py)
   and append a `CabinetRepair` to `REPAIRS`.
2. If it needs a cabinet-side PowerShell script, put it under
   `cabinet_tools/shared/platform-security/`, keep it **pure ASCII**, and add it
   to `ConfigScanner.spec` `datas` so it ships in the exe.
3. Gate it with `game_kinds` (`("slot",)`, `("roulette",)` or `None` for any) —
   the GUI hides repairs that do not apply to the detected profile.
4. Set `destructive=True` for anything that clears meters or state.
5. Add a test to `tests/test_cabinet_repairs.py`.
