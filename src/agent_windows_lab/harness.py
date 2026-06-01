from __future__ import annotations

import json
import locale
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


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


CheckFn = Callable[[], CheckResult]


ISSUE_TARGETS: dict[str, dict[str, str]] = {
    "generic": {
        "repo": "any agentic OSS project",
        "url": "https://github.com/yyzquwu/agent-windows-lab",
        "focus": "Windows process, stdio, path, shell, browser, and MCP evidence",
    },
    "modelcontextprotocol-python-sdk": {
        "repo": "modelcontextprotocol/python-sdk",
        "url": "https://github.com/modelcontextprotocol/python-sdk",
        "focus": "MCP stdio framing and Windows regression-test evidence",
    },
    "modelcontextprotocol-servers": {
        "repo": "modelcontextprotocol/servers",
        "url": "https://github.com/modelcontextprotocol/servers",
        "focus": "MCP server filesystem/path and stdio behavior on Windows",
    },
    "microsoft-playwright-mcp": {
        "repo": "microsoft/playwright-mcp",
        "url": "https://github.com/microsoft/playwright-mcp",
        "focus": "Browser-agent MCP startup, profile path, and Windows stdio evidence",
    },
}


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


def check_mcp_stdio_jsonrpc_probe() -> CheckResult:
    with tempfile.TemporaryDirectory(prefix="Agent Windows Lab ") as raw:
        root = Path(raw)
        script = root / "mcp_stdio_probe.py"
        script.write_text(
            "import json, sys\n"
            "line = sys.stdin.buffer.readline()\n"
            "request = json.loads(line.decode('utf-8'))\n"
            "response = {\n"
            "    'jsonrpc': '2.0',\n"
            "    'id': request.get('id'),\n"
            "    'result': {'protocolVersion': '2025-06-18', 'serverInfo': {'name': 'probe'}}\n"
            "}\n"
            "sys.stdout.buffer.write(json.dumps(response, separators=(',', ':')).encode('utf-8') + b'\\n')\n",
            encoding="utf-8",
        )
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "agent-windows-lab"}, "protocolVersion": "2025-06-18"},
        }
        payload = (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")
        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=root,
            input=payload,
            capture_output=True,
            text=False,
            timeout=20,
            check=False,
        )
        response: dict[str, Any] = {}
        try:
            response = json.loads(completed.stdout.decode("utf-8"))
        except json.JSONDecodeError:
            pass
        ok = (
            completed.returncode == 0
            and response.get("jsonrpc") == "2.0"
            and response.get("id") == 1
            and completed.stdout.endswith(b"\n")
            and not completed.stdout.endswith(b"\r\n")
        )
        return CheckResult(
            name="mcp_stdio_jsonrpc_probe",
            status="pass" if ok else "fail",
            summary="Round-tripped an MCP-style JSON-RPC initialize message over binary stdio with LF framing.",
            details={
                "returncode": completed.returncode,
                "request": request,
                "response": response,
                "stdout_hex": completed.stdout.hex(),
                "stderr_hex": completed.stderr.hex(),
                "lf_framed": completed.stdout.endswith(b"\n") and not completed.stdout.endswith(b"\r\n"),
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


def _quote_for_powershell(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _parse_json_stdout(value: str) -> dict[str, Any]:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def check_shell_launch_context() -> CheckResult:
    probes: dict[str, dict[str, Any]] = {}
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    cmd = shutil.which("cmd")
    with tempfile.TemporaryDirectory(prefix="Agent Windows Lab ") as raw:
        root = Path(raw) / f"shell cwd {UNICODE_TOKEN}"
        root.mkdir()
        script = root / "shell_probe.py"
        script.write_text(
            "import json, os, sys\n"
            "payload = {'cwd': os.getcwd(), 'env': os.environ.get('AGENT_WINDOWS_LAB_TOKEN'), 'argv': sys.argv[1:]}\n"
            "sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))\n",
            encoding="utf-8",
        )
        env = {**os.environ, "AGENT_WINDOWS_LAB_TOKEN": UNICODE_TOKEN}
        if powershell:
            command = (
                f"& {_quote_for_powershell(sys.executable)} "
                f"{_quote_for_powershell(str(script))} {_quote_for_powershell(UNICODE_TOKEN)}"
            )
            ps = subprocess.run(
                [powershell, "-NoProfile", "-Command", command],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
            probes["powershell"] = {
                "returncode": ps.returncode,
                "observed": _parse_json_stdout(ps.stdout),
                "stderr": ps.stderr.strip(),
            }
        if cmd:
            command = f'""{sys.executable}" "{script}" "{UNICODE_TOKEN}""'
            cmd_run = subprocess.run(
                [cmd, "/c", command],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
            probes["cmd"] = {
                "returncode": cmd_run.returncode,
                "observed": _parse_json_stdout(cmd_run.stdout),
                "stderr": cmd_run.stderr.strip(),
            }

    def probe_ok(item: dict[str, Any]) -> bool:
        observed = item.get("observed", {})
        return (
            item.get("returncode") == 0
            and observed.get("env") == UNICODE_TOKEN
            and observed.get("argv") == [UNICODE_TOKEN]
            and "shell cwd" in observed.get("cwd", "")
        )

    ok = bool(probes) and all(probe_ok(item) for item in probes.values())
    return CheckResult(
        name="shell_launch_context",
        status="pass" if ok else "warn",
        summary=(
            "Verified shell-launched child processes preserve cwd, environment, and Unicode arguments."
            if ok
            else "Captured shell launch differences for cwd, environment, or Unicode arguments."
        ),
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


def check_browser_agent_environment_probe() -> CheckResult:
    local_app_data = os.environ.get("LOCALAPPDATA")
    program_files = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    browser_candidates = [
        Path(base) / relative
        for base in program_files
        if base
        for relative in [
            Path("Microsoft") / "Edge" / "Application" / "msedge.exe",
            Path("Google") / "Chrome" / "Application" / "chrome.exe",
        ]
    ]
    found_browsers = [str(path) for path in browser_candidates if path.exists()]
    playwright_cache = str(Path(local_app_data) / "ms-playwright") if local_app_data else None
    with tempfile.TemporaryDirectory(prefix="Agent Windows Lab ") as raw:
        profile_dir = Path(raw) / f"browser profile {UNICODE_TOKEN}"
        profile_dir.mkdir()
        marker = profile_dir / "state.json"
        marker.write_text(json.dumps({"ok": True, "token": UNICODE_TOKEN}), encoding="utf-8")
        profile_roundtrip = json.loads(marker.read_text(encoding="utf-8"))

    npx = shutil.which("npx")
    ok = profile_roundtrip.get("token") == UNICODE_TOKEN and bool(npx or found_browsers)
    return CheckResult(
        name="browser_agent_environment_probe",
        status="pass" if ok else "warn",
        summary="Captured browser-agent prerequisites and verified a Unicode profile path can be created.",
        details={
            "npx": npx,
            "found_browsers": found_browsers,
            "playwright_cache": playwright_cache,
            "profile_path_created": str(profile_dir),
            "profile_roundtrip": profile_roundtrip,
        },
    )


CASE_CHECKS: dict[str, tuple[CheckFn, ...]] = {
    "browser": (check_browser_agent_environment_probe,),
    "environment": (check_environment,),
    "encoding": (check_python_child_stdout_encoding, check_shell_encoding_probe),
    "mcp": (check_stdio_newline_framing, check_mcp_stdio_jsonrpc_probe),
    "paths": (check_path_shapes, check_long_path_probe),
    "shell": (check_shell_encoding_probe, check_shell_launch_context),
    "stdio": (check_stdio_newline_framing,),
    "subprocess": (check_subprocess_argument_roundtrip, check_node_argument_roundtrip),
}


def available_cases() -> list[str]:
    return ["all", *sorted(CASE_CHECKS)]


def available_issue_targets() -> list[str]:
    return sorted(ISSUE_TARGETS)


def _normalize_cases(cases: Iterable[str] | None) -> list[str]:
    requested = [case.lower() for case in cases or ["all"]]
    selected = list(dict.fromkeys(requested))
    unknown = [case for case in selected if case not in available_cases()]
    if unknown:
        known = ", ".join(available_cases())
        raise ValueError(f"Unknown case(s): {', '.join(unknown)}. Known cases: {known}")
    if "all" in selected:
        return ["all"]
    return selected


def _case_check_functions(selected_cases: list[str]) -> list[CheckFn]:
    if selected_cases == ["all"]:
        selected_cases = [case for case in available_cases() if case != "all"]
    elif "environment" not in selected_cases:
        selected_cases = ["environment", *selected_cases]

    check_fns: list[CheckFn] = []
    seen: set[str] = set()
    for case in selected_cases:
        for check_fn in CASE_CHECKS[case]:
            if check_fn.__name__ not in seen:
                check_fns.append(check_fn)
                seen.add(check_fn.__name__)
    return check_fns


def run_checks(cases: Iterable[str] | None = None) -> dict[str, Any]:
    selected_cases = _normalize_cases(cases)
    checks = [check_fn() for check_fn in _case_check_functions(selected_cases)]
    counts: dict[str, int] = {}
    for check in checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    return {
        "schema_version": 1,
        "name": "agent-windows-lab",
        "cases": selected_cases,
        "platform": platform.platform(),
        "summary": counts,
        "checks": [asdict(check) for check in checks],
    }


def run_all_checks() -> dict[str, Any]:
    return run_checks()


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


def issue_packet_to_markdown(report: dict[str, Any], *, target: str = "generic", title: str | None = None) -> str:
    target_info = ISSUE_TARGETS[target]
    notable = [check for check in report["checks"] if check["status"] in {"fail", "warn", "skip"}]
    cases = report.get("cases", ["all"])
    case_args = " ".join(f"--case {case}" for case in cases if case != "all") or "--case all"
    issue_title = title or f"Windows agent repro: {', '.join(cases)} evidence from Agent Windows Lab"
    lines = [
        f"# {issue_title}",
        "",
        "## Target",
        "",
        f"- Repository: `{target_info['repo']}`",
        f"- URL: {target_info['url']}",
        f"- Focus: {target_info['focus']}",
        "",
        "## Summary",
        "",
        "Agent Windows Lab produced a redacted Windows repro packet for agentic-tooling behavior.",
        "The packet is intended to make the issue easy to reproduce, verify, and turn into a regression test.",
        "",
        "## Repro Command",
        "",
        "```powershell",
        f"python .\\scripts\\run_agent_windows_lab.py --out .\\artifacts\\issue-packet {case_args} --redact --issue-target {target}",
        "python .\\scripts\\verify_redacted_report.py .\\artifacts\\issue-packet\\agent-windows-lab-report.json",
        "```",
        "",
        "## Environment",
        "",
        f"- Platform: `{report['platform']}`",
        f"- Cases: `{', '.join(cases)}`",
        f"- Redacted: `{report.get('redacted') is True}`",
        "",
        "## Check Summary",
        "",
    ]
    for status, count in sorted(report["summary"].items()):
        lines.append(f"- `{status}`: {count}")
    lines.extend(["", "## Notable Signals", ""])
    if notable:
        for check in notable:
            lines.append(f"- `{check['name']}`: `{check['status']}` - {check['summary']}")
    else:
        lines.append("- No failing or warning checks. Use this as a Windows baseline/regression fixture.")
    lines.extend(["", "## Full Check List", ""])
    for check in report["checks"]:
        lines.append(f"- `{check['name']}`: `{check['status']}` - {check['summary']}")
    lines.extend(
        [
            "",
            "## Evidence Files",
            "",
            "- `agent-windows-lab-report.json`",
            "- `agent-windows-lab-report.md`",
            "- `agent-windows-lab-issue.md`",
            "",
            "All generated evidence should be created with `--redact` and verified before sharing.",
        ]
    )
    return "\n".join(lines)
