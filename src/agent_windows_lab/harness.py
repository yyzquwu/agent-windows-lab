from __future__ import annotations

import json
import locale
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


UNICODE_TOKEN = "snow-\u96ea"
ARGUMENTS_WITH_SHELL_METACHARS = [
    "space value",
    "literal&value",
    "pipe|value",
    "caret^value",
    "semi;value",
    UNICODE_TOKEN,
]


def _path_variants(path: str | None) -> list[str]:
    if not path:
        return []
    normalized = str(Path(path))
    variants = {path, normalized, normalized.replace("\\", "/"), normalized.replace("/", "\\")}
    return sorted((variant for variant in variants if variant), key=len, reverse=True)


def _locale_encoding() -> str:
    getencoding = getattr(locale, "getencoding", None)
    if getencoding is not None:
        return getencoding()
    return locale.getpreferredencoding(False)


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: dict[str, Any]


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    text: bool = True,
    encoding: str = "utf-8",
    timeout: int = 20,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    if text:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding=encoding,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=False,
        timeout=timeout,
        check=False,
    )


def check_environment() -> CheckResult:
    tools = {
        "python": sys.executable,
        "node": shutil.which("node"),
        "git": shutil.which("git"),
        "gh": shutil.which("gh"),
        "bash": shutil.which("bash"),
    }
    return CheckResult(
        name="environment",
        status="pass",
        summary=f"{platform.system()} {platform.release()} with Python {platform.python_version()}",
        details={
            "platform": platform.platform(),
            "python": platform.python_version(),
            "executable": sys.executable,
            "filesystem_encoding": sys.getfilesystemencoding(),
            "python_default_encoding": sys.getdefaultencoding(),
            "preferred_encoding": _locale_encoding(),
            "cwd": str(Path.cwd()),
            "tools": tools,
        },
    )


def check_path_shapes() -> CheckResult:
    with tempfile.TemporaryDirectory(prefix="Agent Windows Lab ") as raw:
        root = Path(raw)
        target_dir = root / "space dir" / UNICODE_TOKEN
        target_dir.mkdir(parents=True)
        target_file = target_dir / "agent report.jsonl"
        payload = {"path": str(target_file), "message": UNICODE_TOKEN}
        target_file.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        roundtrip = json.loads(target_file.read_text(encoding="utf-8"))

        ok = roundtrip["message"] == UNICODE_TOKEN and target_file.exists()
        return CheckResult(
            name="path_shapes",
            status="pass" if ok else "fail",
            summary="Created and read a path containing spaces and Unicode.",
            details={
                "path": str(target_file),
                "path_length": len(str(target_file)),
                "roundtrip": roundtrip,
            },
        )


def check_long_path_probe() -> CheckResult:
    with tempfile.TemporaryDirectory(prefix="Agent Windows Lab ") as raw:
        root = Path(raw)
        current = root
        for index in range(8):
            current = current / f"nested-directory-{index:02d}-for-agent-path-testing"
        target_file = current / "result.json"
        try:
            current.mkdir(parents=True)
            target_file.write_text('{"ok": true}\n', encoding="utf-8")
            read_back = target_file.read_text(encoding="utf-8")
            return CheckResult(
                name="long_path_probe",
                status="pass",
                summary="Created and read a long nested path.",
                details={
                    "path": str(target_file),
                    "path_length": len(str(target_file)),
                    "read_back": read_back.strip(),
                },
            )
        except OSError as exc:
            return CheckResult(
                name="long_path_probe",
                status="warn",
                summary="Long nested path failed; this is useful upstream evidence.",
                details={
                    "path": str(target_file),
                    "path_length": len(str(target_file)),
                    "error": repr(exc),
                },
            )


def check_subprocess_argument_roundtrip() -> CheckResult:
    with tempfile.TemporaryDirectory(prefix="Agent Windows Lab ") as raw:
        root = Path(raw)
        script = root / "echo args.py"
        script.write_text(
            "import json, sys\n"
            "payload = json.dumps(sys.argv[1:], ensure_ascii=False).encode('utf-8')\n"
            "sys.stdout.buffer.write(payload)\n",
            encoding="utf-8",
        )
        completed = _run([sys.executable, str(script), *ARGUMENTS_WITH_SHELL_METACHARS])
        observed = json.loads(completed.stdout) if completed.returncode == 0 else []
        ok = completed.returncode == 0 and observed == ARGUMENTS_WITH_SHELL_METACHARS
        return CheckResult(
            name="subprocess_argument_roundtrip",
            status="pass" if ok else "fail",
            summary="Verified shell metacharacters survive shell=False process launch.",
            details={
                "returncode": completed.returncode,
                "expected": ARGUMENTS_WITH_SHELL_METACHARS,
                "observed": observed,
                "stderr": completed.stderr,
            },
        )


