"""Live Push load-time optimisations: shared exe buffer, scoped read cache,
parallel stages with an early partial result, SMB session memo."""

from __future__ import annotations

import os
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from config_scanner import read_cache
from config_scanner.read_cache import (
    cached_parse,
    open_exe_cached,
    read_exe_bytes_cached,
    run_in_scope,
    scoped_read_cache,
)
from tests.test_onehand_build_detect import _write_numeric_onehand
from tests.test_slot_setup import _fake_goldclub


@pytest.fixture(autouse=True)
def _fresh_exe_cache():
    read_cache.clear_exe_cache()
    yield
    read_cache.clear_exe_cache()


# --------------------------------------------------------------------------
# exe byte cache
# --------------------------------------------------------------------------


def test_exe_bytes_read_once_for_many_consumers(tmp_path: Path, monkeypatch) -> None:
    exe = tmp_path / "OneHand.exe"
    exe.write_bytes(b"MZ" + b"x" * 4096)
    reads = {"n": 0}
    real = Path.read_bytes

    def _counting(self: Path) -> bytes:
        reads["n"] += 1
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", _counting)

    first = read_exe_bytes_cached(exe)
    with open_exe_cached(exe) as handle:
        head = handle.read(2)
    again = read_exe_bytes_cached(exe)

    assert first is again and head == b"MZ"
    assert reads["n"] == 1


def test_exe_cache_invalidates_when_file_changes(tmp_path: Path) -> None:
    exe = tmp_path / "OneHand.exe"
    exe.write_bytes(b"MZ" + b"a" * 100)
    before = read_exe_bytes_cached(exe)
    exe.write_bytes(b"MZ" + b"b" * 200)
    # Force a different mtime even on coarse filesystems.
    st = exe.stat()
    os.utime(exe, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    after = read_exe_bytes_cached(exe)
    assert before != after and after.endswith(b"b" * 200)


def test_exe_cache_skips_oversized_and_missing_files(tmp_path: Path, monkeypatch) -> None:
    exe = tmp_path / "huge.exe"
    exe.write_bytes(b"MZ" + b"z" * 64)
    monkeypatch.setattr(read_cache, "EXE_CACHE_MAX_FILE_BYTES", 10)
    assert read_exe_bytes_cached(exe) is None
    # Falls back to a real file handle so callers still work.
    with open_exe_cached(exe) as handle:
        assert handle.read(2) == b"MZ"
    assert read_exe_bytes_cached(tmp_path / "nope.exe") is None
    with pytest.raises(OSError):
        open_exe_cached(tmp_path / "nope.exe")


def test_concurrent_first_readers_share_one_read(tmp_path: Path, monkeypatch) -> None:
    exe = tmp_path / "OneHand.exe"
    exe.write_bytes(b"MZ" + b"q" * 50_000)
    reads = {"n": 0}
    real = Path.read_bytes
    gate = threading.Event()

    def _slow(self: Path) -> bytes:
        gate.wait(2.0)
        reads["n"] += 1
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", _slow)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(read_exe_bytes_cached, exe) for _ in range(4)]
        gate.set()
        results = [f.result() for f in futures]
    assert reads["n"] == 1
    assert all(r is results[0] for r in results)


def test_onehand_detect_reads_exe_once(tmp_path: Path, monkeypatch) -> None:
    from config_scanner.build_version import detect_onehand_build
    from config_scanner.slot_setup import markets_accepted_by_onehand

    gold = tmp_path / "Goldclub"
    slot = gold / "slot"
    slot.mkdir(parents=True)
    _write_numeric_onehand(slot, ProductName="OneHand")
    reads = {"n": 0}
    real = Path.read_bytes

    def _counting(self: Path) -> bytes:
        if self.name.casefold() == "onehand.exe":
            reads["n"] += 1
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", _counting)
    opened = {"n": 0}
    real_open = Path.open

    def _open(self: Path, *args, **kwargs):
        if self.name.casefold() == "onehand.exe":
            opened["n"] += 1
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _open)

    info = detect_onehand_build(gold)
    markets_accepted_by_onehand(gold)

    assert info is not None and info.version.startswith("3.0.0")
    assert reads["n"] == 1, "OneHand.exe must cross the link once per load"
    # ``Path.read_bytes`` opens the file once itself; nothing else may.
    assert opened["n"] == 1, "no streaming open once the exe is cached"


