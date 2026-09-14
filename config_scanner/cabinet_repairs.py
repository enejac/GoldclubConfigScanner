"""Diagnose and repair known GoldClub cabinet faults.

Each entry in :data:`REPAIRS` is one field-proven fault: a cheap ``diagnose``
that reports whether the cabinet is in that state, and a ``repair`` that puts it
right. The GUI (More -> Diagnose & repair cabinet...) lists the findings and
lets the operator apply the ones that matter.

Background, evidence and the manual procedure for every repair live in
``docs/cabinet-repairs.md``. Keep the two in sync.

Two hard boundaries, inherited from the cabinet rules: nothing here touches boot
configuration (bcdboot / BCD / EFI / registry hives), and nothing rewrites the
serial port board maps ``layout.json`` / ``locations.json``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from app_paths import app_install_dir
from config_scanner.build_version import (
    is_unc_path,
    normalize_scan_target,
    scan_target_path,
)
from config_scanner.slot_setup import goldclub_root_from_target
from config_scanner.stack_restart import unc_host_from_target
from network.lab_access import ensure_lab_smb_credential, safe_join_under

STATUS_OK = "ok"
STATUS_BROKEN = "broken"
STATUS_UNKNOWN = "unknown"
STATUS_NOT_APPLICABLE = "not_applicable"

# Staged next to UnlockerDisk.exe, which is where the custom shell already looks.
CABINET_SECURITY_DIR = r"C:\Platform\Security"

_PLATFORM_SECURITY_SCRIPTS = (
    "Repair-MuxSasPort.ps1",
    "Clear-MuxGhostPorts.ps1",
    "Unlock-GoldClubVolume.ps1",
    "Install-GoldClubBootTasks.ps1",
)


class RepairError(RuntimeError):
    """A repair could not be attempted (bad target, missing script, no WinRM)."""


@dataclass(frozen=True)
class RepairContext:
    """Everything a diagnose/repair needs about the cabinet under the cursor."""

    scan_target: str
    goldclub_root: Path
    game_kind: str
    host: str | None = None  # UNC host / IP; None when the target is local

    @property
    def is_remote(self) -> bool:
        return bool(self.host)


@dataclass(frozen=True)
class RepairFinding:
    repair_id: str
    title: str
    status: str
    detail: str
    destructive: bool = False

    @property
    def needs_repair(self) -> bool:
        return self.status == STATUS_BROKEN


@dataclass(frozen=True)
class RepairOutcome:
    repair_id: str
    title: str
    ok: bool
    detail: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CabinetRepair:
    id: str
    title: str
    summary: str
    diagnose: Callable[[RepairContext], RepairFinding]
    repair: Callable[[RepairContext], RepairOutcome]
    game_kinds: tuple[str, ...] | None = None
    destructive: bool = False
    needs_remote: bool = False

    def applies_to(self, game_kind: str) -> bool:
        if self.game_kinds is None:
            return True
        return (game_kind or "").strip().casefold() in self.game_kinds


# --------------------------------------------------------------------------
# context / transport helpers
# --------------------------------------------------------------------------


def build_context(scan_target: str, game_kind: str) -> RepairContext:
    if not (scan_target or "").strip():
        raise RepairError("No scan target selected.")
    normalized = normalize_scan_target(scan_target)
    if not normalized:
        raise RepairError(f"Could not resolve a cabinet path from {scan_target!r}.")
    root = goldclub_root_from_target(scan_target_path(normalized))
    host = unc_host_from_target(normalized) if is_unc_path(normalized) else None
    if host:
        ensure_lab_smb_credential(host)
    return RepairContext(
        scan_target=normalized,
        goldclub_root=root,
        game_kind=(game_kind or "").strip().casefold() or "roulette",
        host=host,
    )


def _repair_tools_dir() -> Path:
    """Locate the platform-security scripts: exe folder, frozen bundle, then repo."""
    probe = "Repair-MuxSasPort.ps1"
    candidates: list[Path] = []
    root = app_install_dir()
    candidates.extend(
        [
            root / "cabinet_tools" / "shared" / "platform-security",
            root / "scripts" / "platform-security",
            root / "platform-security",
        ]
    )
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(
            Path(sys._MEIPASS) / "cabinet_tools" / "shared" / "platform-security"
        )
    repo_root = Path(__file__).resolve().parents[1]
    candidates.append(repo_root / "cabinet_tools" / "shared" / "platform-security")

    for directory in candidates:
        try:
            if (directory / probe).is_file():
                return directory
        except OSError:
            continue
    raise RepairError(
        f"{probe} not found - expected beside the exe in "
        "cabinet_tools\\shared\\platform-security."
    )


def _parse_kv(text: str) -> dict[str, str]:
    """Read ``KEY=VALUE`` lines out of a remote script's stdout."""
    found: dict[str, str] = {}
    for line in (text or "").splitlines():
        stripped = line.strip()
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if key and re.fullmatch(r"[A-Z0-9_]+", key):
            found[key] = value.strip()
    return found