def check_python_child_stdout_encoding() -> CheckResult:
    with tempfile.TemporaryDirectory(prefix="Agent Windows Lab ") as raw:
        root = Path(raw)
        script = root / "unicode_stdout.py"
        script.write_text(
            "import sys\n"
            "print('stdout_encoding=' + str(sys.stdout.encoding))\n"
            "print('unicode=' + chr(0x96ea))\n",
            encoding="utf-8",
        )
        completed = _run([sys.executable, str(script)], text=False)
        first_line = completed.stdout.splitlines()[0] if completed.stdout.splitlines() else b""
        stdout_encoding = "unknown"
        try:
            first_line_text = first_line.decode("ascii", errors="replace")
            if first_line_text.startswith("stdout_encoding="):
                stdout_encoding = first_line_text.split("=", 1)[1] or "unknown"
        except UnicodeDecodeError:
            first_line_text = ""
        decode_encoding = stdout_encoding if stdout_encoding != "unknown" else _locale_encoding()
        stdout = completed.stdout.decode(decode_encoding, errors="replace")
        stderr = completed.stderr.decode(decode_encoding, errors="replace")
        unicode_roundtrip_ok = f"unicode={chr(0x96ea)}" in stdout
        return CheckResult(
            name="python_child_stdout_encoding",
            status="pass" if completed.returncode == 0 and unicode_roundtrip_ok else "warn",
            summary=(
                "Python child process printed Unicode successfully."
                if completed.returncode == 0 and unicode_roundtrip_ok
                else "Python child process failed to print Unicode with default stdout encoding."
            ),
            details={
                "returncode": completed.returncode,
                "stdout_encoding": stdout_encoding,
                "stdout_hex": completed.stdout.hex(),
                "stdout": stdout.strip(),
                "stderr_hex": completed.stderr.hex(),
                "stderr": stderr.strip(),
            },
        )


def check_stdio_newline_framing() -> CheckResult:
    with tempfile.TemporaryDirectory(prefix="Agent Windows Lab ") as raw:
        root = Path(raw)
        text_script = root / "stdio_text.py"
        binary_script = root / "stdio_binary.py"
        message = '{"jsonrpc":"2.0","id":1,"result":"ok"}'
        text_script.write_text(
            f"import sys\nsys.stdout.write({message!r} + '\\n')\n",
            encoding="utf-8",
        )
        binary_script.write_text(
            f"import sys\nsys.stdout.buffer.write(({message!r} + '\\n').encode('utf-8'))\n",
            encoding="utf-8",
        )
        text_run = _run([sys.executable, str(text_script)], text=False)
        binary_run = _run([sys.executable, str(binary_script)], text=False)
        text_bytes = text_run.stdout
        binary_bytes = binary_run.stdout
        text_has_crlf = b"\r\n" in text_bytes
        binary_is_lf = binary_bytes.endswith(b"\n") and not binary_bytes.endswith(b"\r\n")
        return CheckResult(
            name="stdio_newline_framing",
            status="warn" if text_has_crlf else "pass",
            summary=(
                "Text-mode stdout emitted CRLF; strict MCP-style NDJSON readers should prefer binary/explicit framing."
                if text_has_crlf
                else "Text-mode stdout emitted LF in this environment."
            ),
            details={
                "text_stdout_hex": text_bytes.hex(),
                "binary_stdout_hex": binary_bytes.hex(),
                "text_has_crlf": text_has_crlf,
                "binary_is_lf": binary_is_lf,
            },
        )


def check_shell_encoding_probe() -> CheckResult:
    probes: dict[str, dict[str, Any]] = {}
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    cmd = shutil.which("cmd")
    if powershell:
        ps = _run(
            [
                powershell,
                "-NoProfile",
                "-Command",
                "[Console]::OutputEncoding.WebName; 'unicode:' + [char]0x96ea",
            ]
        )
        probes["powershell"] = {
            "returncode": ps.returncode,
            "stdout": ps.stdout.strip(),
            "stderr": ps.stderr.strip(),
        }
    if cmd:
        cmd_run = _run([cmd, "/c", "chcp"])
        probes["cmd"] = {
            "returncode": cmd_run.returncode,
            "stdout": cmd_run.stdout.strip(),
            "stderr": cmd_run.stderr.strip(),
        }

    ok = bool(probes) and all(item["returncode"] == 0 for item in probes.values())
    return CheckResult(
        name="shell_encoding_probe",
        status="pass" if ok else "warn",
        summary="Captured shell encoding and code-page signals for repro reports.",
        details=probes,
    )


def check_node_argument_roundtrip() -> CheckResult:
    node = shutil.which("node")
    if not node:
        return CheckResult(
            name="node_argument_roundtrip",
            status="skip",
            summary="Node.js is not available.",
            details={},
        )

    with tempfile.TemporaryDirectory(prefix="Agent Windows Lab ") as raw:
        root = Path(raw)
        script = root / "echo args.mjs"
        script.write_text(
            "console.log(JSON.stringify(process.argv.slice(2)))\n",
            encoding="utf-8",
        )
        completed = _run([node, str(script), *ARGUMENTS_WITH_SHELL_METACHARS])
        observed = json.loads(completed.stdout) if completed.returncode == 0 else []
        ok = completed.returncode == 0 and observed == ARGUMENTS_WITH_SHELL_METACHARS
        return CheckResult(
            name="node_argument_roundtrip",
            status="pass" if ok else "fail",
            summary="Verified Node subprocess argument roundtrip for TypeScript/JS agent tooling.",
            details={
                "node": node,
                "returncode": completed.returncode,
                "expected": ARGUMENTS_WITH_SHELL_METACHARS,
                "observed": observed,
                "stderr": completed.stderr,
            },
        )