def test_version_sniff_skipped_when_versioninfo_complete(tmp_path: Path, monkeypatch) -> None:
    from config_scanner import build_version

    slot = tmp_path / "slot"
    slot.mkdir()
    _write_numeric_onehand(slot, ProductName="OneHand")
    calls = {"n": 0}

    def _boom(path: Path):
        calls["n"] += 1
        return "", None

    monkeypatch.setattr(build_version, "_sniff_exe_version_strings", _boom)
    info = build_version._extract_version_from_onehand_exe(slot / "OneHand.exe")
    assert info.product_version
    assert calls["n"] == 0

    # Missing ProductName still triggers the sniff (it is the only source).
    _write_numeric_onehand(slot)
    read_cache.clear_exe_cache()
    build_version._extract_version_from_onehand_exe(slot / "OneHand.exe")
    assert calls["n"] == 1


# --------------------------------------------------------------------------
# scoped read cache
# --------------------------------------------------------------------------


def test_scoped_cache_parses_each_xml_once(tmp_path: Path) -> None:
    xml = tmp_path / "a.xml"
    xml.write_text("<r><v>1</v></r>", encoding="utf-8")
    parses = {"n": 0}

    def _parser(path: Path):
        parses["n"] += 1
        return ET.parse(path)

    # No scope: not memoised.
    cached_parse(xml, _parser)
    cached_parse(xml, _parser)
    assert parses["n"] == 2

    with scoped_read_cache() as scope:
        t1 = cached_parse(xml, _parser)
        t2 = cached_parse(xml, _parser)
        # Worker threads only share it when bound with run_in_scope.
        with ThreadPoolExecutor(max_workers=2) as pool:
            t3 = pool.submit(run_in_scope(cached_parse, xml, _parser)).result()
        assert t1 is t2 is t3
        assert scope.hits == 2 and scope.misses == 1
    assert parses["n"] == 3
    # Scope closed: fresh parse again.
    cached_parse(xml, _parser)
    assert parses["n"] == 4


def test_scoped_cache_memoises_goldclub_path_resolution(tmp_path: Path) -> None:
    from config_scanner import slot_setup

    gold = _fake_goldclub(tmp_path)
    rel = "slot/hwdrivers/Keyboard.xml"
    walks = {"n": 0}
    real = slot_setup._resolve_goldclub_rel_uncached

    def _counting(root: Path, relative: str):
        walks["n"] += 1
        return real(root, relative)

    slot_setup._resolve_goldclub_rel_uncached = _counting
    try:
        with scoped_read_cache():
            a = slot_setup._resolve_goldclub_rel(gold, rel)
            b = slot_setup._resolve_goldclub_rel(gold, rel)
        assert a == b and a is not None
        assert walks["n"] == 1
        slot_setup._resolve_goldclub_rel(gold, rel)
        assert walks["n"] == 2
    finally:
        slot_setup._resolve_goldclub_rel_uncached = real


def test_recipe_load_inside_scope_parses_shared_files_once(tmp_path: Path, monkeypatch) -> None:
    from config_scanner import slot_setup

    gold = _fake_goldclub(tmp_path)
    parsed: list[str] = []
    real = ET.parse

    def _counting(source, *args, **kwargs):
        parsed.append(str(source).casefold())
        return real(source, *args, **kwargs)

    monkeypatch.setattr(ET, "parse", _counting)
    with scoped_read_cache():
        slot_setup.load_recipe_from_goldclub(gold, label="live")
    assert parsed, "fixture must exercise XML readers"
    assert len(parsed) == len(set(parsed)), (
        "each XML file must be parsed once per load: "
        + ", ".join(sorted({p for p in parsed if parsed.count(p) > 1}))
    )


# --------------------------------------------------------------------------
# load_live_cabinet: parallel stages + partial callback + worker-side reads
# --------------------------------------------------------------------------


def test_load_live_cabinet_emits_partial_before_full(tmp_path: Path) -> None:
    from config_scanner.live_push import LiveLoadOutcome, load_live_cabinet

    gold = _fake_goldclub(tmp_path)
    seen: list[LiveLoadOutcome] = []
    outcome = load_live_cabinet(str(gold), on_partial=seen.append)

    assert outcome.error == "" and outcome.recipe is not None
    assert outcome.partial is False
    assert len(seen) == 1
    early = seen[0]
    assert early.partial is True
    assert early.root == outcome.root
    assert early.recipe == outcome.recipe
    assert early.status == outcome.status
    # Slow extras are not part of the early result.
    assert early.onehand_build is None and early.licence is None