def _truthy(value: str | None) -> bool:
    return (value or "").strip().casefold() in {"true", "1", "yes"}


def run_probe(ctx: RepairContext, script: str, *, timeout: int = 60) -> dict[str, str]:
    """Run a read-only PowerShell probe on the cabinet and parse KEY=VALUE output."""
    if ctx.is_remote:
        from config_scanner.stack_restart import remote_winrm_ready, winrm_skip_detail
        from automation.remote_exec import winrm_run_inline

        if not remote_winrm_ready(ctx.host):
            raise RepairError(winrm_skip_detail(str(ctx.host)))
        result = winrm_run_inline(ip=str(ctx.host), script=script, timeout=timeout)
        if result.returncode != 0 and not result.stdout.strip():
            raise RepairError(
                (result.stderr or "WinRM probe failed").strip().splitlines()[0]
            )
        return _parse_kv(result.stdout)
    completed = _run_local_powershell(["-Command", script], timeout=timeout)
    return _parse_kv(completed.stdout)


def _run_local_powershell(args: Sequence[str], *, timeout: int) -> subprocess.CompletedProcess:
    run_kw: dict = {
        "capture_output": True,
        "text": True,
        "errors": "replace",
        "timeout": timeout,
    }
    if os.name == "nt":
        run_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
        **run_kw,
    )


def stage_platform_security_scripts(
    ctx: RepairContext,
    names: Iterable[str] = _PLATFORM_SECURITY_SCRIPTS,
) -> list[str]:
    """Copy repair scripts to ``C:\\Platform\\Security`` on the cabinet."""
    source_dir = _repair_tools_dir()
    if ctx.is_remote:
        dest_dir = Path(rf"\\{ctx.host}\c$\Platform\Security")
    else:
        dest_dir = Path(CABINET_SECURITY_DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)

    staged: list[str] = []
    for name in names:
        src = source_dir / name
        if not src.is_file():
            raise RepairError(f"Missing local script: {src}")
        shutil.copy2(src, dest_dir / name)
        staged.append(name)
    return staged


def run_cabinet_script(
    ctx: RepairContext,
    script_name: str,
    *,
    args: list[str] | None = None,
    timeout: int = 300,
) -> tuple[int, str]:
    """Run a staged script elevated on the cabinet; return (exit code, output)."""
    remote_path = rf"{CABINET_SECURITY_DIR}\{script_name}"
    if ctx.is_remote:
        from automation.remote_exec import winrm_run_elevated_script

        result = winrm_run_elevated_script(
            ip=str(ctx.host),
            remote_script_path=remote_path,
            script_args=list(args or []),
            timeout=timeout,
        )
        output = "\n".join(part for part in (result.stdout, result.stderr) if part.strip())
        return result.returncode, output
    completed = _run_local_powershell(
        ["-File", remote_path, *(args or [])],
        timeout=timeout,
    )
    output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part.strip()
    )
    return completed.returncode, output


# --------------------------------------------------------------------------
# 1. slot licence placement
# --------------------------------------------------------------------------

_LICENCE_HASH_RE = re.compile(r"^[0-9A-Fa-f]{64}\.xml$")
_LICENCE_DIR_NAMES = ("Licenses", "Licences")
_LICENCE_DLL_NAMES = ("licence.dll", "license.dll")


def _is_licence_xml(name: str) -> bool:
    lowered = (name or "").casefold()
    if not lowered.endswith(".xml"):
        return False
    if lowered.startswith("licence") or lowered.startswith("license"):
        return True
    return bool(_LICENCE_HASH_RE.match(name or ""))


def _licence_search_dirs(root: Path) -> list[Path]:
    # slot\\ first so a working OneHand copy wins over a stale Goldclub-root leftover.
    dirs = [root / "slot"]
    for name in _LICENCE_DIR_NAMES:
        dirs.append(root / name)
    dirs.append(root / "config" / "licences")
    dirs.append(root / "config" / "licenses")
    dirs.append(root)
    return dirs


def _collect_licence_xmls(root: Path) -> dict[str, Path]:
    """First source for each licence XML name (slot\\ before root leftovers)."""
    found: dict[str, Path] = {}
    for directory in _licence_search_dirs(root):
        try:
            if not directory.is_dir():
                continue
            entries = list(directory.iterdir())
        except OSError:
            continue
        for path in entries:
            try:
                if not path.is_file() or not _is_licence_xml(path.name):
                    continue
            except OSError:
                continue
            found.setdefault(path.name, path)
    return found


def _licence_destinations(root: Path) -> list[Path]:
    """Where OneHand and Bootstrap actually look for licence XMLs."""
    dests = [root / "slot", root]
    for name in _LICENCE_DIR_NAMES:
        candidate = root / name
        try:
            if candidate.is_dir():
                dests.append(candidate)
        except OSError:
            continue
    return dests


