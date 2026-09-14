"""config.json is the install folder only — game trees live in profiles.json."""

from __future__ import annotations

import json
from pathlib import Path

from config_scanner.paths import bundled_assets_root, load_tool_config

_TOOL_ONLY_KEYS = frozenset({"snapshotsDir", "reportsDir", "parallelWorkers"})


def test_bundled_config_json_is_tool_folder_only() -> None:
    data = json.loads((bundled_assets_root() / "config.json").read_text(encoding="utf-8"))
    assert set(data) == _TOOL_ONLY_KEYS
    assert data["snapshotsDir"] == "snapshots"
    assert data["reportsDir"] == "reports"
    assert data["parallelWorkers"] == 8


def test_load_tool_config_does_not_invent_a_roulette_path(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    cfg = load_tool_config(tmp_path)
    assert cfg.game_drive is None
    assert cfg.scan_roots == []
    assert cfg.snapshots_dir == "snapshots"
    assert cfg.reports_dir == "reports"
    assert cfg.parallel_workers == 8
    assert not hasattr(cfg, "build_version_relative_path")


def test_load_tool_config_still_reads_legacy_sidecar_keys(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "gameDrive": r"\\10.0.0.111\c$\Goldclub",
                "buildVersionRelativePath": "ruleta/BuildVersion.txt",
                "scanRoots": ["config"],
                "includePatterns": ["*.xml"],
                "parallelWorkers": 2,
                "snapshotsDir": "snaps",
                "reportsDir": "reps",
            }
        ),
        encoding="utf-8",
    )
    cfg = load_tool_config(tmp_path)
    assert cfg.game_drive == r"\\10.0.0.111\c$\Goldclub"
    assert cfg.scan_roots == ["config"]
    assert cfg.include_patterns == ["*.xml"]
    assert cfg.parallel_workers == 2
    assert cfg.snapshots_dir == "snaps"
    assert cfg.reports_dir == "reps"
