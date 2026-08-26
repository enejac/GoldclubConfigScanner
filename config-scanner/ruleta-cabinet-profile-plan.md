# Ruleta cabinet profile — keep 10.1 HW/SAS/wheel, import foreign software

Cabinet: **GRT330106 / 10.0.0.111**. Goal: software taken from another machine
must drop onto this slot and run without importing that machine’s hardware,
SAS, switches, wheel, or identity.

This is **not** “restore a 10.2 snapshot over live 10.1 config.”
It is **software-import + local cabinet profile**.

## What we measured (same cabinet, two snaps)

| | 10.1 | 10.2 |
|---|---|---|
| Snap | `2026-08-19_…_v10.1_b40114_102620` | `2026-08-17_…_v10.2_b40114_125213` |
| Exe ProductVersion | 10.1.8.0 | 10.2.0.827 |
| Archived files | 472 | 473 |
| Identical SHA1 | 470 of 471 shared files | |
| `setup.xml` leaves | 922 | 920 |
| Leaf diffs | **10** | |
| `godot.xml` | identical (10 window slots in the file) | identical |

`setup.xml` diffs that actually exist:

1. 10.1 has two extra Godot nodes (`enable player select=1`, `show online bonusing popup=0`). Harmless extras.
2. Bill denominations A–H `active` is `1` on the 10.1 snap and `0` on the 10.2 snap. **Live HW state**, not a 10.1/10.2 schema change. Keep the 10.1 values.

Everything the user named as “must stay intact” is **already the same** in both
on-cabinet snaps:

- `hardware settings / additional / wheel` = `double zero with serie`
- `validate wheel compatibility` = `1`
- `game settings / additional / ballread / sensor type` = `2` (sim-all)
- `testmode / forcerng` = `1`
- `number of player stations` = `1`
- `config/etc/application/game/switches.xml` same hash
- layouts: `layout1` futura_doublezero, `layout2` futura_doublezeroCrycle

