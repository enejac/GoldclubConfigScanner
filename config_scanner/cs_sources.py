"""Country Selector sources: embedded catalog, lab share (249), and local paths.

GameStar ships two update shapes on the lab share:

* **CS .b2u** (GameStar 2.0.0 / 2.0.1 ``Country Selectors``, ``_B2U``) —
  ``updateDecrypt`` → ``Content/tmp/CountrySelectorTool`` (authoring / leaf
  probe / export).
* **GS+22 / GS+30 GameUpdate .zip** — ``gameDecrypt`` → ``Meta/meta.xml`` only
  (cabinet apply package, **not** a CS overlay tree).

JinLong ``.ws`` packages, disk ``.mrimg`` images, and other slot brands on the
same share are out of scope for Create.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from config_scanner.cs_catalog import discover_leaves, resolve_country_selector_tool
from config_scanner.embedded_updates import EmbeddedUpdate, load_catalog, materialize_country_tool
from config_scanner.net_gate import (
    clear_reachability_cache,
    offline_note,
    remote_path_available,
    unc_host,
    unreachable_hosts,
)

_SHARE_ROOT = Path("//10.0.0.249/WinSystems_SLOT")
_SHARE_GS201 = _SHARE_ROOT / "GameStar 2.0.1/Country Selectors"
_SHARE_GS200 = _SHARE_ROOT / "GameStar 2.0.0/Country Selectors"
_SHARE_GS201_UPDATES = _SHARE_ROOT / "GameStar 2.0.1/Updates"
_SHARE_GS22 = _SHARE_ROOT / "GameStar+22"
_SHARE_GS30 = _SHARE_ROOT / "GameStar+30"
_SHARE_B2U = _SHARE_ROOT / "_B2U"
_SHARE_B2U_ENC = _SHARE_B2U / "encrypted"
_SHARE_USB91_B2U = Path("//10.0.0.91/usb/_B2U")
_SHARE_USB91_ENC = _SHARE_USB91_B2U / "encrypted"
_SHARE_KEYBOARDS = _SHARE_ROOT / "Keyboard Updates"
_SHARE_BILLS = _SHARE_ROOT / "_BILLS"
_SHARE_JINLONG = _SHARE_ROOT / "JinLong"

_SHARE_SCAN_CACHE: list[CsSource] | None = None

_GAMEUPDATE_RE = re.compile(
    r"GameUpdate\.Slot\.CountrySelector_.*\.zip$", re.IGNORECASE
)


class CsSourceKind(str, Enum):
    EMBEDDED = "embedded"
    SHARE_B2U = "share_b2u"
    SHARE_FOLDER = "share_folder"
    SHARE_GAMEUPDATE = "share_gameupdate"
    LOCAL = "local"


@dataclass(frozen=True)
class CsSource:
    """One selectable Country Selector source for the create wizard."""

    id: str
    label: str
    country: str
    gamestar_line: str
    kind: CsSourceKind
    path: Path | None = None
    embedded_id: str | None = None
    authoring: bool = True
    note: str = ""

    @property
    def group(self) -> str:
        if self.kind == CsSourceKind.EMBEDDED:
            return "Built-in (offline USB)"
        if self.gamestar_line == "GS+30":
            return "GameStar+30 share (cabinet apply)"
        if self.gamestar_line == "GS+22":
            return "GameStar+22 share (cabinet apply)"
        if self.gamestar_line.startswith("2.0"):
            return f"GameStar {self.gamestar_line} share"
        if self.kind == CsSourceKind.SHARE_FOLDER or self.gamestar_line == "overlay":
            return "Lab share (_B2U unpacked)"
        return "Other"


def is_game_update_zip(path: Path) -> bool:
    name = Path(path).name
    return bool(_GAMEUPDATE_RE.match(name)) or (
        name.casefold().startswith("gameupdate.slot.countryselector")
        and Path(path).suffix.casefold() == ".zip"
    )


def is_b2u_path(path: Path) -> bool:
    return Path(path).is_file() and Path(path).suffix.casefold() == ".b2u"


def _norm_country(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").casefold())


_COUNTRY_TOKENS: tuple[tuple[str, str], ...] = (
    ("JAM", "Jamaica"),
    ("PRU", "Peru"),
    ("PER", "Peru"),  # PER before PR — CS-Gamestar-PER-00 is Peru, not PuertoRico
    ("PAN", "Panama"),
    ("COL", "Colombia"),
    ("GUY", "Guyana"),
    ("MEX", "Mexico"),
    ("ARG", "Argentina"),
    ("PGY", "Paraguay"),
    ("PAR", "Paraguay"),
    ("RSA", "South Africa"),
    ("ZAR", "South Africa"),
    ("KNA", "St. Kitts & Nevis"),
    ("TRI", "Trinidad"),
    ("TT", "Trinidad"),
    ("PR", "PuertoRico"),
)

# ``SA`` is not a substring token — it would match ``_SAS`` (Trinidad SAS packs).
_SA_PACK_RE = re.compile(r"(?:^|[-_])SA(?:[-_]\d|$)", re.IGNORECASE)


def country_from_b2u_folder_name(name: str) -> str:
    """Map a ``CS-Gamestar-*`` folder or file stem to a jurisdiction country."""
    upper = (name or "").upper()
    for token, country in _COUNTRY_TOKENS:
        if token in upper:
            return country
    if _SA_PACK_RE.search(upper):
        return "South Africa"
    return "Trinidad"


def country_matches_profile(profile_country: str, source_country: str) -> bool:
    a = _norm_country(profile_country)
    b = _norm_country(source_country)
    if not a or not b:
        return True
    if a in b or b in a:
        return True
    # Trinidad&Tobago vs Trinidad vs Live Push combo ``TT``
    if a in {"tt", "trinidadtobago"} and "trinidad" in b:
        return True
    if b in {"tt", "trinidadtobago"} and "trinidad" in a:
        return True
    if "trinidad" in a and "trinidad" in b:
        return True
    if "puertorico" in a and "puertorico" in b:
        return True
    return a == b


NOT_SHIPPED_NOTE = (
    "Not shipped in this build: no bundled .b2u and no staged tree. "
    "Copy embedded_updates\\staged\\{id}\\CountrySelectorTool beside ConfigScanner.exe "
    "(or the official .b2u) to use it offline."
)


def embedded_entry_has_payload(entry: EmbeddedUpdate) -> bool:
    """True when the catalog entry can actually be opened on this PC."""
    try:
        return entry.staged_tool_path is not None or entry.b2u_path is not None
    except OSError:
        return False


def source_is_materializable(source: CsSource) -> bool:
    """True when ``resolve_cs_source`` can open this entry without a modal failure.

    Embedded entries need a staged tree or bundled ``.b2u`` on this PC; share
    paths need a reachable host *and* an existing file/folder.
    """
    if source.kind == CsSourceKind.EMBEDDED:
        if not source.embedded_id:
            return False
        from config_scanner.embedded_updates import find_embedded_update

        entry = find_embedded_update(source.embedded_id)
        return entry is not None and embedded_entry_has_payload(entry)
    path = source.path
    if path is None:
        return False
    if not remote_path_available(path):
        return False
    try:
        return path.is_file() or path.is_dir()
    except OSError:
        return False


def share_hosts() -> tuple[str, ...]:
    """Hosts the CS source catalog may touch (for reachability notes)."""
    hosts: list[str] = []
    for root in (_SHARE_ROOT, _SHARE_USB91_B2U):
        host = unc_host(root)
        if host and host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def share_offline_note() -> str:
    """Inline note when a lab share host was probed and is down ('' when all up)."""
    known = {h.casefold() for h in share_hosts()}
    down = [h for h in unreachable_hosts() if h.casefold() in known]
    return offline_note(down)


def share_browse_start(preferred: str | Path, fallback: str = "") -> str:
    """Start folder for a file dialog: *preferred* only when its host answers.

    A native Windows file dialog pointed at a dead UNC path blocks the GUI
    thread while the redirector times out, so fall back to a local folder.
    """
    if remote_path_available(preferred):
        return str(preferred)
    if fallback:
        return fallback
    return str(Path.home())


def pick_cs_source_for_export(
    market: str,
    *,
    profile_id: str = "",
    sources: Sequence[CsSource] | None = None,
) -> CsSource | None:
    """Authoring CS pack for Export CS (embedded Trinidad counts; ``TT`` maps)."""
    pool = [
        s
        for s in (sources if sources is not None else list_cs_sources())
        if s.authoring
    ]
    if market:
        matched = [s for s in pool if country_matches_profile(market, s.country)]
        search = matched if matched else pool
    else:
        search = pool
    usable = [s for s in search if source_is_materializable(s)]
    return recommend_cs_source(usable, profile_id=profile_id, include_debug=False)


def share_shortcuts() -> tuple[tuple[str, Path], ...]:
    return (
        ("GameStar 2.0.1 Country Selectors", _SHARE_GS201),
        ("GameStar 2.0.0 Country Selectors", _SHARE_GS200),
        ("GameStar 2.0.1 Updates (companions)", _SHARE_GS201_UPDATES),
        ("GameStar+30 (cabinet apply)", _SHARE_GS30),
        ("GameStar+22 (cabinet apply)", _SHARE_GS22),
        ("_B2U overlays", _SHARE_B2U),
        ("USB 10.0.0.91 _B2U", _SHARE_USB91_B2U),
        ("Keyboard Updates", _SHARE_KEYBOARDS),
        ("_BILLS (JCM / MEI)", _SHARE_BILLS),
        ("JinLong (different product)", _SHARE_JINLONG),
    )


def companion_share_shortcuts() -> tuple[tuple[str, Path], ...]:
    return (
        ("_B2U companions", _SHARE_B2U),
        ("USB 10.0.0.91 _B2U", _SHARE_USB91_B2U),
        ("GameStar 2.0.1 Updates", _SHARE_GS201_UPDATES),
        ("Keyboard Updates", _SHARE_KEYBOARDS),
        ("_BILLS", _SHARE_BILLS),
    )


def clear_share_scan_cache() -> None:
    global _SHARE_SCAN_CACHE
    _SHARE_SCAN_CACHE = None
    clear_reachability_cache()


def _listdir(root: Path) -> list[Path]:
    if not remote_path_available(root):
        return []
    try:
        if not root.is_dir():
            return []
        return sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []


def is_debug_or_test_pack(source: CsSource) -> bool:
    """True for lab Debug/Test overlays that operators should not pick by default."""
    blob = " ".join(
        [
            source.id,
            source.label,
            source.path.name if source.path else "",
            source.path.stem if source.path else "",
        ]
    ).upper()
    return "DEBUG" in blob or "TEST" in blob


_PACK_VER_RE = re.compile(
    r"(TRI|TT|JAM|PRU|PER|PANC|PR|COL|GUY|MEX|SA)-(\d+)",
    re.IGNORECASE,
)

_GROUP_ORDER = (
    "Built-in (offline USB)",
    "GameStar 2.0.1 share",
    "GameStar 2.0.0 share",
    "Lab share (_B2U unpacked)",
    "GameStar+30 share (cabinet apply)",
    "GameStar+22 share (cabinet apply)",
    "Other",
)


def sort_cs_sources(sources: Sequence[CsSource]) -> list[CsSource]:
    def _key(src: CsSource) -> tuple[int, str]:
        try:
            gi = _GROUP_ORDER.index(src.group)
        except ValueError:
            gi = 99
        return (gi, src.label.casefold())

    return sorted(sources, key=_key)


def recommend_cs_source(
    sources: Sequence[CsSource],
    *,
    profile_id: str = "",
    include_debug: bool = False,
) -> CsSource | None:
    """Newest sensible authoring pack for this market (official line, matching SAS)."""
    pool = [s for s in sources if s.authoring]
    if not include_debug:
        filtered = [s for s in pool if not is_debug_or_test_pack(s)]
        if filtered:
            pool = filtered
    if not pool:
        return None
    sas_only = "sas_only" in (profile_id or "").casefold()

    def _score(src: CsSource) -> tuple:
        name = f"{src.path.name if src.path else ''} {src.label}".upper()
        debug = is_debug_or_test_pack(src)
        has_ol = "OL+SAS" in name or "OL SAS" in name or "OL_SAS" in name
        has_sas_suffix = bool(re.search(r"_SAS\b", name))
        if sas_only:
            sas_score = 2 if has_sas_suffix and not has_ol else (1 if has_sas_suffix else 0)
        else:
            sas_score = 2 if has_ol else (0 if has_sas_suffix else 1)
        tri_bonus = 1 if "TRI-" in name else 0
        match = _PACK_VER_RE.search(name.replace(" ", ""))
        ver = int(match.group(2)) if match else 0
        line_rank = {
            "2.0.1": 80,
            "2.0.0": 70,
            "overlay": 55,
            "embedded": 50,
        }.get(src.gamestar_line, 10)
        if src.kind == CsSourceKind.EMBEDDED:
            line_rank = 50
        return (0 if debug else 1, ver, sas_score, tri_bonus, line_rank)

    return max(pool, key=_score)


def _share_line_b2u_entries(root: Path, line: str) -> list[CsSource]:
    out: list[CsSource] = []
    for country_dir in _listdir(root):
        if not country_dir.is_dir():
            continue
        country = country_dir.name
        for child in _listdir(country_dir):
            if not is_b2u_path(child):
                continue
            out.append(
                CsSource(
                    id=f"share-b2u-{line}-{child.stem}",
                    label=f"{country} — {child.name}",
                    country=country,
                    gamestar_line=line,
                    kind=CsSourceKind.SHARE_B2U,
                    path=child,
                    authoring=True,
                )
            )
    return out


def _share_b2u_folder_entries(
    root: Path | None = None, *, id_prefix: str = "share-folder"
) -> list[CsSource]:
    out: list[CsSource] = []
    for child in _listdir(root or _SHARE_B2U):
        if not child.is_dir():
            continue
        if not child.name.upper().startswith("CS-GAMESTAR"):
            continue
        country = country_from_b2u_folder_name(child.name)
        out.append(
            CsSource(
                id=f"{id_prefix}-{child.name}",
                label=f"_B2U — {child.name}",
                country=country,
                gamestar_line="overlay",
                kind=CsSourceKind.SHARE_FOLDER,
                path=child,
                authoring=True,
            )
        )
    return out


def _share_encrypted_cs_entries(
    root: Path | None = None, *, id_prefix: str = "share-enc"
) -> list[CsSource]:
    out: list[CsSource] = []
    for child in _listdir(root or _SHARE_B2U_ENC):
        if not is_b2u_path(child):
            continue
        if not child.stem.upper().startswith("CS-GAMESTAR"):
            continue
        country = country_from_b2u_folder_name(child.stem)
        out.append(
            CsSource(
                id=f"{id_prefix}-{child.stem}",
                label=f"_B2U encrypted — {child.name}",
                country=country,
                gamestar_line="overlay",
                kind=CsSourceKind.SHARE_B2U,
                path=child,
                authoring=True,
            )
        )
    return out


def _share_gameupdate_entries(root: Path, line: str) -> list[CsSource]:
    note = (
        f"{line} game package — cabinet apply only (Meta/meta.xml). "
        "Use a GameStar 2.0.x / _B2U Country Selector .b2u to Create."
    )
    out: list[CsSource] = []
    for country_dir in _listdir(root):
        if not country_dir.is_dir():
            continue
        country = country_dir.name
        for child in _listdir(country_dir):
            if not is_game_update_zip(child):
                continue
            if "DEMO" in child.name.upper():
                continue
            out.append(
                CsSource(
                    id=f"share-{line.lower()}-{child.stem}",
                    label=f"{country} — {child.name}",
                    country=country,
                    gamestar_line=line,
                    kind=CsSourceKind.SHARE_GAMEUPDATE,
                    path=child,
                    authoring=False,
                    note=note,
                )
            )
    return out


def _scanned_share_sources() -> list[CsSource]:
    global _SHARE_SCAN_CACHE
    if _SHARE_SCAN_CACHE is not None:
        return _SHARE_SCAN_CACHE
    collected: list[CsSource] = []
    collected.extend(_share_line_b2u_entries(_SHARE_GS201, "2.0.1"))
    collected.extend(_share_line_b2u_entries(_SHARE_GS200, "2.0.0"))
    collected.extend(_share_b2u_folder_entries())
    collected.extend(_share_encrypted_cs_entries())
    collected.extend(_share_b2u_folder_entries(_SHARE_USB91_B2U, id_prefix="usb91-folder"))
    collected.extend(_share_encrypted_cs_entries(_SHARE_USB91_ENC, id_prefix="usb91-enc"))
    collected.extend(_share_gameupdate_entries(_SHARE_GS30, "GS+30"))
    collected.extend(_share_gameupdate_entries(_SHARE_GS22, "GS+22"))
    _SHARE_SCAN_CACHE = collected
    return collected


_CURATED_SHARE: tuple[CsSource, ...] = (
    # Trinidad 2.0.1
    CsSource(
        id="share-tri-01",
        label="Trinidad TRI-01 OL+SAS",
        country="Trinidad",
        gamestar_line="2.0.1",
        kind=CsSourceKind.SHARE_B2U,
        path=_SHARE_GS201 / "Trinidad" / "CS-Gamestar-TRI-01.b2u",
        authoring=True,
    ),
    CsSource(
        id="share-tri-01-sas",
        label="Trinidad TRI-01 SAS",
        country="Trinidad",
        gamestar_line="2.0.1",
        kind=CsSourceKind.SHARE_B2U,
        path=_SHARE_GS201 / "Trinidad" / "CS-Gamestar-TRI-01_SAS.b2u",
        authoring=True,
    ),
    CsSource(
        id="share-tt-00",
        label="Trinidad TT-00",
        country="Trinidad",
        gamestar_line="2.0.1",
        kind=CsSourceKind.SHARE_B2U,
        path=_SHARE_GS201 / "Trinidad" / "CS-Gamestar-TT-00.b2u",
        authoring=True,
    ),
    # Jamaica
    CsSource(
        id="share-jam-00",
        label="Jamaica JAM-00",
        country="Jamaica",
        gamestar_line="2.0.1",
        kind=CsSourceKind.SHARE_B2U,
        path=_SHARE_GS201 / "Jamaica" / "CS-Gamestar-JAM-00.b2u",
        authoring=True,
    ),
    CsSource(
        id="share-jam-01",
        label="Jamaica JAM-01",
        country="Jamaica",
        gamestar_line="2.0.1",
        kind=CsSourceKind.SHARE_B2U,
        path=_SHARE_GS201 / "Jamaica" / "CS-Gamestar-JAM-01.b2u",
        authoring=True,
    ),
    # Puerto Rico
    CsSource(
        id="share-pr-05",
        label="Puerto Rico PR-05",
        country="PuertoRico",
        gamestar_line="2.0.1",
        kind=CsSourceKind.SHARE_B2U,
        path=_SHARE_GS201 / "PuertoRico" / "CS-Gamestar-PR-05.b2u",
        authoring=True,
    ),
    CsSource(
        id="share-pr-05-sas",
        label="Puerto Rico PR-05 SAS",
        country="PuertoRico",
        gamestar_line="2.0.1",
        kind=CsSourceKind.SHARE_B2U,
        path=_SHARE_GS201 / "PuertoRico" / "CS-Gamestar-PR-05_SAS.b2u",
        authoring=True,
    ),
    # GS+30 Trinidad (apply-only reference)
    CsSource(
        id="share-gs30-tt-ol",
        label="Trinidad GS+30 30100 OL+SAS",
        country="Trinidad&Tobago",
        gamestar_line="GS+30",
        kind=CsSourceKind.SHARE_GAMEUPDATE,
        path=_SHARE_GS30
        / "Trinidad&Tobago"
        / "GameUpdate.Slot.CountrySelector_GS+30_30100_T&T_OL+SAS_Win10.zip",
        authoring=False,
        note="Cabinet apply only (not CS overlay tree).",
    ),
    CsSource(
        id="share-gs30-col-3050",
        label="Colombia GS+30 3050",
        country="Colombia",
        gamestar_line="GS+30",
        kind=CsSourceKind.SHARE_GAMEUPDATE,
        path=_SHARE_GS30
        / "Colombia"
        / "GameUpdate.Slot.CountrySelector_GS+30_3050_V1_COL_Win10.zip",
        authoring=False,
        note="Cabinet apply only (not CS overlay tree).",
    ),
    CsSource(
        id="share-gs30-pan-30100-ol",
        label="Panama GS+30 30100 OL+SAS",
        country="Panama",
        gamestar_line="GS+30",
        kind=CsSourceKind.SHARE_GAMEUPDATE,
        path=_SHARE_GS30
        / "Panama"
        / "GameUpdate.Slot.CountrySelector_GS+30_30100_PAN_OL+SAS_Win10.zip",
        authoring=False,
        note="Cabinet apply only (not CS overlay tree).",
    ),
    CsSource(
        id="share-panc-01-200",
        label="Panama PANC-01 (GameStar 2.0.0)",
        country="Panama",
        gamestar_line="2.0.0",
        kind=CsSourceKind.SHARE_B2U,
        path=_SHARE_GS200 / "Panama" / "CS-Gamestar-PANC-01.b2u",
        authoring=True,
        note="Official GameStar 2.0.0 Panama overlay. 2.0.1 Country Selectors/Panama is empty.",
    ),
    CsSource(
        id="share-pr-04-200",
        label="Puerto Rico PR-04 (GameStar 2.0.0)",
        country="PuertoRico",
        gamestar_line="2.0.0",
        kind=CsSourceKind.SHARE_B2U,
        path=_SHARE_GS200 / "PuertoRico" / "CS-Gamestar-PR-04.b2u",
        authoring=True,
    ),
    CsSource(
        id="share-per-00-enc",
        label="Peru PER-00 (_B2U encrypted)",
        country="Peru",
        gamestar_line="overlay",
        kind=CsSourceKind.SHARE_B2U,
        path=_SHARE_B2U_ENC / "CS-Gamestar-PER-00.b2u",
        authoring=True,
        note="Official Peru CS overlay. Prefer this over PRU-00_Debug.",
    ),
)


def _embedded_sources() -> list[CsSource]:
    """Catalog entries; ones with no payload on this PC are listed but not authoring.

    The catalog names every official pack, but the exe only bundles the
    ``.b2u`` files and staged trees live beside the exe on USB. An entry with
    neither (e.g. PR-06 on a bare install) used to be *recommended* and then
    failed with a modal "no staged tree or .b2u" the moment the wizard opened
    step 2. Mark it so the wizard greys it out and skips it.
    """
    out: list[CsSource] = []
    for entry in load_catalog():
        shipped = embedded_entry_has_payload(entry)
        note = entry.readme or ""
        if not shipped:
            missing = NOT_SHIPPED_NOTE.format(id=entry.id)
            note = f"{missing}\n{note}" if note else missing
        out.append(
            CsSource(
                id=f"embedded-{entry.id}",
                label=entry.label,
                country=entry.country,
                gamestar_line=entry.gamestar_version or "embedded",
                kind=CsSourceKind.EMBEDDED,
                embedded_id=entry.id,
                authoring=shipped,
                note=note,
            )
        )
    return out


def source_is_not_shipped(source: CsSource) -> bool:
    """True for a catalog entry whose payload is missing on this PC."""
    return (
        source.kind == CsSourceKind.EMBEDDED
        and not source.authoring
        and source.note.startswith("Not shipped in this build")
    )


def list_cs_sources(
    *,
    profile_country: str | None = None,
    authoring_only: bool = True,
    include_share_scan: bool = False,
) -> list[CsSource]:
    """All known CS sources (embedded + curated share + optional live scan)."""
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    out: list[CsSource] = []

    def _add(src: CsSource) -> None:
        if src.id in seen_ids:
            return
        if src.path is not None:
            key = str(src.path).replace("\\", "/").casefold()
            if key in seen_paths:
                return
            seen_paths.add(key)
        if authoring_only and not src.authoring:
            return
        if profile_country and not country_matches_profile(profile_country, src.country):
            return
        seen_ids.add(src.id)
        out.append(src)

    for src in _embedded_sources():
        _add(src)
    for src in _CURATED_SHARE:
        if src.path is None:
            _add(src)
            continue
        if not remote_path_available(src.path):
            continue
        try:
            if src.path.is_file() or src.path.is_dir():
                _add(src)
        except OSError:
            continue
    if include_share_scan:
        for src in _scanned_share_sources():
            _add(src)
    return sort_cs_sources(out)


def resolve_cs_source(source: CsSource) -> Path:
    """Materialize *source* to a CountrySelectorTool path."""
    if source.kind == CsSourceKind.EMBEDDED:
        if not source.embedded_id:
            raise ValueError("embedded source missing embedded_id")
        from config_scanner.embedded_updates import find_embedded_update

        entry = find_embedded_update(source.embedded_id)
        if entry is None:
            raise FileNotFoundError(f"embedded update {source.embedded_id} not in catalog")
        return materialize_country_tool(entry)
    if source.path is None:
        raise FileNotFoundError(f"source {source.id} has no path")
    return materialize_cs_path(source.path)


def materialize_cs_path(path: Path) -> Path:
    """Open a folder, .b2u, or GameUpdate zip as CountrySelectorTool.

    Never raises on partial decrypt layouts without a clear message; always
    returns a tool with ``data/`` or raises ``FileNotFoundError`` / ``ValueError``.
    """
    path = Path(path)
    host = unc_host(path)
    if host and not remote_path_available(path):
        raise FileNotFoundError(
            f"\\\\{host} is not reachable (SMB port 445 did not answer) — cannot open {path.name}. "
            "Connect to the lab network or use a built-in pack."
        )
    if not path.exists():
        raise FileNotFoundError(f"not found: {path}")

    try:
        if path.is_dir():
            return resolve_country_selector_tool(path)

        if is_b2u_path(path):
            from config_scanner.b2u_pack import extract_b2u_update
            from config_scanner.pack_detect import detect_pack

            try:
                package = extract_b2u_update(path, reuse_cache=True)
            except (OSError, RuntimeError, FileNotFoundError) as exc:
                raise FileNotFoundError(
                    f"Could not decrypt {path.name}: {exc}\n"
                    "Need BiOS2_PackageGenerator.exe in the tools folder next to ConfigScanner."
                ) from exc
            detected = detect_pack(package)
            if detected.kind.value == "country" and (detected.root / "data").is_dir():
                return detected.root
            # Fallback: deep resolve under package
            try:
                return resolve_country_selector_tool(package)
            except FileNotFoundError as exc:
                raise FileNotFoundError(
                    f"{path.name} decrypted but no CountrySelectorTool/data found "
                    f"({detected.detail})"
                ) from exc

        if is_game_update_zip(path):
            from config_scanner.b2u_pack import extract_game_update, game_update_authoring_note

            try:
                package = extract_game_update(path, reuse_cache=True)
            except (OSError, RuntimeError, FileNotFoundError, ValueError) as exc:
                raise FileNotFoundError(
                    f"Could not decrypt GameUpdate {path.name}: {exc}"
                ) from exc
            if not game_update_has_country_selector(package):
                raise FileNotFoundError(game_update_authoring_note(path))
            return resolve_country_selector_tool(package)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise FileNotFoundError(f"Failed to open Country Selector source {path}: {exc}") from exc

    raise ValueError(f"unsupported Country Selector source: {path}")


def game_update_has_country_selector(package_dir: Path) -> bool:
    """True when a decrypted game update contains CS ``data/`` leaves."""
    try:
        tool = resolve_country_selector_tool(package_dir)
        return any(discover_leaves(tool))
    except (OSError, FileNotFoundError, ValueError):
        return False


def load_leaves_for_source(source: CsSource) -> tuple[Path, list]:
    """Resolve source and return (tool_path, leaves)."""
    tool = resolve_cs_source(source)
    leaves = discover_leaves(tool)
    if not leaves:
        raise FileNotFoundError(f"No install.json leaves under {tool}")
    return tool, leaves
