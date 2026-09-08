#!/usr/bin/env python3
"""Pull official GameStar country .b2u + staged CS trees into embedded_updates assets."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config_scanner.cs_catalog import discover_leaves, resolve_country_selector_tool  # noqa: E402
from config_scanner.embedded_updates import EmbeddedUpdate, write_catalog  # noqa: E402

SHARE_GS201 = Path(r"//10.0.0.249/WinSystems_SLOT/GameStar 2.0.1/Country Selectors")
SHARE_GS30 = Path(r"//10.0.0.249/WinSystems_SLOT/GameStar+30")
SHARE_B2U = Path(r"//10.0.0.249/WinSystems_SLOT/_B2U")
SHARE_USB91_B2U = Path(r"//10.0.0.91/usb/_B2U")
SHARE_USB91_ENC = SHARE_USB91_B2U / "encrypted"
ASSETS = _ROOT / "config_scanner" / "assets" / "embedded_updates"


def _copy_b2u(src: Path, dest_name: str) -> None:
    if not src.is_file():
        print(f"  skip b2u missing: {src}")
        return
    dest = ASSETS / "b2u" / dest_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print(f"  b2u {dest_name} ({dest.stat().st_size} bytes)")


def _stage_tool(src_root: Path, staged_id: str) -> int:
    tool = resolve_country_selector_tool(src_root)
    leaves = discover_leaves(tool)
    dest = ASSETS / "staged" / staged_id / "CountrySelectorTool"
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(tool, dest)
    print(f"  staged {staged_id} ({len(leaves)} leaves)")
    return len(leaves)


def sync_embedded(*, skip_staged: bool = False) -> list[EmbeddedUpdate]:
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "b2u").mkdir(exist_ok=True)
    entries: list[EmbeddedUpdate] = []

    # Trinidad TT-00 — official GameStar 2.0.1 .b2u
    tt00_b2u = SHARE_GS201 / "Trinidad" / "CS-Gamestar-TT-00.b2u"
    _copy_b2u(tt00_b2u, "CS-Gamestar-TT-00.b2u")
    leaf_note = ""
    if not skip_staged and tt00_b2u.is_file():
        from config_scanner.b2u_pack import default_package_generator, extract_b2u_update

        if default_package_generator() is not None:
            pkg = extract_b2u_update(
                tt00_b2u,
                work_parent=ASSETS / "_sync_cache",
                reuse_cache=False,
            )
            _stage_tool(pkg, "CS-Gamestar-TT-00")
            leaves = discover_leaves(
                ASSETS / "staged" / "CS-Gamestar-TT-00" / "CountrySelectorTool"
            )
            if leaves:
                leaf_note = leaves[0].readme
    entries.append(
        EmbeddedUpdate(
            id="CS-Gamestar-TT-00",
            label="Trinidad TT-00 (Gamestar 2.0.1)",
            country="Trinidad",
            gamestar_version="2.0.1",
            b2u_file="CS-Gamestar-TT-00.b2u",
            staged_id="CS-Gamestar-TT-00",
            readme=leaf_note,
        )
    )

    # TRI-00 overlays from _B2U (unpacked CS packages)
    for pkg_id, label in (
        ("CS-Gamestar-TRI-00_SAS", "Trinidad TRI-00 SAS"),
        ("CS-Gamestar-TRI-00_OL+SAS", "Trinidad TRI-00 OL+SAS"),
    ):
        src = SHARE_B2U / pkg_id
        if skip_staged or not src.is_dir():
            print(f"  skip staged {pkg_id}")
        else:
            try:
                _stage_tool(src, pkg_id)
            except (OSError, FileNotFoundError, ValueError) as exc:
                print(f"  staged {pkg_id} failed: {exc}")
        entries.append(
            EmbeddedUpdate(
                id=pkg_id,
                label=label,
                country="Trinidad",
                gamestar_version="TRI-00",
                b2u_file=None,
                staged_id=pkg_id,
            )
        )

    # TRI-01 official .b2u from GameStar share
    for name in ("CS-Gamestar-TRI-01.b2u", "CS-Gamestar-TRI-01_SAS.b2u"):
        src = SHARE_GS201 / "Trinidad" / name
        pkg_id = Path(name).stem
        _copy_b2u(src, name)
        entries.append(
            EmbeddedUpdate(
                id=pkg_id,
                label=f"Trinidad {pkg_id.replace('CS-Gamestar-', '')}",
                country="Trinidad",
                gamestar_version="TRI-01",
                b2u_file=name if src.is_file() else None,
                staged_id=None,
            )
        )

    # Official TRI-00 .b2u (USB 10.0.0.91 encrypted; 249 may also have it)
    tri00 = SHARE_USB91_ENC / "CS-Gamestar-TRI-00.b2u"
    if not tri00.is_file():
        tri00 = SHARE_B2U / "encrypted" / "CS-Gamestar-TRI-00.b2u"
    _copy_b2u(tri00, "CS-Gamestar-TRI-00.b2u")
    entries.append(
        EmbeddedUpdate(
            id="CS-Gamestar-TRI-00",
            label="Trinidad TRI-00",
            country="Trinidad",
            gamestar_version="TRI-00",
            b2u_file="CS-Gamestar-TRI-00.b2u" if tri00.is_file() else None,
            staged_id="CS-Gamestar-TRI-00",
        )
    )

    # Compact official .b2u from USB encrypted (skip 35 MB PR-04/PR-05)
    for country, fname, short, ver, readme in (
        ("PuertoRico", "CS-Gamestar-PR-00.b2u", "PR-00", "PR-00", "Gamestar PuertoRico 1c 94 500Limit OL Ticket + SAS"),
        ("PuertoRico", "CS-Gamestar-PR-01.b2u", "PR-01", "PR-01", "Gamestar PuertoRico 1c 94 500Limit OL Ticket + SAS"),
        ("PuertoRico", "CS-Gamestar-PR-02.b2u", "PR-02", "PR-02", "Gamestar PuertoRico 1c 92-94 / 94 500Limit OL Ticket + SAS"),
        ("PuertoRico", "CS-Gamestar-PR-03.b2u", "PR-03", "PR-03", "Gamestar PuertoRico 1c 92-94 / 94 500Limit OL Ticket + SAS"),
        ("Panama", "CS-Gamestar-PANC-00.b2u", "PANC-00", "PANC-00", ""),
        ("Panama", "CS-Gamestar-PANC-01.b2u", "PANC-01", "PANC-01", ""),
        ("Peru", "CS-Gamestar-PER-00.b2u", "PER-00", "PER-00", "Official Peru CS overlay"),
    ):
        src = SHARE_USB91_ENC / fname
        if not src.is_file():
            src = SHARE_B2U / "encrypted" / fname
        if not src.is_file():
            src = SHARE_GS201 / country / fname
        _copy_b2u(src, fname)
        entries.append(
            EmbeddedUpdate(
                id=Path(fname).stem,
                label=f"{country} {short}",
                country=country,
                gamestar_version=ver,
                b2u_file=fname if src.is_file() else None,
                staged_id=Path(fname).stem,
                readme=readme,
            )
        )

    # Newest PR + South Africa — unpacked CS trees on USB (no compact official .b2u)
    for pkg_id, label, country, ver, readme in (
        (
            "CS-Gamestar-PR-06",
            "Puerto Rico PR-06",
            "PuertoRico",
            "PR-06",
            "Gamestar PuertoRico 1c 92-94 / 94 500Limit OL Ticket + SAS",
        ),
        (
            "CS-Gamestar-PR-06_SAS",
            "Puerto Rico PR-06 SAS",
            "PuertoRico",
            "PR-06",
            "Gamestar PuertoRico 1c 92-94 / 94 SAS",
        ),
        (
            "CS-Gamestar-SA-00",
            "South Africa SA-00",
            "South Africa",
            "SA-00",
            "Gamestar2 South Africa 1c 94 Limit 500 SAS 3Screens - Axiomtek GMB140",
        ),
    ):
        src = SHARE_USB91_B2U / pkg_id
        if skip_staged or not src.is_dir():
            print(f"  skip staged {pkg_id}")
        else:
            try:
                _stage_tool(src, pkg_id)
            except (OSError, FileNotFoundError, ValueError) as exc:
                print(f"  staged {pkg_id} failed: {exc}")
        entries.append(
            EmbeddedUpdate(
                id=pkg_id,
                label=label,
                country=country,
                gamestar_version=ver,
                b2u_file=None,
                staged_id=pkg_id,
                readme=readme,
            )
        )

    # Jamaica / large PR-05 — .b2u only when present on 249 (not on USB 91)
    for country, files in (
        (
            "Jamaica",
            (
                ("CS-Gamestar-JAM-00.b2u", "JAM-00"),
                ("CS-Gamestar-JAM-01.b2u", "JAM-01"),
            ),
        ),
        (
            "PuertoRico",
            (
                ("CS-Gamestar-PR-05.b2u", "PR-05"),
                ("CS-Gamestar-PR-05_SAS.b2u", "PR-05 SAS"),
            ),
        ),
    ):
        for fname, short in files:
            src = SHARE_GS201 / country / fname
            pkg_id = Path(fname).stem
            _copy_b2u(src, fname)
            if src.is_file():
                entries.append(
                    EmbeddedUpdate(
                        id=pkg_id,
                        label=f"{country} {short}",
                        country=country,
                        gamestar_version="2.0.1",
                        b2u_file=fname,
                        staged_id=None,
                    )
                )

    write_catalog(entries)
    cache = ASSETS / "_sync_cache"
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
    print(f"catalog: {len(entries)} entries -> {ASSETS / 'catalog.json'}")
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-staged",
        action="store_true",
        help="Only copy .b2u files (no CountrySelectorTool trees)",
    )
    args = parser.parse_args()
    try:
        sync_embedded(skip_staged=args.skip_staged)
    except OSError as exc:
        print(f"sync failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
