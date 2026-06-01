from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


WINDOWS_DRIVE_PATH = re.compile(r"(?<![A-Za-z0-9_.-])[A-Za-z]:[\\/]")
UNC_PATH = re.compile(r"(?<![:A-Za-z0-9_.-])(?:\\\\|//)[^\\/\r\n\"'<>|]+[\\/][^\r\n\"'<>|]+")
POSIX_SYSTEM_PATH = re.compile(
    r"(?<![:A-Za-z0-9_.-])/"
    r"(?:usr|opt|bin|sbin|etc|var|tmp|private|Applications|Library|System|nix)/"
    r"[^\s\"'<>|]+"
)


def _walk_strings(value: Any, *, key: str = "") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        strings: list[tuple[str, str]] = []
        for child_key, child_value in value.items():
            strings.extend(_walk_strings(child_value, key=str(child_key)))
        return strings
    if isinstance(value, list):
        strings = []
        for child_value in value:
            strings.extend(_walk_strings(child_value, key=key))
        return strings
    if isinstance(value, str):
        return [(key, value)]
    return []


def _looks_like_path(value: str) -> bool:
    return bool(WINDOWS_DRIVE_PATH.search(value) or UNC_PATH.search(value) or POSIX_SYSTEM_PATH.search(value))


def find_redaction_leaks(report: dict[str, Any]) -> list[str]:
    leaks: list[str] = []
    for key, value in _walk_strings(report):
        if _looks_like_path(value):
            leaks.append(f"{key}: {value}")
        if key.endswith("_hex"):
            try:
                decoded = bytes.fromhex(value).decode("utf-8", errors="ignore")
            except ValueError:
                continue
            if _looks_like_path(decoded):
                leaks.append(f"{key} decoded: {decoded}")
    return leaks


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an Agent Windows Lab report is redacted.")
    parser.add_argument("report", type=Path)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    if report.get("redacted") is not True:
        print("report is missing redacted=true", file=sys.stderr)
        return 1

    leaks = find_redaction_leaks(report)
    if leaks:
        print("redaction leaks found:", file=sys.stderr)
        for leak in leaks:
            print(f"- {leak}", file=sys.stderr)
        return 1

    print("redacted report verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