def _same_bytes(a: Path, b: Path) -> bool:
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def _missing_licence_copies(root: Path) -> list[tuple[Path, Path]]:
    """(source, destination) pairs that need writing."""
    sources = _collect_licence_xmls(root)
    pending: list[tuple[Path, Path]] = []
    for name, src in sorted(sources.items()):
        for dest_dir in _licence_destinations(root):
            dest = dest_dir / name
            if dest == src:
                continue
            try:
                if dest.is_file() and _same_bytes(src, dest):
                    continue
            except OSError:
                pass
            pending.append((src, dest))

    dll_src: Path | None = None
    for directory in (root / "slot", root):
        for dll_name in _LICENCE_DLL_NAMES:
            candidate = directory / dll_name
            try:
                if candidate.is_file():
                    dll_src = candidate
                    break
            except OSError:
                continue
        if dll_src is not None:
            break
    # The WIBU stub is only ever read next to OneHand.exe. A working cabinet has
    # no root-level copy, so do not manufacture one.
    if dll_src is not None:
        dest = root / "slot" / "licence.dll"
        if dest != dll_src and not (dest.is_file() and _same_bytes(dll_src, dest)):
            pending.append((dll_src, dest))
    return pending


def _diagnose_slot_licence(ctx: RepairContext) -> RepairFinding:
    root = ctx.goldclub_root
    sources = _collect_licence_xmls(root)
    if not sources:
        return RepairFinding(
            repair_id="slot_licence_placement",
            title=_TITLE_LICENCE,
            status=STATUS_UNKNOWN,
            detail=(
                "No licence XML anywhere under the game root - install the "
                "licence pack first, or restore one from a snapshot."
            ),
        )
    pending = _missing_licence_copies(root)
    if not pending:
        return RepairFinding(
            repair_id="slot_licence_placement",
            title=_TITLE_LICENCE,
            status=STATUS_OK,
            detail=(
                f"{len(sources)} licence file(s) present in every location "
                "OneHand reads."
            ),
        )
    shown = ", ".join(
        str(dest.relative_to(root)).replace("\\", "/") for _, dest in pending[:4]
    )
    extra = f" (+{len(pending) - 4} more)" if len(pending) > 4 else ""
    return RepairFinding(
        repair_id="slot_licence_placement",
        title=_TITLE_LICENCE,
        status=STATUS_BROKEN,
        detail=(
            f"{len(pending)} licence file(s) missing where the game reads them: "
            f"{shown}{extra}. OneHand.exe resolves licences next to itself in "
            "slot\\, so a pack installed only into Licenses\\ shows 'No licence!'."
        ),
    )


def _repair_slot_licence(ctx: RepairContext) -> RepairOutcome:
    root = ctx.goldclub_root
    pending = _missing_licence_copies(root)
    if not pending:
        return RepairOutcome(
            repair_id="slot_licence_placement",
            title=_TITLE_LICENCE,
            ok=True,
            detail="Nothing to do - licence files are already in place.",
        )
    notes: list[str] = []
    failures = 0
    for src, dest in pending:
        rel = str(dest.relative_to(root)).replace("\\", "/")
        try:
            safe_join_under(root, rel)
        except ValueError as exc:
            notes.append(f"{rel}: {exc}")
            failures += 1
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            notes.append(f"copied {src.name} -> {rel}")
        except OSError as exc:
            notes.append(f"{rel}: {exc}")
            failures += 1
    ok = failures == 0
    written = len(pending) - failures
    detail = f"Placed {written} licence file(s)."
    if failures:
        detail += f" {failures} failed."
    return RepairOutcome(
        repair_id="slot_licence_placement",
        title=_TITLE_LICENCE,
        ok=ok,
        detail=detail,
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------
# 2. AurumSetup host block
# --------------------------------------------------------------------------

_AURUM_SETUP_REL = "services/aurum/config/AurumSetup.xml"
_HOST_ELEMENTS = ("NetworkHostName", "ServiceURI", "MessengerURI")
_HOSTNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9\-]{1,14}$")

_MACHINE_NAME_PROBE = "'MACHINE=' + [Environment]::MachineName"


def _aurum_setup_path(root: Path) -> Path:
    return root / Path(_AURUM_SETUP_REL)


def find_aurum_setup_xml(goldclub: Path) -> Path | None:
    """Locate AurumSetup.xml under a Goldclub root (any Services/services casing)."""
    direct = _aurum_setup_path(goldclub)
    try:
        if direct.is_file():
            return direct
    except OSError:
        pass
    from config_scanner.slot_setup import _resolve_goldclub_rel

    found = _resolve_goldclub_rel(goldclub, _AURUM_SETUP_REL)
    if found is not None:
        try:
            if found.is_file():
                return found
        except OSError:
            return None
    return None


