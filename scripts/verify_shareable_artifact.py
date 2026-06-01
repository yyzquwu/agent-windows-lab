from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SENSITIVE_KEYS = {"body"}
SAFE_PLACEHOLDER_PATH_PATTERN = re.compile(
    r"%(?:USERPROFILE|WORKSPACE|TEMP|PATH)%(?:(?:\\\\|\\|/)(?![A-Za-z]:)[^\\/\r\n\"'<>|`{},\s]+)+",
    re.IGNORECASE,
)
PRIVATE_PATH_PATTERNS = [
    re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/]+", re.IGNORECASE),
    re.compile(r"[A-Za-z]:[\\/]+[^\\/\r\n]+[\\/]+AppData[\\/]", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])/(?:Users|home)/[^/\s]+", re.IGNORECASE),
    re.compile(r"(?<![:A-Za-z0-9_.-])(?:\\\\|//)[^\\/\r\n\"'<>|]+[\\/][^\r\n\"'<>|]+"),
]


def _walk(value: Any, *, key: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        pairs: list[tuple[str, Any]] = []
        for child_key, child_value in value.items():
            pairs.append((str(child_key), child_value))
            pairs.extend(_walk(child_value, key=str(child_key)))
        return pairs
    if isinstance(value, list):
        pairs = []
        for child_value in value:
            pairs.extend(_walk(child_value, key=key))
        return pairs
    return [(key, value)]


def _artifact_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return [item for item in path.rglob("*") if item.is_file()]


def _looks_private_path(value: str) -> bool:
    without_placeholders = SAFE_PLACEHOLDER_PATH_PATTERN.sub("%PATH%", value)
    return any(pattern.search(without_placeholders) for pattern in PRIVATE_PATH_PATTERNS)


def _json_leaks(path: Path, payload: Any) -> list[str]:
    leaks: list[str] = []
    for key, value in _walk(payload):
        if key in SENSITIVE_KEYS:
            leaks.append(f"{path}: raw `{key}` field is not shareable")
        if isinstance(value, str) and _looks_private_path(value):
            leaks.append(f"{path}: path-like value in `{key}`: {value}")
        if isinstance(value, str) and key.endswith("_hex"):
            try:
                decoded = bytes.fromhex(value).decode("utf-8", errors="ignore")
            except ValueError:
                continue
            if _looks_private_path(decoded):
                leaks.append(f"{path}: path-like decoded hex in `{key}`: {decoded}")
    return leaks


def _text_leaks(path: Path, text: str) -> list[str]:
    if _looks_private_path(text):
        return [f"{path}: path-like text found"]
    return []


def find_shareable_artifact_leaks(path: Path) -> list[str]:
    leaks: list[str] = []
    files = _artifact_files(path)
    if not files:
        return [f"{path}: no files found"]
    for item in files:
        text = item.read_text(encoding="utf-8", errors="replace")
        if item.suffix.lower() == ".json":
            try:
                leaks.extend(_json_leaks(item, json.loads(text)))
                continue
            except json.JSONDecodeError:
                pass
        leaks.extend(_text_leaks(item, text))
    return leaks


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify generated shareable artifacts do not leak local paths.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    leaks = find_shareable_artifact_leaks(args.path)
    if leaks:
        print("shareable artifact leaks found:", file=sys.stderr)
        for leak in leaks:
            print(f"- {leak}", file=sys.stderr)
        return 1
    print("shareable artifact verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