def run_all_checks() -> dict[str, Any]:
    checks = [
        check_environment(),
        check_path_shapes(),
        check_long_path_probe(),
        check_subprocess_argument_roundtrip(),
        check_python_child_stdout_encoding(),
        check_stdio_newline_framing(),
        check_shell_encoding_probe(),
        check_node_argument_roundtrip(),
    ]
    counts: dict[str, int] = {}
    for check in checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    return {
        "schema_version": 1,
        "name": "agent-windows-lab",
        "platform": platform.platform(),
        "summary": counts,
        "checks": [asdict(check) for check in checks],
    }


def redact_report(report: dict[str, Any]) -> dict[str, Any]:
    redacted = json.loads(json.dumps(report))
    replacements: list[tuple[str, str]] = []
    for placeholder, path in [
        ("%WORKSPACE%", str(Path.cwd())),
        ("%TEMP%", tempfile.gettempdir()),
        ("%USERPROFILE%", str(Path.home())),
    ]:
        replacements.extend((variant, placeholder) for variant in _path_variants(path))

    byte_replacements = [
        (needle.encode("utf-8"), replacement.encode("utf-8"))
        for needle, replacement in replacements
        if needle
    ]

    def redact_string(value: str) -> str:
        sanitized = value
        for needle, replacement in replacements:
            sanitized = sanitized.replace(needle, replacement)
        sanitized = re.sub(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/]+", "%USERPROFILE%", sanitized)
        sanitized = re.sub(r"(?<![A-Za-z0-9_.-])/Users/[^/\s]+", "%USERPROFILE%", sanitized)
        sanitized = re.sub(r"(?<![A-Za-z0-9_.-])/home/[^/\s]+", "%USERPROFILE%", sanitized)
        sanitized = re.sub(r"(?<![:A-Za-z0-9_.-])(?:\\\\|//)[^\\/\r\n\"'<>|]+[\\/][^\r\n\"'<>|]+", "%PATH%", sanitized)
        sanitized = re.sub(r"(?<![A-Za-z0-9_.-])[A-Za-z]:[\\/][^\r\n\"'<>|]+", "%PATH%", sanitized)
        sanitized = re.sub(
            r"(?<![:A-Za-z0-9_.-])/(?:usr|opt|bin|sbin|etc|var|tmp|private|Applications|Library|System|nix)/[^\s\"'<>|]+",
            "%PATH%",
            sanitized,
        )
        return sanitized

    def redact_hex_string(value: str) -> str:
        try:
            raw = bytes.fromhex(value)
        except ValueError:
            return redact_string(value)

        sanitized = raw
        for needle, replacement in byte_replacements:
            sanitized = sanitized.replace(needle, replacement)
        sanitized = re.sub(rb"[A-Za-z]:[\\/]+Users[\\/]+[^\\/]+", b"%USERPROFILE%", sanitized)
        sanitized = re.sub(rb"(?<![A-Za-z0-9_.-])/Users/[^/\s]+", b"%USERPROFILE%", sanitized)
        sanitized = re.sub(rb"(?<![A-Za-z0-9_.-])/home/[^/\s]+", b"%USERPROFILE%", sanitized)
        sanitized = re.sub(rb"(?<![:A-Za-z0-9_.-])(?:\\\\|//)[^\\/\r\n\"'<>|]+[\\/][^\r\n\"'<>|]+", b"%PATH%", sanitized)
        sanitized = re.sub(rb"(?<![A-Za-z0-9_.-])[A-Za-z]:[\\/][^\r\n\"'<>|]+", b"%PATH%", sanitized)
        sanitized = re.sub(
            rb"(?<![:A-Za-z0-9_.-])/(?:usr|opt|bin|sbin|etc|var|tmp|private|Applications|Library|System|nix)/[^\s\"'<>|]+",
            b"%PATH%",
            sanitized,
        )
        return sanitized.hex()

    def redact_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: redact_hex_string(item) if key.endswith("_hex") and isinstance(item, str) else redact_value(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [redact_value(item) for item in value]
        if not isinstance(value, str):
            return value
        return redact_string(value)

    redacted = redact_value(redacted)
    redacted["redacted"] = True
    return redacted


def report_to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Agent Windows Lab Report",
        "",
        f"Platform: `{report['platform']}`",
        "",
        "## Summary",
        "",
    ]
    for status, count in sorted(report["summary"].items()):
        lines.append(f"- `{status}`: {count}")
    lines.extend(["", "## Checks", ""])
    for check in report["checks"]:
        lines.append(f"### {check['name']}")
        lines.append("")
        lines.append(f"Status: `{check['status']}`")
        lines.append("")
        lines.append(check["summary"])
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(check["details"], indent=2, sort_keys=True, ensure_ascii=False))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)
