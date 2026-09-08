"""Deny agent shell/tool calls that rewrite GoldClub/EGM boot (BCD, EFI, hives)."""
from __future__ import annotations

import json
import re
import sys

DENY_REASON = (
    "Blocked: GoldClub boot/BCD/hive edits are forbidden "
    "(27 Aug 2026 BIWIN BSOD). Copy OO_Security.ps1 and onlogon.ps1 only."
)

_DENY_RE = re.compile(
    r"""
    bcdboot
    | bcdedit\s+/store
    | bootmgfw\.efi
    | bootx64\.efi
    | HKLM\\BIWINSYS
    | HKLM\\BIWINSOFT
    | _fix-biwin-efi
    | _fix-biwin-bcd
    | _patch-biwin-boot
    | _repair-biwin-bsod
    | _unload-biwin-hive
    | CrashControl
    | Shell\s+Launcher
    | Alegro.+\.mrimg
    | reg\s+load\s+HKLM\\BIWIN
    | reg\s+load.{0,80}Windows\\System32\\config\\SYSTEM
    | reg\s+load.{0,80}Windows\\System32\\config\\SOFTWARE
    """,
    re.IGNORECASE | re.VERBOSE,
)


def collect_text(payload: dict) -> str:
    parts: list[str] = []
    for key in ("command", "command_line", "script"):
        val = payload.get(key)
        if isinstance(val, str):
            parts.append(val)
    tool_input = payload.get("tool_input") or payload.get("arguments") or {}
    if isinstance(tool_input, dict):
        for key in ("command", "path", "file_path"):
            val = tool_input.get(key)
            if isinstance(val, str):
                parts.append(val)
    path = payload.get("path") or payload.get("file_path")
    if isinstance(path, str):
        parts.append(path)
    return "\n".join(parts)


def should_deny(text: str) -> str | None:
    if not text:
        return None
    if _DENY_RE.search(text):
        return DENY_REASON
    return None


def _parse_stdin() -> dict:
    raw_b = sys.stdin.buffer.read()
    if not raw_b.strip():
        return {}
    last_err: Exception | None = None
    for enc in ("utf-8-sig", "utf-8", "utf-16", "utf-16-le"):
        try:
            payload = json.loads(raw_b.decode(enc))
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            last_err = exc
            continue
    raise ValueError(f"hook stdin is not JSON ({last_err})")


def main() -> None:
    try:
        payload = _parse_stdin()
    except Exception:
        json.dump(
            {
                "permission": "deny",
                "agent_message": DENY_REASON,
                "user_message": DENY_REASON,
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        return
    reason = should_deny(collect_text(payload))
    if reason:
        json.dump(
            {
                "permission": "deny",
                "agent_message": reason,
                "user_message": reason,
            },
            sys.stdout,
        )
    else:
        json.dump({"permission": "allow"}, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