def rewrite_aurum_host_tokens(
    setup: Path,
    machine: str,
    *,
    backup: bool = True,
) -> tuple[bool, str]:
    """In-place NetworkHostName / ServiceURI / MessengerURI rewrite.

    Does not round-trip the file through ElementTree — LoadSetup is sensitive
    to that (GST22377: overlay host GST20664 left SASControler1 unconfigured).
    Returns ``(changed, detail)``.
    """
    machine = (machine or "").strip()
    if not machine or not _HOSTNAME_RE.match(machine):
        return False, "invalid Windows hostname"
    try:
        text = setup.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, f"could not read {setup}: {exc}"

    hosts = _aurum_host_names(text)
    stale = [h for h in hosts if h.casefold() != machine.casefold()]
    if not stale:
        return False, f"AurumSetup already targets {machine}"

    notes: list[str] = []
    patched = text
    for old in stale:
        for element in _HOST_ELEMENTS:
            pattern = re.compile(
                rf"(<{element}>\s*)([^<]*?)(\s*</{element}>)", re.IGNORECASE
            )

            def _swap(match: re.Match[str], _old: str = old) -> str:
                value = match.group(2)
                if _old.casefold() not in value.casefold():
                    return match.group(0)
                replaced = re.sub(re.escape(_old), machine, value, flags=re.IGNORECASE)
                return f"{match.group(1)}{replaced}{match.group(3)}"

            patched = pattern.sub(_swap, patched)
        notes.append(f"{old} -> {machine}")

    if patched == text:
        return False, "found a stale host block but no host token to rewrite"

    if backup:
        backup_path = setup.with_name(f"{setup.name}.bak-host-{stale[0]}")
        try:
            if not backup_path.exists():
                shutil.copy2(setup, backup_path)
                notes.append(f"backup {backup_path.name}")
        except OSError as exc:
            return False, f"could not backup {setup}: {exc}"
    try:
        setup.write_text(patched, encoding="utf-8")
    except OSError as exc:
        return False, f"could not write {setup}: {exc}"
    return True, "; ".join(notes) or f"rewrote host tokens to {machine}"


def _cabinet_machine_name(ctx: RepairContext) -> str | None:
    if not ctx.is_remote:
        return (os.environ.get("COMPUTERNAME") or "").strip() or None
    try:
        values = run_probe(ctx, _MACHINE_NAME_PROBE, timeout=30)
    except RepairError:
        return None
    name = (values.get("MACHINE") or "").strip()
    return name or None


