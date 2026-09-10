# GoldClub Config Scanner

Standalone SHA1 snapshot / compare / restore tool for GoldClub EGM config.

Forked from [GoldclubLogInvestigator](https://github.com/enejac/GoldclubLogInvestigator) at `d355681` so scanner work can diverge from the log-triage app. Roulette restore is proven; the next structural work is slot-EGM auto-adapt (profiles, scan roots, OneHand vs Ruleta).

## Download Windows exe

GitHub will not download a 43 MB file from the **blob** page (the floppy-disk icon is dead; it only says it cannot preview the file).

While signed in, open:

https://github.com/enejac/GoldclubConfigScanner/raw/master/downloads/Launch-ConfigScanner.exe

That is the **View raw** link. Or: **Code → Download ZIP**, then take `downloads\Launch-ConfigScanner.exe`.

Stamp: **2026-09-10 08:48 UTC**. Keep repo `tools\` next to the exe.

## Run from source

```powershell
python gui_app.py
```

## Build USB exe

```powershell
.\build_exe.ps1
```

Output: `dist\ConfigScanner.exe` (copied to repo root). Writable data lives in `config-scanner\` beside the exe.

## Tests

```powershell
python -m pytest tests -q
```

## Profiles

See `config_scanner/assets/profiles.json` — `roulette_usb` and `slot_lab_90`. Slot adaptation belongs in this repo, not in Log Investigator.

## Cabinet repairs

[`docs/cabinet-repairs.md`](docs/cabinet-repairs.md) documents the cabinet faults we have hit in the field — licence XMLs not next to `OneHand.exe`, an `AurumSetup.xml` host block that does not match the Windows hostname, the MUX stuck off COM11 (`NO SAS COMMUNICATIONS`), the black-screen boot caused by the shell's UAC-filtered token, and a pending slot RAM clear — with the root cause, the evidence, and the manual procedure for each.

All of them are automated in the app under **More → Diagnose & repair cabinet…** ([`config_scanner/cabinet_repairs.py`](config_scanner/cabinet_repairs.py)).