def test_load_live_cabinet_carries_worker_side_results(tmp_path: Path) -> None:
    from config_scanner.live_push import load_live_cabinet

    gold = _fake_goldclub(tmp_path)
    outcome = load_live_cabinet(str(gold))
    assert outcome.error == ""
    # Fields exist and have the documented types even when the fixture has
    # no real PE / HardwareConfig.
    assert outcome.onehand_markets is None or isinstance(outcome.onehand_markets, frozenset)
    assert isinstance(outcome.ticket_printer_active, bool)


def test_load_live_cabinet_survives_partial_callback_error(tmp_path: Path) -> None:
    from config_scanner.live_push import load_live_cabinet

    gold = _fake_goldclub(tmp_path)

    def _boom(_outcome):
        raise RuntimeError("gui gone")

    outcome = load_live_cabinet(str(gold), on_partial=_boom)
    assert outcome.error == "" and outcome.recipe is not None


def test_load_live_cabinet_runs_stages_concurrently(tmp_path: Path, monkeypatch) -> None:
    """Independent reads overlap instead of running back to back."""
    import time

    from config_scanner import live_push

    gold = _fake_goldclub(tmp_path)
    delay = 0.25

    def _slow(fn):
        def _run(*args, **kwargs):
            time.sleep(delay)
            return fn(*args, **kwargs)

        return _run

    monkeypatch.setattr(live_push, "inspect_live_licences", _slow(live_push.inspect_live_licences))
    monkeypatch.setattr(live_push, "detect_onehand_build", _slow(live_push.detect_onehand_build))
    monkeypatch.setattr(
        live_push, "live_display_corruption_errors", _slow(live_push.live_display_corruption_errors)
    )
    monkeypatch.setattr(
        live_push, "read_ticket_printer_active", _slow(live_push.read_ticket_printer_active)
    )
    started = time.perf_counter()
    outcome = live_push.load_live_cabinet(str(gold))
    elapsed = time.perf_counter() - started
    assert outcome.error == ""
    # Four 250 ms stages serial = 1.0 s; concurrent should stay well under that.
    assert elapsed < 4 * delay * 0.8, f"stages ran serially ({elapsed:.2f}s)"


def test_load_live_cabinet_logs_stage_timings(tmp_path: Path, monkeypatch) -> None:
    from config_scanner import live_push

    gold = _fake_goldclub(tmp_path)
    lines: list[str] = []
    monkeypatch.setattr(live_push, "_lp_log", lines.append)
    live_push.load_live_cabinet(str(gold))
    timing = [line for line in lines if line.startswith("load ") and "total=" in line]
    assert timing, lines
    assert "recipe=" in timing[0] and "connect=" in timing[0]


# --------------------------------------------------------------------------
# SMB session memo
# --------------------------------------------------------------------------


def test_ensure_lab_smb_connects_once_per_host(monkeypatch) -> None:
    from config_scanner import live_push
    from network import lab_access

    calls: list[str] = []
    monkeypatch.setattr(lab_access, "is_lab_lan_ip", lambda host: True)
    monkeypatch.setattr(
        lab_access, "ensure_lab_smb_credential", lambda host: calls.append(host) or True
    )
    host = "10.0.0.250"
    live_push.forget_lab_smb_session(host)
    try:
        live_push._ensure_lab_smb(host)
        live_push._ensure_lab_smb(host)
        live_push._ensure_lab_smb(host.upper())
        assert calls == [host]
        live_push.forget_lab_smb_session(host)
        live_push._ensure_lab_smb(host)
        assert calls == [host, host]
    finally:
        live_push.forget_lab_smb_session(host)


def test_ensure_lab_smb_does_not_memoise_failures(monkeypatch) -> None:
    from config_scanner import live_push
    from network import lab_access

    calls: list[str] = []
    monkeypatch.setattr(lab_access, "is_lab_lan_ip", lambda host: True)
    monkeypatch.setattr(
        lab_access, "ensure_lab_smb_credential", lambda host: calls.append(host) or False
    )
    host = "10.0.0.251"
    live_push.forget_lab_smb_session(host)
    live_push._ensure_lab_smb(host)
    live_push._ensure_lab_smb(host)
    assert calls == [host, host]