def _aurum_host_names(text: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(
        r"<NetworkHostName>\s*([^<\s]+)\s*</NetworkHostName>", text, re.IGNORECASE
    ):
        candidate = match.group(1).strip()
        if candidate and candidate not in names:
            names.append(candidate)
    return names


def _diagnose_aurum_hostname(ctx: RepairContext) -> RepairFinding:
    setup = _aurum_setup_path(ctx.goldclub_root)
    try:
        if not setup.is_file():
            return RepairFinding(
                repair_id="aurum_setup_hostname",
                title=_TITLE_AURUM,
                status=STATUS_NOT_APPLICABLE,
                detail=f"No {_AURUM_SETUP_REL} - this cabinet has no Aurum config.",
            )
        text = setup.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return RepairFinding(
            repair_id="aurum_setup_hostname",
            title=_TITLE_AURUM,
            status=STATUS_UNKNOWN,
            detail=f"Could not read {_AURUM_SETUP_REL}: {exc}",
        )

    machine = _cabinet_machine_name(ctx)
    if not machine:
        return RepairFinding(
            repair_id="aurum_setup_hostname",
            title=_TITLE_AURUM,
            status=STATUS_UNKNOWN,
            detail=(
                "Could not read the cabinet's Windows hostname (WinRM). "
                "AurumSetup selects its <Network> block by machine name, so the "
                "check needs it."
            ),
        )

    hosts = _aurum_host_names(text)
    if any(h.casefold() == machine.casefold() for h in hosts):
        return RepairFinding(
            repair_id="aurum_setup_hostname",
            title=_TITLE_AURUM,
            status=STATUS_OK,
            detail=f"AurumSetup has a <Network> block for {machine}.",
        )
    listed = ", ".join(hosts) if hosts else "none"
    return RepairFinding(
        repair_id="aurum_setup_hostname",
        title=_TITLE_AURUM,
        status=STATUS_BROKEN,
        detail=(
            f"Windows hostname is {machine} but AurumSetup only has block(s) for "
            f"{listed}. LoadSetup picks the block by machine name, so "
            "SASControler1 is never configured -> 'CONFIG FOR SASControler1 NOT "
            "FOUND!' and AurumEGM..ctor throws a NullReferenceException."
        ),
    )


def _repair_aurum_hostname(ctx: RepairContext) -> RepairOutcome:
    setup = find_aurum_setup_xml(ctx.goldclub_root)
    machine = _cabinet_machine_name(ctx)
    if setup is None:
        return RepairOutcome(
            repair_id="aurum_setup_hostname",
            title=_TITLE_AURUM,
            ok=False,
            detail=f"No {_AURUM_SETUP_REL} - this cabinet has no Aurum config.",
        )
    if not machine or not _HOSTNAME_RE.match(machine):
        return RepairOutcome(
            repair_id="aurum_setup_hostname",
            title=_TITLE_AURUM,
            ok=False,
            detail="Could not resolve a usable Windows hostname for the cabinet.",
        )
    changed, detail = rewrite_aurum_host_tokens(setup, machine, backup=True)
    if not changed and "already targets" in detail:
        return RepairOutcome(
            repair_id="aurum_setup_hostname",
            title=_TITLE_AURUM,
            ok=True,
            detail=f"AurumSetup already targets {machine}.",
        )
    if not changed:
        return RepairOutcome(
            repair_id="aurum_setup_hostname",
            title=_TITLE_AURUM,
            ok=False,
            detail=detail,
        )
    notes = tuple(part.strip() for part in detail.split(";") if part.strip())
    return RepairOutcome(
        repair_id="aurum_setup_hostname",
        title=_TITLE_AURUM,
        ok=True,
        detail=(
            f"Rewrote the AurumSetup host tokens to {machine}. Restart "
            "GoldClub.Aurum.Services and the game; expect 50010 and 50011 to listen."
        ),
        notes=notes,
    )


# --------------------------------------------------------------------------
# 3. MUX / SAS COM port
# --------------------------------------------------------------------------

_MUX_TARGET_PORT = 11

_MUX_PROBE = r"""
$hw = 'VID_0483&PID_5740'
$base = "HKLM:\SYSTEM\CurrentControlSet\Enum\USB\$hw"
$total = 0
$ghosts = 0
$livePort = ''
$liveName = ''
if (Test-Path -LiteralPath $base) {
    foreach ($k in (Get-ChildItem -LiteralPath $base -ErrorAction SilentlyContinue)) {
        $total++
        $serial = $k.PSChildName
        $dp = Get-ItemProperty -LiteralPath (Join-Path $k.PSPath 'Device Parameters') -ErrorAction SilentlyContinue
        $pnp = Get-PnpDevice -InstanceId "USB\$hw\$serial" -ErrorAction SilentlyContinue
        if ($pnp -and $pnp.Present) {
            $livePort = [string]$dp.PortName
            $liveName = [string](Get-ItemProperty -LiteralPath $k.PSPath -ErrorAction SilentlyContinue).FriendlyName
        }
        else { $ghosts++ }
    }
}
$active = (Get-ItemProperty 'HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM' -ErrorAction SilentlyContinue).'\Device\USBSER000'
$listening = [bool](Get-NetTCPConnection -State Listen -LocalPort 31100 -ErrorAction SilentlyContinue)
"NODES=$total"
"GHOSTS=$ghosts"
"LIVE_PORT=$livePort"
"LIVE_NAME=$liveName"
"ACTIVE_PORT=$active"
"SAS_LISTENING=$listening"
""".strip()


def _diagnose_mux_sas(ctx: RepairContext) -> RepairFinding:
    try:
        values = run_probe(ctx, _MUX_PROBE, timeout=90)
    except RepairError as exc:
        return RepairFinding(
            repair_id="mux_sas_com_port",
            title=_TITLE_MUX,
            status=STATUS_UNKNOWN,
            detail=f"Could not query the cabinet: {exc}",
        )
    if not values:
        return RepairFinding(
            repair_id="mux_sas_com_port",
            title=_TITLE_MUX,
            status=STATUS_UNKNOWN,
            detail="No answer from the cabinet probe (WinRM reachable?).",
        )

    nodes = int(values.get("NODES") or 0)
    ghosts = int(values.get("GHOSTS") or 0)
    active = (values.get("ACTIVE_PORT") or "").strip()
    listening = _truthy(values.get("SAS_LISTENING"))
    target = f"COM{_MUX_TARGET_PORT}"

    if nodes == 0:
        return RepairFinding(
            repair_id="mux_sas_com_port",
            title=_TITLE_MUX,
            status=STATUS_NOT_APPLICABLE,
            detail="No MUX board (VID_0483&PID_5740) on this cabinet.",
        )
    if active == target and listening:
        return RepairFinding(
            repair_id="mux_sas_com_port",
            title=_TITLE_MUX,
            status=STATUS_OK,
            detail=f"MUX is on {target} and CommCtrlSAS is listening on 31100.",
        )

    reasons: list[str] = []
    if active and active != target:
        reasons.append(f"the live board is on {active}, not {target}")
    if ghosts:
        reasons.append(
            f"{ghosts} ghost node(s) hold COM reservations (the board's USB "
            "serial is not stable, so Windows mints a node per identity)"
        )
    if not listening:
        reasons.append("nothing is listening on 31100, so Aurum's SASControler1 "
                       "has no gateway and the game locks with "
                       "'NO SAS COMMUNICATIONS'")
    return RepairFinding(
        repair_id="mux_sas_com_port",
        title=_TITLE_MUX,
        status=STATUS_BROKEN,
        detail="; ".join(reasons) or "MUX/SAS port assignment is inconsistent.",
    )


def _repair_mux_sas(ctx: RepairContext) -> RepairOutcome:
    notes: list[str] = []
    staged = stage_platform_security_scripts(
        ctx, ("Repair-MuxSasPort.ps1", "Clear-MuxGhostPorts.ps1")
    )
    notes.append("staged " + ", ".join(staged))

    code, output = run_cabinet_script(ctx, "Repair-MuxSasPort.ps1", timeout=420)
    values = _parse_kv(output)
    result = (values.get("RESULT") or "").strip()
    active = (values.get("ACTIVE_PORT") or "").strip()
    listening = _truthy(values.get("SAS_LISTENING"))
    script_log = [line.strip() for line in (output or "").splitlines() if line.strip()]
    notes.extend(script_log[-60:])

    if result == "OK":
        return RepairOutcome(
            repair_id="mux_sas_com_port",
            title=_TITLE_MUX,
            ok=True,
            detail=(
                f"MUX is on {active} and CommCtrlSAS is listening on 31100. "
                "OneHand should drop the host lock within a few seconds."
            ),
            notes=tuple(notes),
        )
    messages = {
        "NOT_ELEVATED": "The repair needs a real admin token on the cabinet.",
        "NO_DEVICE": "No MUX board found - check that it is plugged in.",
        "NO_LIVE_DEVICE": "Only ghost MUX nodes are present; nothing to reassign.",
        "NO_DEVCON": "devcon.exe was not found on the cabinet.",
        "PORT_OK_NO_LISTENER": (
            f"The MUX is on {active} but CommCtrlSAS is not listening on 31100 yet."
        ),
        "PORT_NOT_APPLIED": (
            f"The port is still {active}. A service kept the handle open; a reboot "
            "will finish the device restart."
        ),
    }
    detail = messages.get(result) or (
        f"Repair script exited {code}"
        + (f" ({result})" if result else "")
        + f"; active port {active or 'unknown'}, 31100 listening {listening}."
    )
    return RepairOutcome(
        repair_id="mux_sas_com_port",
        title=_TITLE_MUX,
        ok=False,
        detail=detail,
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------
# 4. boot tasks (BitLocker unlock + MUX ghost cleanup as SYSTEM)
# --------------------------------------------------------------------------

_UNLOCK_TASK = "GoldClub-Unlock-Volume"
_MUX_TASK = "GoldClub-Clear-MuxGhosts"

_BOOT_TASK_PROBE = r"""
function Test-Task {
    param([string]$Name)
    $null = cmd /c "schtasks /Query /TN ""$Name"" /FO LIST" 2>&1
    return ($LASTEXITCODE -eq 0)
}
"UNLOCK_TASK=" + (Test-Task 'GoldClub-Unlock-Volume')
"MUX_TASK=" + (Test-Task 'GoldClub-Clear-MuxGhosts')
"DEVCON=" + [IO.File]::Exists('C:\Platform\Security\devcon.exe')
""".strip()


def _diagnose_boot_tasks(ctx: RepairContext) -> RepairFinding:
    try:
        values = run_probe(ctx, _BOOT_TASK_PROBE, timeout=60)
    except RepairError as exc:
        return RepairFinding(
            repair_id="goldclub_boot_tasks",
            title=_TITLE_BOOT_TASKS,
            status=STATUS_UNKNOWN,
            detail=f"Could not query scheduled tasks: {exc}",
        )
    if not values:
        return RepairFinding(
            repair_id="goldclub_boot_tasks",
            title=_TITLE_BOOT_TASKS,
            status=STATUS_UNKNOWN,
            detail="No answer from the cabinet probe (WinRM reachable?).",
        )

    missing: list[str] = []
    if not _truthy(values.get("UNLOCK_TASK")):
        missing.append(_UNLOCK_TASK)
    if not _truthy(values.get("MUX_TASK")):
        missing.append(_MUX_TASK)

    if missing:
        return RepairFinding(
            repair_id="goldclub_boot_tasks",
            title=_TITLE_BOOT_TASKS,
            status=STATUS_BROKEN,
            detail=(
                f"Missing AtStartup SYSTEM task(s): {', '.join(missing)}. Without "
                "them the BitLocker unlock runs on the shell's UAC-filtered token, "
                "silently does nothing, and the cabinet boots to a black screen."
            ),
        )
    if not _truthy(values.get("DEVCON")):
        return RepairFinding(
            repair_id="goldclub_boot_tasks",
            title=_TITLE_BOOT_TASKS,
            status=STATUS_BROKEN,
            detail=(
                "Both tasks are registered, but devcon.exe is not staged on C:. "
                "G: is still BitLocker-locked when the MUX task runs, so it would "
                "find nothing to run."
            ),
        )
    return RepairFinding(
        repair_id="goldclub_boot_tasks",
        title=_TITLE_BOOT_TASKS,
        status=STATUS_OK,
        detail="Both AtStartup SYSTEM tasks are registered and devcon.exe is staged.",
    )


def _repair_boot_tasks(ctx: RepairContext) -> RepairOutcome:
    notes: list[str] = []
    staged = stage_platform_security_scripts(ctx)
    notes.append("staged " + ", ".join(staged))

    code, output = run_cabinet_script(
        ctx, "Install-GoldClubBootTasks.ps1", timeout=240
    )
    for line in (output or "").splitlines():
        if line.strip():
            notes.append(line.strip())

    # The installer prints "result: unlock=True muxGhosts=True".
    ok = code == 0 and "unlock=true" in (output or "").casefold()
    detail = (
        f"Registered {_UNLOCK_TASK} and {_MUX_TASK} to run as SYSTEM at startup."
        if ok
        else f"Install-GoldClubBootTasks.ps1 exited {code}; see the notes."
    )
    return RepairOutcome(
        repair_id="goldclub_boot_tasks",
        title=_TITLE_BOOT_TASKS,
        ok=ok,
        detail=detail,
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------
# 5. pending slot RAM clear (destructive)
# --------------------------------------------------------------------------

_RAMCLEAR_MARKER_REL = "var/state/maintenance/invoke-task-ramclear"
_RAMCLEAR_SIGNS = (
    "RAMCLEAR REQUIRED",
    "ErrorRegistryDataNotFound",
)


def _latest_slot_log(root: Path) -> Path | None:
    log_dir = root / "var" / "log" / "SlotLog"
    try:
        logs = [p for p in log_dir.glob("*.log") if p.is_file()]
    except OSError:
        return None
    if not logs:
        return None
    try:
        return max(logs, key=lambda p: p.stat().st_mtime)
    except OSError:
        return logs[-1]


def _diagnose_ramclear(ctx: RepairContext) -> RepairFinding:
    root = ctx.goldclub_root
    marker = root / Path(_RAMCLEAR_MARKER_REL)
    try:
        marker_present = marker.exists()
    except OSError:
        marker_present = False

    log = _latest_slot_log(root)
    hit: str | None = None
    if log is not None:
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        tail = text[-400_000:]
        for sign in _RAMCLEAR_SIGNS:
            if sign.casefold() in tail.casefold():
                hit = sign
                break

    if not marker_present and hit is None:
        return RepairFinding(
            repair_id="slot_ramclear_pending",
            title=_TITLE_RAMCLEAR,
            status=STATUS_OK,
            detail="No RAM clear marker and no trial/NVRAM error in the slot log.",
            destructive=True,
        )
    reasons: list[str] = []
    if marker_present:
        reasons.append("an unconsumed invoke-task-ramclear marker is present")
    if hit:
        reasons.append(f"the slot log contains {hit!r}")
    return RepairFinding(
        repair_id="slot_ramclear_pending",
        title=_TITLE_RAMCLEAR,
        status=STATUS_BROKEN,
        detail=(
            "; ".join(reasons)
            + ". The trial blob lives in NVRAM and a licence change invalidates "
            "it. This clears meters - back the cabinet up first."
        ),
        destructive=True,
    )


def _repair_ramclear(ctx: RepairContext) -> RepairOutcome:
    script = r"G:\bin\RunManteinanceTasks.1.ps1"
    task_dir = "G:\\maintenance\\tasks\\ramclear\\"
    # No -nested: the runner then builds its own PSModulePath and Path.
    command = (
        f"& powershell.exe -NoProfile -ExecutionPolicy Bypass -File '{script}' "
        f"-path '{task_dir}' 2>&1"
    )
    if ctx.is_remote:
        from config_scanner.stack_restart import remote_winrm_ready, winrm_skip_detail
        from automation.remote_exec import winrm_run_inline

        if not remote_winrm_ready(ctx.host):
            return RepairOutcome(
                repair_id="slot_ramclear_pending",
                title=_TITLE_RAMCLEAR,
                ok=False,
                detail=winrm_skip_detail(str(ctx.host)),
            )
        result = winrm_run_inline(ip=str(ctx.host), script=command, timeout=900)
        code = result.returncode
        output = "\n".join(p for p in (result.stdout, result.stderr) if p.strip())
    else:
        completed = _run_local_powershell(["-Command", command], timeout=900)
        code = completed.returncode
        output = "\n".join(
            p for p in (completed.stdout, completed.stderr) if p.strip()
        )
    notes = [line.strip() for line in (output or "").splitlines() if line.strip()]
    ok = code == 0
    detail = (
        "RAM clear finished. Backups are under "
        "var\\state\\maintenance\\ramclear\\backup. Re-check the Dallas key in "
        "slot\\themes\\HardwareConfig.xml if it was replaced."
        if ok
        else f"RunManteinanceTasks exited {code}; see the notes."
    )
    return RepairOutcome(
        repair_id="slot_ramclear_pending",
        title=_TITLE_RAMCLEAR,
        ok=ok,
        detail=detail,
        notes=tuple(notes[-40:]),
    )


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

_TITLE_LICENCE = "Slot licence files not where the game reads them"
_TITLE_AURUM = "AurumSetup host block does not match the Windows hostname"
_TITLE_MUX = "MUX/SAS stuck off COM11 (NO SAS COMMUNICATIONS)"
_TITLE_BOOT_TASKS = "Boot unlock tasks missing (black screen after boot)"
_TITLE_RAMCLEAR = "Pending slot RAM clear (RAMCLEAR REQUIRED)"


REPAIRS: tuple[CabinetRepair, ...] = (
    CabinetRepair(
        id="slot_licence_placement",
        title=_TITLE_LICENCE,
        summary=(
            "Mirror licence XMLs and licence.dll into slot\\, the game root and "
            "Licenses\\ so OneHand.exe can read them."
        ),
        diagnose=_diagnose_slot_licence,
        repair=_repair_slot_licence,
        game_kinds=("slot",),
    ),
    CabinetRepair(
        id="aurum_setup_hostname",
        title=_TITLE_AURUM,
        summary=(
            "Point AurumSetup.xml NetworkHostName / ServiceURI / MessengerURI at "
            "the cabinet's real hostname, leaving the EGM identity alone."
        ),
        diagnose=_diagnose_aurum_hostname,
        repair=_repair_aurum_hostname,
        game_kinds=("slot",),
        needs_remote=True,
    ),
    CabinetRepair(
        id="mux_sas_com_port",
        title=_TITLE_MUX,
        summary=(
            "Drop ghost MUX nodes, let the stock script assign COM11, and bounce "
            "the board with the gateways stopped so no reboot is needed."
        ),
        diagnose=_diagnose_mux_sas,
        repair=_repair_mux_sas,
        needs_remote=True,
    ),
    CabinetRepair(
        id="goldclub_boot_tasks",
        title=_TITLE_BOOT_TASKS,
        summary=(
            "Register the AtStartup SYSTEM tasks that unlock BitLocker and clear "
            "MUX ghosts, which the UAC-filtered shell token cannot do."
        ),
        diagnose=_diagnose_boot_tasks,
        repair=_repair_boot_tasks,
        needs_remote=True,
    ),
    CabinetRepair(
        id="slot_ramclear_pending",
        title=_TITLE_RAMCLEAR,
        summary=(
            "Run the vendor ramclear maintenance task to rebuild the NVRAM trial "
            "blob after a licence change. Clears meters."
        ),
        diagnose=_diagnose_ramclear,
        repair=_repair_ramclear,
        game_kinds=("slot",),
        destructive=True,
        needs_remote=True,
    ),
)


def repairs_for(game_kind: str) -> tuple[CabinetRepair, ...]:
    return tuple(r for r in REPAIRS if r.applies_to(game_kind))


def repair_by_id(repair_id: str) -> CabinetRepair | None:
    for repair in REPAIRS:
        if repair.id == repair_id:
            return repair
    return None


ProgressCb = Callable[[str], None]


def _emit(progress: ProgressCb | None, message: str) -> None:
    if progress is not None:
        try:
            progress(message)
        except Exception:  # noqa: BLE001 - progress must never break a repair
            pass


def diagnose_cabinet(
    ctx: RepairContext,
    *,
    progress: ProgressCb | None = None,
) -> list[RepairFinding]:
    """Run every applicable diagnose; never raises for a single bad check."""
    findings: list[RepairFinding] = []
    for repair in repairs_for(ctx.game_kind):
        _emit(progress, f"Checking: {repair.title} …")
        try:
            finding = repair.diagnose(ctx)
        except RepairError as exc:
            finding = RepairFinding(
                repair_id=repair.id,
                title=repair.title,
                status=STATUS_UNKNOWN,
                detail=str(exc),
                destructive=repair.destructive,
            )
        except Exception as exc:  # noqa: BLE001
            finding = RepairFinding(
                repair_id=repair.id,
                title=repair.title,
                status=STATUS_UNKNOWN,
                detail=f"Check failed: {exc}",
                destructive=repair.destructive,
            )
        findings.append(finding)
    return findings


def apply_repairs(
    ctx: RepairContext,
    repair_ids: Sequence[str],
    *,
    progress: ProgressCb | None = None,
) -> list[RepairOutcome]:
    """Run the named repairs in registry order."""
    wanted = {rid.strip() for rid in repair_ids if rid and rid.strip()}
    outcomes: list[RepairOutcome] = []
    for repair in REPAIRS:
        if repair.id not in wanted:
            continue
        if not repair.applies_to(ctx.game_kind):
            outcomes.append(
                RepairOutcome(
                    repair_id=repair.id,
                    title=repair.title,
                    ok=False,
                    detail=f"Not applicable to a {ctx.game_kind} cabinet.",
                )
            )
            continue
        _emit(progress, f"Repairing: {repair.title} …")
        try:
            outcome = repair.repair(ctx)
        except RepairError as exc:
            outcome = RepairOutcome(
                repair_id=repair.id,
                title=repair.title,
                ok=False,
                detail=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            outcome = RepairOutcome(
                repair_id=repair.id,
                title=repair.title,
                ok=False,
                detail=f"Repair failed: {exc}",
            )
        outcomes.append(outcome)
        _emit(progress, f"  {'OK' if outcome.ok else 'FAILED'}: {outcome.detail}")
    return outcomes