July `10.2.0.684` snaps (`G:\`, still `content-type="gcxml"` hashed tags) are
**not** a leaf compare. Do not treat that 1786-path churn as a schema delta.

## Why they are still not interchangeable

The archived **config** is interchangeable on this EGM. The **runtime stack** is not.

### 1. Signed SAS DeviceManager (hard gate)

Live `processorStatus` player 0:

`themeId=futura_doublezero` `paytableId=paytable_elite_double_zero` `denomId=10000`

Ruleta **10.1** enum-parses only:

`paytable_double_zero`, `paytable_premium`, `paytable_elite`,
`paytable_player_select`, `paytable_single_zero`.

`paytable_elite_double_zero` / `paytable_premium_double_zero` are 10.2-only.
`PutRemoteThemeAndCombo` then `CRIT bad conversion` and `ProcessExit` in ~5 s.

Those strings live in **MAC-signed** files that Config Scanner does **not**
snapshot:

- `ruleta/var/SASControler1/DeviceManagerData.xml_{1,2}`
- `services/aurum/var/MeterHost/DeviceManagerData.xml_{1,2}`
- `ruleta/var/gm2au/…` when present

`config_scanner/paytable_compat.py` remaps **writable** combo / AurumSetup /
unsigned XML only. A 16-byte header is never rewritten (DATA TAMPERED).
`REVERT-SAS-101` (move + regen) wrote **222-byte stubs**. Do not run it again.

There is **no 10.1-signed DeviceManager backup** on this cabinet.

### 2. Licence / trial

Live licence is `37A55022DCBEF351AE27471D181B1EF5.xml` (WIBU **12-12262688**).
`licence.dll` is never overwritten when the dest exists.

| Pack | Result on this dongle |
|---|---|
| 10.2.0.827 licensed for 12262688 | expected to load 10.2 SAS names |
| 10.2.0.684 Development | ERROR 30 / LLAVE |
| Downloads 10.2.0.0 | silent `ProcessExit` / `return 0` |
| Foreign licence XML / other WIBU | ERROR 30 or refuse write |

### 3. Foreign setup (the 282 KB incident)

A donor pack that includes `setup.xml` can replace **this** cabinet’s 10.1
setup. That is how Godot extras became `-- --` instead of
`--gamestart=old --market=colombia …`. Snapshots re-encrypt plain gcxml on
write-back; a raw foreign encrypted file is a different tree.

`godot.xml` in both snaps lists windows 1–10. Ruleta still honours
`number of player stations=1` from **setup**. Keep setup; do not import a
multi-station donor setup.

### 4. Paytable JSON

10.2 snaps add:

- `paytable_elite_double_zero.json` (id 6)
- `paytable_premium_double_zero.json` (id 4)

Safe beside a 10.2 exe. On 10.1 they must stay quarantined / not restored
(`no_paytable` / `is_10_2_only_paytable_json`).

## Existing tools vs the gap

Already in product:

- Write scopes: full / hardware / software / no_paytable / full_software
- Never write `serialport/` or machine identity / live licence
- Identity leaf merge on other XML
- 7-file surgical pack (`network/software_version_swap.py`)
- Four-part PE match (no silent 827 뿯↽ 684)
- Writable paytable remap + `ruleta-compat-hold.json`

**Missing:** a scope that copies **only binaries** from a donor and then
**re-applies this cabinet’s 10.1 profile**. `Config + Ruleta software` still
writes snapshot **config** first — the wrong direction for “random machine
software onto my slot.”

## Cabinet profile (never taken from a donor)

Freeze and restore from **this** EGM only:

1. `config` + `bios` `application/ruleta/setup.xml` (10.1 snap
   `…_v10.1_b40114_102620`, re-encrypted). Both copies stay in sync.
2. `config/etc/application/game/switches.xml` (+ hwsubsys switch plugins).
3. `serialport/layout.json` + `locations.json` — read-only, never write.
4. Live licence XML + `licence.dll`.
5. `ProductSerialNumber`, `HostName`, `ConfigureAurum`, `services/aurum/**`.
6. Signed DeviceManager copies (current 10.2 names until GoldClub re-signs).
7. Wheel slice inside setup: wheel type, sensor type **2**, `forcerng`,
   player stations **1**, KeyboardPanel, tito/bill/lights/UPS flags.
8. `combo.dat` after remap (`EgmPaytableId` the live exe can parse).

## Software import (allowed from a random machine)

Only after PE preflight:

- `Ruleta.exe`
- `godot/RouletteGui.pck`
- Godot / middleware DLLs in the 7-file pack
- Paytable JSON whose `name` the **live** exe can parse

Refuse from the donor:

- `setup.xml`, `godot.xml`
- `serialport/**`
- licences / `licence.dll` if dest exists
- `DeviceManagerData.xml_*`
- `combo.dat`, `AurumSetup.xml`
- OnLine / leftover site DLLs unless we later expand the pack on purpose

If the donor tree also contains setup, **re-encrypt the frozen 10.1 setup**
onto bios + config after the copy.

## When a drop works out of the box

**Path A — stay on 10.1 exe (current SAS blocks this)**

Needs GoldClub to re-sign DeviceManager so player 0 `paytableId` is a 10.1
name (typically `paytable_double_zero`). Then any 10.1.8.0 pack with this
WIBU works on the frozen profile. We cannot mint that MAC.

**Path B — licensed 10.2.0.827 (matches today’s SAS)**

1. Verify PE **exactly** `10.2.0.827` (not 684, not 10.2.0.0).
2. Copy the 7 files; skip `licence.dll`.
3. Keep this cabinet’s 10.1 setup / switches / serialport / signed SAS.
4. Allow the two 10.2 paytable JSON files.
5. Clear `ruleta-compat-hold.json` only after the 10.2 exe is live.
6. FullStack from an elevated console on the cabinet (Session 0 cannot SCM).

**Path C — same major.minor + SAS vocabulary already matches**

10.1 exe + 10.1 SAS, or 10.2 exe + 10.2 SAS, plus this cabinet’s profile.
That is the only “random pack, no extra work” case.

## Implementation (in product)

1. `config_scanner/cabinet_profile.py` freezes live setup/godot/switches plus
   DeviceManager/licence hashes next to Config Scanner and under
   `var/state/cabinet-profile`.
2. Write scope `binaries_only` — GUI **Ruleta software only (keep cabinet profile)**.
3. Preflight refuses `10.2.0.684` and `10.2.0.0`. Surgical 7-file copy only;
   donor setup/godot/licence/SAS noted and not applied.
4. After copy: reapply frozen files if stomped; copy 10.2-only paytable JSON
   only when the live exe is 10.2; remap writable ids; `plan_ruleta_compat`.
5. Tests in `tests/test_config_scanner_seamless_restore.py`.

Do not: `REVERT-SAS-101`, unsigned MAC patch, `GOLD-CLUB\test` on this
workgroup host, overwrite `37A55022…`, or treat `BuildVersion.txt` as the
exe version.
