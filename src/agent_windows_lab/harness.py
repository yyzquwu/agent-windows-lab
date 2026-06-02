from __future__ import annotations

import importlib.util
import json
import locale
import math
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Generator, Iterable


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


@contextmanager
def _temporary_directory(prefix: str = "Agent Windows Lab ") -> Generator[str]:
    root = Path(tempfile.gettempdir())
    for _ in range(100):
        path = root / f"{prefix}{uuid.uuid4().hex[:8]}"
        try:
            if os.name == "nt":
                path.mkdir()
            else:
                path.mkdir(mode=0o700)
        except FileExistsError:
            continue
        try:
            yield str(path)
        finally:
            shutil.rmtree(path, ignore_errors=True)
        return
    raise FileExistsError(f"Could not create temporary directory under {root}")


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
    "modelcontextprotocol-typescript-sdk": {
        "repo": "modelcontextprotocol/typescript-sdk",
        "url": "https://github.com/modelcontextprotocol/typescript-sdk",
        "focus": "TypeScript MCP stdio, subprocess, and Windows path behavior",
    },
    "microsoft-playwright-mcp": {
        "repo": "microsoft/playwright-mcp",
        "url": "https://github.com/microsoft/playwright-mcp",
        "focus": "Browser-agent MCP startup, profile path, and Windows stdio evidence",
    },
    "browser-use": {
        "repo": "browser-use/browser-use",
        "url": "https://github.com/browser-use/browser-use",
        "focus": "Browser-agent launch, profile, path, and shell behavior on Windows",
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
    with _temporary_directory(prefix="Agent Windows Lab ") as raw:
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
    with _temporary_directory(prefix="Agent Windows Lab ") as raw:
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
    with _temporary_directory(prefix="Agent Windows Lab ") as raw:
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
    with _temporary_directory(prefix="Agent Windows Lab ") as raw:
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
    with _temporary_directory(prefix="Agent Windows Lab ") as raw:
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
    with _temporary_directory(prefix="Agent Windows Lab ") as raw:
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


def check_mcp_python_sdk_session_lifecycle_probe() -> CheckResult:
    if importlib.util.find_spec("mcp") is None:
        return CheckResult(
            name="mcp_python_sdk_session_lifecycle_probe",
            status="skip",
            summary="MCP Python SDK is not installed in this Python environment.",
            details={
                "install_hint": "python -m pip install mcp",
                "purpose": "Probe ClientSession lifecycle behavior for modelcontextprotocol/python-sdk stdio issues.",
            },
        )

    with _temporary_directory(prefix="Agent Windows Lab ") as raw:
        root = Path(raw)
        script = root / "mcp_python_sdk_session_lifecycle.py"
        script.write_text(
            r'''
import asyncio
import json
import sys
import time
import traceback

import mcp
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVER_CODE = "\n".join(
    [
        "import json",
        "import sys",
        "import time",
        "line = sys.stdin.buffer.readline()",
        "request = json.loads(line.decode('utf-8'))",
        "response = {",
        "    'jsonrpc': '2.0',",
        "    'id': request.get('id'),",
        "    'result': {",
        "        'protocolVersion': '2025-06-18',",
        "        'capabilities': {},",
        "        'serverInfo': {'name': 'agent-windows-lab-sdk-probe', 'version': '1.0.0'},",
        "    },",
        "}",
        "sys.stdout.buffer.write(json.dumps(response, separators=(',', ':')).encode('utf-8') + b'\\n')",
        "sys.stdout.buffer.flush()",
        "time.sleep(0.1)",
    ]
)


def server_params() -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=["-c", SERVER_CODE])


async def correct_context() -> dict[str, object]:
    started = time.monotonic()
    async with stdio_client(server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            result = await asyncio.wait_for(session.initialize(), timeout=5)
    server_info = getattr(result, "serverInfo", getattr(result, "server_info", None))
    return {
        "status": "completed",
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "server_name": getattr(server_info, "name", None),
        "protocol_version": getattr(result, "protocolVersion", getattr(result, "protocol_version", None)),
    }


async def missing_session_context() -> dict[str, object]:
    started = time.monotonic()
    try:
        async with stdio_client(server_params()) as (read, write):
            session = ClientSession(read, write)
            await asyncio.wait_for(session.initialize(), timeout=3)
        return {
            "status": "completed_unexpected",
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    except BaseException as exc:
        return {
            "status": "raised",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "exception_type": type(exc).__name__,
            "exception": repr(exc),
        }


async def main() -> None:
    results = {
        "python": sys.version.split()[0],
        "mcp_module": getattr(mcp, "__file__", None),
        "mcp_version": getattr(mcp, "__version__", None),
        "correct_context": await correct_context(),
        "missing_session_context": await missing_session_context(),
    }
    print(json.dumps(results, sort_keys=True))


try:
    asyncio.run(main())
except BaseException as exc:
    print(
        json.dumps(
            {
                "top_level_error": repr(exc),
                "top_level_error_type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            },
            sort_keys=True,
        )
    )
    raise
'''.lstrip(),
            encoding="utf-8",
        )
        try:
            completed = _run([sys.executable, str(script)], cwd=root, timeout=20)
        except subprocess.TimeoutExpired as exc:
            return CheckResult(
                name="mcp_python_sdk_session_lifecycle_probe",
                status="fail",
                summary="MCP Python SDK ClientSession lifecycle probe exceeded the process timeout.",
                details={"timeout_seconds": exc.timeout},
            )

    payload: dict[str, Any] = {}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        pass

    correct = payload.get("correct_context", {})
    missing = payload.get("missing_session_context", {})
    correct_ok = correct.get("status") == "completed"
    missing_exception = missing.get("exception_type")
    missing_exception_text = str(missing.get("exception", ""))
    missing_elapsed = missing.get("elapsed_seconds")
    missing_fast_guard = (
        missing.get("status") == "raised"
        and missing_exception == "RuntimeError"
        and isinstance(missing_elapsed, (int, float))
        and missing_elapsed < 1.0
    )
    missing_timeout = (
        missing.get("status") == "raised"
        and (missing_exception == "TimeoutError" or "TimeoutError" in missing_exception_text)
    )

    if completed.returncode != 0 or not payload:
        status = "fail"
        summary = "MCP Python SDK ClientSession lifecycle probe failed before producing structured evidence."
    elif correct_ok and missing_fast_guard:
        status = "pass"
        summary = "Proper ClientSession context initializes, and missing context fails fast instead of hanging."
    elif correct_ok and missing_timeout:
        status = "warn"
        summary = "Proper ClientSession context initializes, but missing context did not complete before timeout."
    elif correct_ok:
        status = "warn"
        summary = "Proper ClientSession context initializes, but missing-context behavior was not a fast guard."
    else:
        status = "fail"
        summary = "MCP Python SDK did not initialize successfully with the proper ClientSession context."

    return CheckResult(
        name="mcp_python_sdk_session_lifecycle_probe",
        status=status,
        summary=summary,
        details={
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "payload": payload,
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
    with _temporary_directory(prefix="Agent Windows Lab ") as raw:
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

    with _temporary_directory(prefix="Agent Windows Lab ") as raw:
        root = Path(raw)
        script = root / "echo args.mjs"
        script.write_text(
            "console.log(JSON.stringify(process.argv.slice(2)))\n",
            encoding="utf-8",
        )
        command = [node, str(script), *ARGUMENTS_WITH_SHELL_METACHARS]
        try:
            completed = _run(command)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
            return CheckResult(
                name="node_argument_roundtrip",
                status="warn",
                summary="Node subprocess argument roundtrip timed out before producing evidence.",
                details={
                    "node": node,
                    "command": command,
                    "timeout_seconds": exc.timeout,
                    "expected": ARGUMENTS_WITH_SHELL_METACHARS,
                    "stdout": stdout or "",
                    "stderr": stderr or "",
                },
            )
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
    with _temporary_directory(prefix="Agent Windows Lab ") as raw:
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


def _json_env_list(name: str) -> list[str] | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        return []
    return payload


def _float_env(name: str, default: float) -> tuple[float, str | None]:
    raw = os.environ.get(name)
    if not raw:
        return default, None
    try:
        value = float(raw)
    except ValueError:
        return default, raw
    if value <= 0 or not math.isfinite(value):
        return default, raw
    return value, None


def _bool_env(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return None


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt" and getattr(process, "pid", None):
        taskkill = shutil.which("taskkill")
        if taskkill:
            subprocess.run(
                [taskkill, "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            try:
                process.wait(timeout=5)
                return
            except subprocess.TimeoutExpired:
                pass
    try:
        if hasattr(process, "terminate"):
            process.terminate()
        else:
            process.kill()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        process.kill()
        process.wait(timeout=5)


def check_browser_use_mcp_startup_probe() -> CheckResult:
    command_var = "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND"
    timeout_var = "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S"
    cwd_var = "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_CWD"
    timeout_s, invalid_timeout = _float_env(timeout_var, 45)
    command = _json_env_list(command_var)
    command_cwd = os.environ.get(cwd_var) or None
    recommended = ["uvx", "--from", "browser-use[cli]", "browser-use", "--mcp"]
    if command is None:
        return CheckResult(
            name="browser_use_mcp_startup_probe",
            status="skip",
            summary="Browser Use MCP startup probe is opt-in; set a JSON command array to run it.",
            details={
                "command_env_var": command_var,
                "timeout_env_var": timeout_var,
                "cwd_env_var": cwd_var,
                "timeout_seconds": timeout_s,
                "invalid_timeout_env_value": invalid_timeout,
                "recommended_command": recommended,
                "related_upstream": "browser-use/browser-use#4657",
            },
        )
    if not command:
        return CheckResult(
            name="browser_use_mcp_startup_probe",
            status="warn",
            summary="Browser Use MCP startup command env var was set but was not a JSON string array.",
            details={
                "command_env_var": command_var,
                "timeout_env_var": timeout_var,
                "cwd_env_var": cwd_var,
                "timeout_seconds": timeout_s,
                "invalid_timeout_env_value": invalid_timeout,
            },
        )

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "clientInfo": {"name": "agent-windows-lab", "version": "0.1.0"},
            "capabilities": {},
        },
    }
    payload = (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")
    started = time.monotonic()
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONUTF8": "1"},
            cwd=command_cwd,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        stderr_bytes = bytearray()

        def read_stderr() -> None:
            while True:
                chunk = process.stderr.read(4096)
                if not chunk:
                    return
                if len(stderr_bytes) < 4000:
                    stderr_bytes.extend(chunk[: 4000 - len(stderr_bytes)])

        stderr_reader = threading.Thread(target=read_stderr, daemon=True)
        stderr_reader.start()
        process.stdin.write(payload)
        process.stdin.flush()

        response_queue: queue.Queue[bytes] = queue.Queue(maxsize=1)

        def read_stdout_line() -> None:
            response_queue.put(process.stdout.readline())

        reader = threading.Thread(target=read_stdout_line, daemon=True)
        reader.start()
        try:
            first_line_bytes = response_queue.get(timeout=timeout_s)
        except queue.Empty:
            raise subprocess.TimeoutExpired(command, timeout_s)
        elapsed_s = round(time.monotonic() - started, 3)
        _terminate_process_tree(process)
        stderr_reader.join(timeout=1)
        stderr_output = bytes(stderr_bytes)
        stdout_bytes = first_line_bytes
        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_output.decode("utf-8", errors="replace")
        response: dict[str, Any] = {}
        first_line = stdout_text.splitlines()[0] if stdout_text.splitlines() else ""
        try:
            response = json.loads(first_line)
        except json.JSONDecodeError:
            pass
        ok = (
            response.get("jsonrpc") == "2.0"
            and response.get("id") == 1
            and "result" in response
            and "error" not in response
        )
        return CheckResult(
            name="browser_use_mcp_startup_probe",
            status="pass" if ok else "warn",
            summary=(
                "Browser Use MCP process answered an initialize request."
                if ok
                else "Browser Use MCP process did not cleanly answer initialize before exit."
            ),
            details={
                "command": command,
                "cwd": command_cwd,
                "timeout_seconds": timeout_s,
                "invalid_timeout_env_value": invalid_timeout,
                "elapsed_seconds": elapsed_s,
                "returncode": process.returncode,
                "response": response,
                "stdout": stdout_text[:4000],
                "stderr": stderr_text[:4000],
                "stdout_hex": stdout_bytes[:4000].hex(),
                "stderr_hex": stderr_output[:4000].hex(),
            },
        )
    except subprocess.TimeoutExpired as exc:
        if process:
            _terminate_process_tree(process)
        elapsed_s = round(time.monotonic() - started, 3)
        stdout_reader = locals().get("reader")
        if isinstance(stdout_reader, threading.Thread):
            stdout_reader.join(timeout=1)
        stderr_reader = locals().get("stderr_reader")
        if isinstance(stderr_reader, threading.Thread):
            stderr_reader.join(timeout=1)
        stdout_parts: list[bytes] = []
        if isinstance(exc.stdout, bytes):
            stdout_parts.append(exc.stdout)
        response_queue = locals().get("response_queue")
        if isinstance(response_queue, queue.Queue):
            while True:
                try:
                    stdout_parts.append(response_queue.get_nowait())
                except queue.Empty:
                    break
        stdout = b"".join(stdout_parts)
        stderr = bytes(locals().get("stderr_bytes", b""))
        return CheckResult(
            name="browser_use_mcp_startup_probe",
            status="warn",
            summary="Browser Use MCP process timed out before answering initialize.",
            details={
                "command": command,
                "cwd": command_cwd,
                "timeout_seconds": timeout_s,
                "invalid_timeout_env_value": invalid_timeout,
                "elapsed_seconds": elapsed_s,
                "timed_out": True,
                "stdout": stdout.decode("utf-8", errors="replace")[:4000],
                "stderr": stderr.decode("utf-8", errors="replace")[:4000],
                "stdout_hex": stdout[:4000].hex(),
                "stderr_hex": stderr[:4000].hex(),
            },
        )
    except OSError as exc:
        if process:
            _terminate_process_tree(process)
        elapsed_s = round(time.monotonic() - started, 3)
        return CheckResult(
            name="browser_use_mcp_startup_probe",
            status="warn",
            summary="Browser Use MCP startup command could not be launched.",
            details={
                "command": command,
                "cwd": command_cwd,
                "timeout_seconds": timeout_s,
                "invalid_timeout_env_value": invalid_timeout,
                "elapsed_seconds": elapsed_s,
                "error": repr(exc),
            },
        )
    finally:
        if process is not None:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()


def _browser_use_mcp_response_text(response: dict[str, Any]) -> str:
    result = response.get("result")
    if not isinstance(result, dict):
        return json.dumps(response, sort_keys=True)[:1000]
    content = result.get("content")
    if not isinstance(content, list):
        return json.dumps(response, sort_keys=True)[:1000]
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict):
            if isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item.get("type"), str):
                parts.append(item["type"])
            else:
                parts.append(json.dumps(item, sort_keys=True))
        else:
            parts.append(str(item))
    return "\n".join(parts)


def _browser_use_mcp_response_summary(response: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": response.get("id"),
        "has_result": isinstance(response.get("result"), dict),
        "has_error": "error" in response,
    }
    if isinstance(response.get("error"), dict):
        error = response["error"]
        summary["error"] = {
            "code": error.get("code"),
            "message": str(error.get("message", ""))[:1000],
        }
    result = response.get("result")
    if isinstance(result, dict):
        summary["result_keys"] = sorted(str(key) for key in result.keys())
        summary["result_is_error"] = bool(result.get("isError"))
        content = result.get("content")
        if isinstance(content, list):
            summary["content_count"] = len(content)
            summary["content_types"] = [
                str(item.get("type", "unknown")) if isinstance(item, dict) else type(item).__name__
                for item in content[:10]
            ]
    return summary


def _browser_use_mcp_command_can_isolate_cwd(command: list[str]) -> bool:
    executable = Path(command[0]).name.lower() if command else ""
    python_names = {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}
    return executable in python_names and "-m" in command and "browser_use.mcp" in command


def _browser_use_mcp_tool_sequence(
    command: list[str],
    *,
    timeout_s: float,
    cwd: str | None,
    pythonpath_root: str | None,
    env_overrides: dict[str, str | None],
) -> dict[str, Any]:
    env = {**os.environ, "PYTHONUTF8": "1"}
    if pythonpath_root:
        env["PYTHONPATH"] = (
            pythonpath_root if not env.get("PYTHONPATH") else pythonpath_root + os.pathsep + env["PYTHONPATH"]
        )
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value

    process: subprocess.Popen[bytes] | None = None
    started = time.monotonic()
    stdout_queue: queue.Queue[bytes | None] = queue.Queue()
    stderr_bytes = bytearray()
    steps: list[dict[str, Any]] = []

    def read_next_response(expected_id: int, step_timeout_s: float) -> tuple[dict[str, Any] | None, str, bool, bool]:
        deadline = time.monotonic() + step_timeout_s
        raw_parts: list[bytes] = []
        while time.monotonic() < deadline:
            try:
                raw = stdout_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if raw is None:
                return None, b"".join(raw_parts).decode("utf-8", errors="replace"), False, True
            raw_parts.append(raw)
            try:
                response = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if response.get("id") != expected_id:
                continue
            return response, b"".join(raw_parts).decode("utf-8", errors="replace"), False, False
        return None, b"".join(raw_parts).decode("utf-8", errors="replace"), True, False

    def send(payload: dict[str, Any]) -> str | None:
        if process is None or process.stdin is None:
            return "stdin unavailable"
        try:
            process.stdin.write((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
            process.stdin.flush()
        except OSError as exc:
            return repr(exc)
        return None

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd,
        )
        assert process.stdout is not None
        assert process.stderr is not None

        def read_stdout() -> None:
            while True:
                chunk = process.stdout.readline()
                if not chunk:
                    stdout_queue.put(None)
                    return
                stdout_queue.put(chunk)

        def read_stderr() -> None:
            while True:
                chunk = process.stderr.read(4096)
                if not chunk:
                    return
                if len(stderr_bytes) < 4000:
                    stderr_bytes.extend(chunk[: 4000 - len(stderr_bytes)])

        stdout_reader = threading.Thread(target=read_stdout, daemon=True)
        stderr_reader = threading.Thread(target=read_stderr, daemon=True)
        stdout_reader.start()
        stderr_reader.start()

        initialize_error = send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "clientInfo": {"name": "agent-windows-lab", "version": "0.1.0"},
                    "capabilities": {},
                },
            }
        )
        if initialize_error:
            steps.append({"name": "initialize", "error": initialize_error})
            return {"steps": steps, "elapsed_seconds": round(time.monotonic() - started, 3)}
        response, raw, timed_out, stdout_eof = read_next_response(1, timeout_s)
        steps.append(
            {
                "name": "initialize",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "timed_out": timed_out,
                "stdout_eof": stdout_eof,
                "response": response or {},
                "stdout": raw[:1000],
            }
        )
        if timed_out or stdout_eof:
            return {"steps": steps, "elapsed_seconds": round(time.monotonic() - started, 3)}
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        for message_id, tool_name, arguments, step_timeout_s in (
            (2, "browser_navigate", {"url": "https://example.com/"}, timeout_s),
            (3, "browser_list_tabs", {}, min(timeout_s, 20)),
            (4, "browser_get_state", {"include_screenshot": False}, min(timeout_s, 30)),
            (5, "browser_screenshot", {"full_page": False}, min(timeout_s, 30)),
        ):
            step_started = time.monotonic()
            send_error = send(
                {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                }
            )
            if send_error:
                steps.append({"name": tool_name, "elapsed_seconds": 0, "error": send_error})
                break
            response, raw, timed_out, stdout_eof = read_next_response(message_id, step_timeout_s)
            text = _browser_use_mcp_response_text(response or {})
            steps.append(
                {
                    "name": tool_name,
                    "elapsed_seconds": round(time.monotonic() - step_started, 3),
                    "timed_out": timed_out,
                    "stdout_eof": stdout_eof,
                    "text": text[:1000],
                    "response_summary": _browser_use_mcp_response_summary(response or {}),
                    "stdout": raw[:1000],
                }
            )
            if timed_out or stdout_eof:
                break

        return {
            "steps": steps,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "returncode": process.poll(),
            "stderr": bytes(stderr_bytes).decode("utf-8", errors="replace")[:4000],
        }
    except OSError as exc:
        steps.append({"name": "launch", "error": repr(exc)})
        return {
            "steps": steps,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "launch_error": repr(exc),
            "stderr": bytes(stderr_bytes).decode("utf-8", errors="replace")[:4000],
        }
    finally:
        if process is not None:
            _terminate_process_tree(process)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()


def _step_text(sequence: dict[str, Any], name: str) -> str:
    for step in sequence.get("steps", []):
        if step.get("name") == name:
            return step.get("text", "")
    return ""


def _browser_use_mcp_sequence_completed_cleanly(sequence: dict[str, Any]) -> bool:
    if sequence.get("launch_error"):
        return False
    expected = {"initialize", "browser_navigate", "browser_list_tabs", "browser_get_state", "browser_screenshot"}
    observed: set[str] = set()
    for step in sequence.get("steps", []):
        name = step.get("name")
        if isinstance(name, str):
            observed.add(name)
        if step.get("timed_out") or step.get("error"):
            return False
        if step.get("stdout_eof"):
            return False
        response_summary = step.get("response_summary")
        if isinstance(response_summary, dict) and response_summary.get("has_error"):
            return False
        if isinstance(response_summary, dict) and response_summary.get("result_is_error"):
            return False
        text = step.get("text")
        if isinstance(text, str) and text.lstrip().lower().startswith("error:"):
            return False
    return expected.issubset(observed)


def _browser_use_mcp_env_key_signature(sequence: dict[str, Any]) -> bool:
    navigate = _step_text(sequence, "browser_navigate")
    list_tabs = _step_text(sequence, "browser_list_tabs").strip()
    get_state = _step_text(sequence, "browser_get_state")
    screenshot = _step_text(sequence, "browser_screenshot")
    return (
        "BrowserStartEvent" in navigate
        and "timed out" in navigate
        and list_tabs == "[]"
        and "Expected at least one handler" in get_state
        and "Root CDP client not initialized" in screenshot
    )


def check_browser_use_mcp_env_key_probe() -> CheckResult:
    command_var = "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND"
    timeout_var = "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S"
    dummy_key_var = "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_DUMMY_OPENAI_KEY"
    cwd_var = "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_CWD"
    isolate_cwd_var = "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_ISOLATE_CWD"
    timeout_s, invalid_timeout = _float_env(timeout_var, 45)
    command = _json_env_list(command_var)
    command_cwd = os.environ.get(cwd_var) or None
    recommended = ["uvx", "--from", "browser-use[cli]", "browser-use", "--mcp"]
    if command is None:
        return CheckResult(
            name="browser_use_mcp_env_key_probe",
            status="skip",
            summary="Browser Use MCP env-key probe is opt-in; set a JSON command array to run it.",
            details={
                "command_env_var": command_var,
                "timeout_env_var": timeout_var,
                "dummy_key_env_var": dummy_key_var,
                "cwd_env_var": cwd_var,
                "isolate_cwd_env_var": isolate_cwd_var,
                "timeout_seconds": timeout_s,
                "invalid_timeout_env_value": invalid_timeout,
                "recommended_command": recommended,
                "related_upstream": "browser-use/browser-use#4846",
            },
        )
    if not command:
        return CheckResult(
            name="browser_use_mcp_env_key_probe",
            status="warn",
            summary="Browser Use MCP env-key command env var was set but was not a JSON string array.",
            details={
                "command_env_var": command_var,
                "timeout_env_var": timeout_var,
                "dummy_key_env_var": dummy_key_var,
                "cwd_env_var": cwd_var,
                "isolate_cwd_env_var": isolate_cwd_var,
                "timeout_seconds": timeout_s,
                "invalid_timeout_env_value": invalid_timeout,
            },
        )

    dummy_key = os.environ.get(dummy_key_var, "sk-proj-redacted-agent-windows-lab")
    isolate_override = _bool_env(isolate_cwd_var)
    isolate_cwd = bool(command_cwd) and (
        isolate_override if isolate_override is not None else _browser_use_mcp_command_can_isolate_cwd(command)
    )
    pythonpath_root = str(Path(command_cwd).resolve()) if isolate_cwd and command_cwd else None
    with _temporary_directory(prefix="agent-windows-lab-browser-use-no-key-") as no_key_config:
        without_key = _browser_use_mcp_tool_sequence(
            command,
            timeout_s=timeout_s,
            cwd=no_key_config if isolate_cwd else command_cwd,
            pythonpath_root=pythonpath_root,
            env_overrides={
                "OPENAI_API_KEY": None,
                "ANTHROPIC_API_KEY": None,
                "BROWSER_USE_CONFIG_DIR": no_key_config,
            },
        )
    with _temporary_directory(prefix="agent-windows-lab-browser-use-dummy-key-") as dummy_key_config:
        with_key = _browser_use_mcp_tool_sequence(
            command,
            timeout_s=timeout_s,
            cwd=dummy_key_config if isolate_cwd else command_cwd,
            pythonpath_root=pythonpath_root,
            env_overrides={
                "OPENAI_API_KEY": dummy_key,
                "ANTHROPIC_API_KEY": None,
                "BROWSER_USE_CONFIG_DIR": dummy_key_config,
            },
        )
    signature = _browser_use_mcp_env_key_signature(with_key)
    no_key_navigated = "Navigated to:" in _step_text(without_key, "browser_navigate")
    no_key_completed_cleanly = _browser_use_mcp_sequence_completed_cleanly(without_key)
    dummy_key_completed_cleanly = _browser_use_mcp_sequence_completed_cleanly(with_key)
    key_gated_signature = signature and no_key_completed_cleanly
    status = "warn" if signature or not no_key_completed_cleanly or not dummy_key_completed_cleanly else "pass"
    if key_gated_signature:
        summary = "Browser Use MCP reproduced the env-key browser startup failure signature."
    elif signature:
        summary = "Browser Use MCP reproduced the browser startup failure signature; the no-key run also failed."
    elif no_key_navigated and not no_key_completed_cleanly:
        summary = "Browser Use MCP no-key baseline failed after navigation."
    elif not no_key_completed_cleanly:
        summary = "Browser Use MCP no-key baseline did not complete cleanly."
    elif not dummy_key_completed_cleanly:
        summary = "Browser Use MCP dummy-key run failed outside the known startup signature."
    else:
        summary = "Browser Use MCP did not reproduce the env-key startup failure signature."
    return CheckResult(
        name="browser_use_mcp_env_key_probe",
        status=status,
        summary=summary,
        details={
            "command": command,
            "cwd": command_cwd,
            "env_key_probe_uses_isolated_cwd": isolate_cwd,
            "isolate_cwd_env_var": isolate_cwd_var,
            "isolate_cwd_env_value": os.environ.get(isolate_cwd_var),
            "timeout_seconds": timeout_s,
            "invalid_timeout_env_value": invalid_timeout,
            "dummy_openai_key_present": True,
            "without_key": without_key,
            "with_dummy_openai_key": with_key,
            "no_key_navigated": no_key_navigated,
            "no_key_completed_cleanly": no_key_completed_cleanly,
            "dummy_key_completed_cleanly": dummy_key_completed_cleanly,
            "env_key_failure_signature": signature,
            "key_gated_failure_signature": key_gated_signature,
            "isolated_config_dirs": True,
            "related_upstream": "browser-use/browser-use#4846",
        },
    )


CASE_CHECKS: dict[str, tuple[CheckFn, ...]] = {
    "browser": (check_browser_agent_environment_probe,),
    "browser-use-mcp": (
        check_browser_agent_environment_probe,
        check_browser_use_mcp_startup_probe,
        check_browser_use_mcp_env_key_probe,
    ),
    "environment": (check_environment,),
    "encoding": (check_python_child_stdout_encoding, check_shell_encoding_probe),
    "mcp": (check_stdio_newline_framing, check_mcp_stdio_jsonrpc_probe),
    "mcp-python-sdk-session": (check_mcp_python_sdk_session_lifecycle_probe,),
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
        ("%TEMP%", tempfile.gettempdir()),
        ("%WORKSPACE%", str(Path.cwd())),
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
