from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_windows_lab.harness import (
    ARGUMENTS_WITH_SHELL_METACHARS,
    _temporary_directory,
    available_cases,
    available_issue_targets,
    check_browser_agent_environment_probe,
    check_browser_use_mcp_env_key_probe,
    check_browser_use_mcp_startup_probe,
    check_mcp_python_sdk_session_lifecycle_probe,
    check_mcp_stdio_jsonrpc_probe,
    check_node_argument_roundtrip,
    check_python_child_stdout_encoding,
    check_shell_launch_context,
    check_stdio_newline_framing,
    check_subprocess_argument_roundtrip,
    issue_packet_to_markdown,
    redact_report,
    report_to_markdown,
    run_all_checks,
    run_checks,
)
from verify_redacted_report import find_redaction_leaks


class HarnessTests(unittest.TestCase):
    def test_subprocess_argument_roundtrip(self) -> None:
        result = check_subprocess_argument_roundtrip()
        self.assertEqual(result.status, "pass", result.details)
        self.assertEqual(result.details["observed"], ARGUMENTS_WITH_SHELL_METACHARS)

    def test_stdio_newline_framing_has_binary_lf(self) -> None:
        result = check_stdio_newline_framing()
        self.assertIn(result.status, {"pass", "warn"})
        self.assertTrue(result.details["binary_is_lf"], result.details)
        self.assertIn("text_has_crlf", result.details)

    def test_python_child_stdout_encoding_probe_is_evidence_not_failure(self) -> None:
        result = check_python_child_stdout_encoding()
        self.assertIn(result.status, {"pass", "warn"})
        self.assertIn("returncode", result.details)
        self.assertIn("stdout_encoding", result.details)
        self.assertIn("stdout_hex", result.details)
        self.assertIn("stdout", result.details)

    def test_node_roundtrip_is_pass_or_skip(self) -> None:
        result = check_node_argument_roundtrip()
        self.assertIn(result.status, {"pass", "skip", "warn"}, result.details)

    def test_node_roundtrip_timeout_is_evidence_not_crash(self) -> None:
        timeout = subprocess.TimeoutExpired(["node", "echo args.mjs"], timeout=20)
        with patch("agent_windows_lab.harness.shutil.which", return_value="node"):
            with patch("agent_windows_lab.harness._run", side_effect=timeout):
                result = check_node_argument_roundtrip()

        self.assertEqual(result.status, "warn", result.details)
        self.assertEqual(result.details["timeout_seconds"], 20)
        self.assertEqual(result.details["expected"], ARGUMENTS_WITH_SHELL_METACHARS)

    def test_mcp_stdio_jsonrpc_probe(self) -> None:
        result = check_mcp_stdio_jsonrpc_probe()
        self.assertEqual(result.status, "pass", result.details)
        self.assertTrue(result.details["lf_framed"], result.details)
        self.assertEqual(result.details["response"]["id"], 1)

    def test_shell_launch_context_is_evidence_not_failure(self) -> None:
        result = check_shell_launch_context()
        self.assertIn(result.status, {"pass", "warn"}, result.details)
        self.assertTrue(result.details, result.details)

    def test_browser_agent_environment_probe_is_evidence_not_failure(self) -> None:
        result = check_browser_agent_environment_probe()
        self.assertIn(result.status, {"pass", "warn"}, result.details)
        self.assertTrue(result.details["profile_roundtrip"]["ok"])

    def test_browser_use_mcp_startup_probe_is_opt_in(self) -> None:
        with patch.dict("os.environ", {"AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": ""}, clear=False):
            result = check_browser_use_mcp_startup_probe()
        self.assertEqual(result.status, "skip", result.details)
        self.assertIn("AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND", result.details["command_env_var"])

    def test_browser_use_mcp_startup_probe_handles_bad_timeout_when_skipped(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": "",
                "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S": "not-a-number",
            },
            clear=False,
        ):
            result = check_browser_use_mcp_startup_probe()

        self.assertEqual(result.status, "skip", result.details)
        self.assertEqual(result.details["timeout_seconds"], 45)
        self.assertEqual(result.details["invalid_timeout_env_value"], "not-a-number")

    def test_browser_use_mcp_startup_probe_rejects_nonfinite_timeout(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            script = Path(raw) / "mcp.py"
            script.write_text(
                "import json, sys\n"
                "request = json.loads(sys.stdin.buffer.readline().decode('utf-8'))\n"
                "response = {'jsonrpc': '2.0', 'id': request.get('id'), 'result': {}}\n"
                "sys.stdout.buffer.write(json.dumps(response).encode('utf-8') + b'\\n')\n"
                "sys.stdout.buffer.flush()\n",
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps([sys.executable, str(script)]),
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S": "NaN",
                },
                clear=False,
            ):
                result = check_browser_use_mcp_startup_probe()

        self.assertEqual(result.status, "pass", result.details)
        self.assertEqual(result.details["timeout_seconds"], 45)
        self.assertEqual(result.details["invalid_timeout_env_value"], "NaN")

    def test_browser_use_mcp_startup_probe_uses_valid_initialize_shape(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            script = Path(raw) / "strict_mcp.py"
            script.write_text(
                "import json, sys\n"
                "request = json.loads(sys.stdin.buffer.readline().decode('utf-8'))\n"
                "client = request.get('params', {}).get('clientInfo', {})\n"
                "if client.get('name') and client.get('version'):\n"
                "    response = {'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'clientInfo': client}}\n"
                "else:\n"
                "    response = {'jsonrpc': '2.0', 'id': request.get('id'), 'error': {'code': -32602}}\n"
                "sys.stdout.buffer.write(json.dumps(response).encode('utf-8') + b'\\n')\n"
                "sys.stdout.buffer.flush()\n",
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {"AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps([sys.executable, str(script)])},
                clear=False,
            ):
                result = check_browser_use_mcp_startup_probe()

        self.assertEqual(result.status, "pass", result.details)
        self.assertIn("version", result.details["response"].get("result", {}).get("clientInfo", {}))

    def test_browser_use_mcp_startup_probe_keeps_stdin_open_until_response(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            script = Path(raw) / "stdin_sensitive_mcp.py"
            script.write_text(
                "import json, sys, threading, time\n"
                "request = json.loads(sys.stdin.buffer.readline().decode('utf-8'))\n"
                "state = {'eof': False}\n"
                "def read_more():\n"
                "    state['eof'] = sys.stdin.buffer.read(1) == b''\n"
                "threading.Thread(target=read_more, daemon=True).start()\n"
                "time.sleep(0.2)\n"
                "if state['eof']:\n"
                "    response = {'jsonrpc': '2.0', 'id': request.get('id'), 'error': {'code': -32000}}\n"
                "else:\n"
                "    response = {'jsonrpc': '2.0', 'id': request.get('id'), 'result': {}}\n"
                "sys.stdout.buffer.write(json.dumps(response).encode('utf-8') + b'\\n')\n"
                "sys.stdout.buffer.flush()\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps([sys.executable, str(script)]),
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S": "5",
                },
                clear=False,
            ):
                result = check_browser_use_mcp_startup_probe()

        self.assertEqual(result.status, "pass", result.details)

    def test_browser_use_mcp_startup_probe_preserves_partial_stdout_on_timeout(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            script = Path(raw) / "partial_stdout_mcp.py"
            script.write_text(
                "import sys, time\n"
                "sys.stdin.buffer.readline()\n"
                "sys.stdout.buffer.write(b'{\"jsonrpc\"')\n"
                "sys.stdout.buffer.flush()\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps([sys.executable, str(script)]),
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S": "0.2",
                },
                clear=False,
            ):
                result = check_browser_use_mcp_startup_probe()

        self.assertEqual(result.status, "warn", result.details)
        self.assertTrue(result.details["timed_out"], result.details)
        self.assertIn('{"jsonrpc"', result.details["stdout"])

    def test_browser_use_mcp_startup_probe_kills_child_after_stdin_oserror(self) -> None:
        class BrokenStdin:
            closed = False

            def write(self, _payload: bytes) -> int:
                raise BrokenPipeError("closed")

            def flush(self) -> None:
                raise AssertionError("flush should not be reached")

            def close(self) -> None:
                self.closed = True

        class EmptyStream:
            closed = False

            def read(self, _size: int = -1) -> bytes:
                return b""

            def readline(self) -> bytes:
                return b""

            def close(self) -> None:
                self.closed = True

        class FakeProcess:
            def __init__(self) -> None:
                self.stdin = BrokenStdin()
                self.stdout = EmptyStream()
                self.stderr = EmptyStream()
                self.killed = False
                self.waited = False

            def poll(self) -> int | None:
                return None if not self.killed else -9

            def kill(self) -> None:
                self.killed = True

            def wait(self, timeout: int | None = None) -> int:
                self.waited = True
                return -9

        fake = FakeProcess()
        with patch.dict(
            "os.environ",
            {"AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps(["fake-browser-use-mcp"])},
            clear=False,
        ):
            with patch("agent_windows_lab.harness.subprocess.Popen", return_value=fake):
                result = check_browser_use_mcp_startup_probe()

        self.assertEqual(result.status, "warn", result.details)
        self.assertTrue(fake.killed)
        self.assertTrue(fake.waited)

    def test_browser_use_mcp_startup_probe_does_not_block_on_stdout_tail(self) -> None:
        class WritableStdin:
            closed = False

            def write(self, payload: bytes) -> int:
                return len(payload)

            def flush(self) -> None:
                return None

            def close(self) -> None:
                self.closed = True

        class ResponseStream:
            closed = False

            def readline(self) -> bytes:
                return b'{"jsonrpc":"2.0","id":1,"result":{}}\n'

            def read(self, _size: int = -1) -> bytes:
                raise AssertionError("stdout tail reads can block when child processes inherit the pipe")

            def close(self) -> None:
                self.closed = True

        class EmptyStream:
            closed = False

            def read(self, _size: int = -1) -> bytes:
                return b""

            def close(self) -> None:
                self.closed = True

        class FakeProcess:
            def __init__(self) -> None:
                self.stdin = WritableStdin()
                self.stdout = ResponseStream()
                self.stderr = EmptyStream()
                self.returncode = None
                self.terminated = False
                self.waited = False

            def poll(self) -> int | None:
                return None if not self.terminated else 0

            def terminate(self) -> None:
                self.terminated = True
                self.returncode = 0

            def kill(self) -> None:
                self.terminated = True
                self.returncode = -9

            def wait(self, timeout: int | None = None) -> int:
                self.waited = True
                self.terminated = True
                self.returncode = 0
                return 0

        fake = FakeProcess()
        with patch.dict(
            "os.environ",
            {"AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps(["fake-browser-use-mcp"])},
            clear=False,
        ):
            with patch("agent_windows_lab.harness.subprocess.Popen", return_value=fake):
                result = check_browser_use_mcp_startup_probe()

        self.assertEqual(result.status, "pass", result.details)
        self.assertTrue(fake.waited)

    def test_browser_use_mcp_startup_probe_reads_response_before_exit(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            script = Path(raw) / "long_running_mcp.py"
            script.write_text(
                "import json, sys, time\n"
                "request = json.loads(sys.stdin.buffer.readline().decode('utf-8'))\n"
                "response = {'jsonrpc': '2.0', 'id': request.get('id'), 'result': {}}\n"
                "sys.stdout.buffer.write(json.dumps(response).encode('utf-8') + b'\\n')\n"
                "sys.stdout.buffer.flush()\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps([sys.executable, str(script)]),
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S": "5",
                },
                clear=False,
            ):
                result = check_browser_use_mcp_startup_probe()

        self.assertEqual(result.status, "pass", result.details)
        self.assertEqual(result.details["response"]["id"], 1)

    def test_browser_use_mcp_startup_probe_rejects_jsonrpc_error(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            script = Path(raw) / "error_mcp.py"
            script.write_text(
                "import json, sys\n"
                "request = json.loads(sys.stdin.buffer.readline().decode('utf-8'))\n"
                "response = {'jsonrpc': '2.0', 'id': request.get('id'), 'error': {'code': -32602}}\n"
                "sys.stdout.buffer.write(json.dumps(response).encode('utf-8') + b'\\n')\n"
                "sys.stdout.buffer.flush()\n",
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {"AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps([sys.executable, str(script)])},
                clear=False,
            ):
                result = check_browser_use_mcp_startup_probe()

        self.assertEqual(result.status, "warn", result.details)
        self.assertIn("error", result.details["response"])

    def test_browser_use_mcp_startup_probe_drains_stderr_before_stdout(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            script = Path(raw) / "chatty_mcp.py"
            script.write_text(
                "import json, sys\n"
                "sys.stderr.buffer.write(b'x' * (1024 * 1024))\n"
                "sys.stderr.buffer.flush()\n"
                "request = json.loads(sys.stdin.buffer.readline().decode('utf-8'))\n"
                "response = {'jsonrpc': '2.0', 'id': request.get('id'), 'result': {}}\n"
                "sys.stdout.buffer.write(json.dumps(response).encode('utf-8') + b'\\n')\n"
                "sys.stdout.buffer.flush()\n",
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps([sys.executable, str(script)]),
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S": "5",
                },
                clear=False,
            ):
                result = check_browser_use_mcp_startup_probe()

        self.assertEqual(result.status, "pass", result.details)
        self.assertTrue(result.details["stderr_hex"])

    def test_browser_use_mcp_env_key_probe_is_opt_in(self) -> None:
        with patch.dict("os.environ", {"AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": ""}, clear=False):
            result = check_browser_use_mcp_env_key_probe()

        self.assertEqual(result.status, "skip", result.details)
        self.assertIn("AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND", result.details["command_env_var"])

    def test_browser_use_mcp_env_key_probe_reports_launch_error(self) -> None:
        with patch.dict(
            "os.environ",
            {"AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps(["definitely-missing-browser-use-mcp"])},
            clear=False,
        ):
            result = check_browser_use_mcp_env_key_probe()

        self.assertEqual(result.status, "warn", result.details)
        self.assertIn("launch_error", result.details["without_key"])

    def test_browser_use_mcp_env_key_probe_reports_stdout_eof_without_timeout(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            script = Path(raw) / "exit_immediately.py"
            script.write_text("raise SystemExit(0)\n", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps([sys.executable, str(script)]),
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S": "5",
                },
                clear=False,
            ):
                result = check_browser_use_mcp_env_key_probe()

        self.assertEqual(result.status, "warn", result.details)
        self.assertTrue(result.details["without_key"]["steps"][0]["stdout_eof"], result.details)
        self.assertFalse(result.details["without_key"]["steps"][0]["timed_out"], result.details)
        self.assertLess(result.details["without_key"]["elapsed_seconds"], 3, result.details)

    def test_browser_use_mcp_env_key_probe_warns_on_unexpected_dummy_key_failure(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            script = Path(raw) / "browser_use_unexpected_failure_mcp.py"
            script.write_text(
                "import json, os, sys\n"
                "def write(payload):\n"
                "    sys.stdout.buffer.write(json.dumps(payload).encode('utf-8') + b'\\n')\n"
                "    sys.stdout.buffer.flush()\n"
                "while True:\n"
                "    line = sys.stdin.buffer.readline()\n"
                "    if not line:\n"
                "        break\n"
                "    request = json.loads(line.decode('utf-8'))\n"
                "    method = request.get('method')\n"
                "    if method == 'notifications/initialized':\n"
                "        continue\n"
                "    if method == 'initialize':\n"
                "        write({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'serverInfo': {'name': 'fake'}}})\n"
                "        continue\n"
                "    tool = request.get('params', {}).get('name')\n"
                "    has_key = bool(os.environ.get('OPENAI_API_KEY'))\n"
                "    if has_key and tool == 'browser_navigate':\n"
                "        text = 'Browser failed to launch'\n"
                "        is_error = True\n"
                "    elif tool == 'browser_navigate':\n"
                "        text = 'Navigated to: https://example.com/'\n"
                "        is_error = False\n"
                "    elif tool == 'browser_list_tabs':\n"
                "        text = '[{\"tab_id\":\"1234\",\"url\":\"https://example.com/\"}]'\n"
                "        is_error = False\n"
                "    elif tool == 'browser_get_state':\n"
                "        text = '{\"url\":\"https://example.com/\"}'\n"
                "        is_error = False\n"
                "    else:\n"
                "        text = '{\"size_bytes\": 10}'\n"
                "        is_error = False\n"
                "    write({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'isError': is_error, 'content': [{'type': 'text', 'text': text}]}})\n",
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps([sys.executable, str(script)]),
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S": "5",
                },
                clear=False,
            ):
                result = check_browser_use_mcp_env_key_probe()

        self.assertEqual(result.status, "warn", result.details)
        self.assertTrue(result.details["no_key_navigated"], result.details)
        self.assertFalse(result.details["env_key_failure_signature"], result.details)
        self.assertFalse(result.details["dummy_key_completed_cleanly"], result.details)
        step = result.details["with_dummy_openai_key"]["steps"][1]
        self.assertTrue(step["response_summary"]["result_is_error"], result.details)

    def test_browser_use_mcp_env_key_probe_warns_on_dirty_no_key_baseline(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            script = Path(raw) / "browser_use_dirty_baseline_mcp.py"
            script.write_text(
                "import json, os, sys\n"
                "def write(payload):\n"
                "    sys.stdout.buffer.write(json.dumps(payload).encode('utf-8') + b'\\n')\n"
                "    sys.stdout.buffer.flush()\n"
                "while True:\n"
                "    line = sys.stdin.buffer.readline()\n"
                "    if not line:\n"
                "        break\n"
                "    request = json.loads(line.decode('utf-8'))\n"
                "    method = request.get('method')\n"
                "    if method == 'notifications/initialized':\n"
                "        continue\n"
                "    if method == 'initialize':\n"
                "        write({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'serverInfo': {'name': 'fake'}}})\n"
                "        continue\n"
                "    tool = request.get('params', {}).get('name')\n"
                "    has_key = bool(os.environ.get('OPENAI_API_KEY'))\n"
                "    is_error = False\n"
                "    if tool == 'browser_navigate':\n"
                "        text = 'Navigated to: https://example.com/'\n"
                "    elif not has_key and tool == 'browser_list_tabs':\n"
                "        text = 'tab enumeration failed'\n"
                "        is_error = True\n"
                "    elif tool == 'browser_list_tabs':\n"
                "        text = '[{\"tab_id\":\"1234\",\"url\":\"https://example.com/\"}]'\n"
                "    elif tool == 'browser_get_state':\n"
                "        text = '{\"url\":\"https://example.com/\"}'\n"
                "    else:\n"
                "        text = '{\"size_bytes\": 10}'\n"
                "    write({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'isError': is_error, 'content': [{'type': 'text', 'text': text}]}})\n",
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps([sys.executable, str(script)]),
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S": "5",
                },
                clear=False,
            ):
                result = check_browser_use_mcp_env_key_probe()

        self.assertEqual(result.status, "warn", result.details)
        self.assertTrue(result.details["no_key_navigated"], result.details)
        self.assertFalse(result.details["no_key_completed_cleanly"], result.details)
        self.assertTrue(result.details["dummy_key_completed_cleanly"], result.details)
        self.assertFalse(result.details["key_gated_failure_signature"], result.details)

    def test_browser_use_mcp_env_key_probe_can_preserve_source_cwd(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            script = Path(raw) / "browser_use_cwd_sensitive_mcp.py"
            script.write_text(
                "import json, os, sys\n"
                "def write(payload):\n"
                "    sys.stdout.buffer.write(json.dumps(payload).encode('utf-8') + b'\\n')\n"
                "    sys.stdout.buffer.flush()\n"
                "while True:\n"
                "    line = sys.stdin.buffer.readline()\n"
                "    if not line:\n"
                "        break\n"
                "    request = json.loads(line.decode('utf-8'))\n"
                "    method = request.get('method')\n"
                "    if method == 'notifications/initialized':\n"
                "        continue\n"
                "    if method == 'initialize':\n"
                "        write({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'serverInfo': {'name': 'fake'}}})\n"
                "        continue\n"
                "    tool = request.get('params', {}).get('name')\n"
                "    if os.environ.get('AGENT_WINDOWS_LAB_BROWSER_USE_MCP_CWD') != os.getcwd():\n"
                "        text = 'source checkout cwd was not preserved'\n"
                "        write({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'isError': True, 'content': [{'type': 'text', 'text': text}]}})\n"
                "        continue\n"
                "    text = {\n"
                "        'browser_navigate': 'Navigated to: https://example.com/',\n"
                "        'browser_list_tabs': '[{\"tab_id\":\"1234\",\"url\":\"https://example.com/\"}]',\n"
                "        'browser_get_state': '{\"url\":\"https://example.com/\"}',\n"
                "        'browser_screenshot': '{\"size_bytes\": 10}',\n"
                "    }.get(tool, 'unknown')\n"
                "    write({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'content': [{'type': 'text', 'text': text}]}})\n",
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps([sys.executable, str(script)]),
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_CWD": raw,
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_ISOLATE_CWD": "false",
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S": "5",
                },
                clear=False,
            ):
                result = check_browser_use_mcp_env_key_probe()

        self.assertEqual(result.status, "pass", result.details)
        self.assertFalse(result.details["env_key_probe_uses_isolated_cwd"], result.details)

    def test_browser_use_mcp_env_key_probe_resolves_relative_isolated_pythonpath(self) -> None:
        fixture_root = ROOT / ".tmp"
        fixture_root.mkdir(exist_ok=True)
        raw_path = fixture_root / f"agent-windows-lab-test-relative-pythonpath-{uuid.uuid4().hex}"
        raw_path.mkdir()
        try:
            raw = str(raw_path)
            package = Path(raw) / "browser_use"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "mcp.py").write_text(
                "import json, sys\n"
                "def write(payload):\n"
                "    sys.stdout.buffer.write(json.dumps(payload).encode('utf-8') + b'\\n')\n"
                "    sys.stdout.buffer.flush()\n"
                "while True:\n"
                "    line = sys.stdin.buffer.readline()\n"
                "    if not line:\n"
                "        break\n"
                "    request = json.loads(line.decode('utf-8'))\n"
                "    method = request.get('method')\n"
                "    if method == 'notifications/initialized':\n"
                "        continue\n"
                "    if method == 'initialize':\n"
                "        write({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'serverInfo': {'name': 'fake'}}})\n"
                "        continue\n"
                "    tool = request.get('params', {}).get('name')\n"
                "    text = {\n"
                "        'browser_navigate': 'Navigated to: https://example.com/',\n"
                "        'browser_list_tabs': '[{\"tab_id\":\"1234\",\"url\":\"https://example.com/\"}]',\n"
                "        'browser_get_state': '{\"url\":\"https://example.com/\"}',\n"
                "        'browser_screenshot': '{\"size_bytes\": 10}',\n"
                "    }.get(tool, 'unknown')\n"
                "    write({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'content': [{'type': 'text', 'text': text}]}})\n",
                encoding="utf-8",
            )
            relative_checkout = os.path.relpath(raw, Path.cwd())
            with patch.dict(
                "os.environ",
                {
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps(
                        [sys.executable, "-m", "browser_use.mcp"]
                    ),
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_CWD": relative_checkout,
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S": "5",
                },
                clear=False,
            ):
                result = check_browser_use_mcp_env_key_probe()
        finally:
            shutil.rmtree(raw_path, ignore_errors=True)

        self.assertEqual(result.status, "pass", result.details)
        self.assertTrue(result.details["env_key_probe_uses_isolated_cwd"], result.details)

    def test_browser_use_mcp_env_key_probe_detects_4846_signature(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            script = Path(raw) / "browser_use_4846_mcp.py"
            script.write_text(
                "import json, os, sys\n"
                "def write(payload):\n"
                "    sys.stdout.buffer.write(json.dumps(payload).encode('utf-8') + b'\\n')\n"
                "    sys.stdout.buffer.flush()\n"
                "while True:\n"
                "    line = sys.stdin.buffer.readline()\n"
                "    if not line:\n"
                "        break\n"
                "    request = json.loads(line.decode('utf-8'))\n"
                "    method = request.get('method')\n"
                "    if method == 'notifications/initialized':\n"
                "        continue\n"
                "    if method == 'initialize':\n"
                "        write({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'serverInfo': {'name': 'fake'}}})\n"
                "        continue\n"
                "    tool = request.get('params', {}).get('name')\n"
                "    write({'jsonrpc': '2.0', 'method': 'notifications/progress', 'params': {'tool': tool}})\n"
                "    has_key = bool(os.environ.get('OPENAI_API_KEY'))\n"
                "    if not has_key:\n"
                "        if 'OPENAI_API_KEY' in os.environ:\n"
                "            text = 'OPENAI_API_KEY was not removed'\n"
                "            write({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'isError': True, 'content': [{'type': 'text', 'text': text}]}})\n"
                "            continue\n"
                "        if os.environ.get('AGENT_WINDOWS_LAB_BROWSER_USE_MCP_CWD') == os.getcwd():\n"
                "            text = 'source checkout cwd was not isolated'\n"
                "            write({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'isError': True, 'content': [{'type': 'text', 'text': text}]}})\n"
                "            continue\n"
                "        text = {\n"
                "            'browser_navigate': 'Navigated to: https://example.com/',\n"
                "            'browser_list_tabs': '[{\"tab_id\":\"1234\",\"url\":\"https://example.com/\"}]',\n"
                "            'browser_get_state': '{\"url\":\"https://example.com/\"}',\n"
                "            'browser_screenshot': '{\"size_bytes\": 10}',\n"
                "        }.get(tool, 'unknown')\n"
                "    else:\n"
                "        text = {\n"
                "            'browser_navigate': 'Error: Event handler BrowserStartEvent timed out after 30.0s',\n"
                "            'browser_list_tabs': '[]',\n"
                "            'browser_get_state': 'Error: Expected at least one handler to return a non-None result',\n"
                "            'browser_screenshot': 'Error: Root CDP client not initialized',\n"
                "        }.get(tool, 'unknown')\n"
                "    write({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'content': [{'type': 'text', 'text': text}]}})\n",
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": json.dumps([sys.executable, str(script)]),
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_CWD": raw,
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_ISOLATE_CWD": "true",
                    "AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S": "5",
                },
                clear=False,
            ):
                result = check_browser_use_mcp_env_key_probe()

        self.assertEqual(result.status, "warn", result.details)
        self.assertTrue(result.details["no_key_navigated"], result.details)
        self.assertTrue(result.details["no_key_completed_cleanly"], result.details)
        self.assertTrue(result.details["env_key_failure_signature"], result.details)
        self.assertTrue(result.details["key_gated_failure_signature"], result.details)
        self.assertTrue(result.details["dummy_openai_key_present"])
        step = result.details["with_dummy_openai_key"]["steps"][-1]
        self.assertIn("response_summary", step)
        self.assertNotIn("response", step)

    def test_run_all_checks_report_shape(self) -> None:
        report = run_all_checks()
        names = {check["name"] for check in report["checks"]}
        self.assertEqual(report["cases"], ["all"])
        self.assertIn("environment", names)
        self.assertIn("stdio_newline_framing", names)
        self.assertIn("subprocess_argument_roundtrip", names)
        self.assertIn("mcp_stdio_jsonrpc_probe", names)
        self.assertIn("browser_agent_environment_probe", names)
        environment = next(check for check in report["checks"] if check["name"] == "environment")
        self.assertIn("python_default_encoding", environment["details"])
        self.assertIn("preferred_encoding", environment["details"])
        self.assertNotIn("fail", report["summary"], report)

    def test_available_cases_include_issue_repro_groups(self) -> None:
        self.assertEqual(
            available_cases(),
            [
                "all",
                "browser",
                "browser-use-mcp",
                "encoding",
                "environment",
                "mcp",
                "mcp-python-sdk-session",
                "paths",
                "shell",
                "stdio",
                "subprocess",
            ],
        )

    def test_available_issue_targets_include_first_upstream_lanes(self) -> None:
        self.assertIn("browser-use", available_issue_targets())
        self.assertIn("modelcontextprotocol-python-sdk", available_issue_targets())
        self.assertIn("modelcontextprotocol-typescript-sdk", available_issue_targets())
        self.assertIn("microsoft-playwright-mcp", available_issue_targets())

    def test_run_checks_filters_to_focused_case_with_environment_context(self) -> None:
        report = run_checks(["stdio"])
        self.assertEqual(report["cases"], ["stdio"])
        self.assertEqual(
            [check["name"] for check in report["checks"]],
            ["environment", "stdio_newline_framing"],
        )

    def test_run_checks_accepts_multiple_cases_without_duplicate_checks(self) -> None:
        report = run_checks(["stdio", "encoding", "stdio"])
        self.assertEqual(report["cases"], ["stdio", "encoding"])
        names = [check["name"] for check in report["checks"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names[0], "environment")
        self.assertIn("stdio_newline_framing", names)
        self.assertIn("python_child_stdout_encoding", names)
        self.assertIn("shell_encoding_probe", names)

    def test_run_checks_mcp_case_contains_stdio_context(self) -> None:
        report = run_checks(["mcp"])
        names = [check["name"] for check in report["checks"]]
        self.assertEqual(report["cases"], ["mcp"])
        self.assertEqual(names[0], "environment")
        self.assertIn("stdio_newline_framing", names)
        self.assertIn("mcp_stdio_jsonrpc_probe", names)

    def test_mcp_python_sdk_session_case_skips_without_sdk(self) -> None:
        with patch("importlib.util.find_spec", return_value=None):
            result = check_mcp_python_sdk_session_lifecycle_probe()
        self.assertEqual(result.status, "skip")
        self.assertIn("install_hint", result.details)

    def test_run_checks_mcp_python_sdk_session_case_contains_probe(self) -> None:
        with patch("importlib.util.find_spec", return_value=None):
            report = run_checks(["mcp-python-sdk-session"])
        names = [check["name"] for check in report["checks"]]
        self.assertEqual(report["cases"], ["mcp-python-sdk-session"])
        self.assertEqual(names[0], "environment")
        self.assertIn("mcp_python_sdk_session_lifecycle_probe", names)

    def test_run_checks_browser_use_mcp_case_contains_startup_context(self) -> None:
        with patch.dict("os.environ", {"AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND": ""}, clear=False):
            report = run_checks(["browser-use-mcp"])
        names = [check["name"] for check in report["checks"]]
        self.assertEqual(report["cases"], ["browser-use-mcp"])
        self.assertEqual(names[0], "environment")
        self.assertIn("browser_agent_environment_probe", names)
        self.assertIn("browser_use_mcp_startup_probe", names)
        self.assertIn("browser_use_mcp_env_key_probe", names)

    def test_run_checks_rejects_unknown_case(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown case"):
            run_checks(["stdio", "missing"])

    def test_markdown_report_contains_statuses(self) -> None:
        report = run_all_checks()
        markdown = report_to_markdown(report)
        self.assertIn("# Agent Windows Lab Report", markdown)
        self.assertIn("stdio_newline_framing", markdown)

    def test_redact_report_sanitizes_local_paths(self) -> None:
        temp_path = str(Path(tempfile.gettempdir()) / "Agent Windows Lab abc" / "file.txt")
        profile_path = str(Path.home() / "Documents" / "project" / "file.py")
        report = {
            "platform": "Windows-11",
            "checks": [
                {
                    "name": "sample",
                    "status": "fail",
                    "details": {
                        "path": temp_path,
                        "stderr_hex": temp_path.encode("utf-8").hex(),
                        "tool": r"C:\Program Files\Git\cmd\git.EXE",
                        "unc_tool": r"\\server\share\git.exe",
                        "posix_tool": "/opt/homebrew/bin/node",
                        "raw_hex": b"value=\xe9".hex(),
                        "nested": [profile_path],
                    },
                }
            ],
        }
        redacted = redact_report(report)
        details = redacted["checks"][0]["details"]
        payload = json.dumps(redacted)
        self.assertTrue(redacted["redacted"])
        self.assertEqual(redacted["checks"][0]["status"], "fail")
        self.assertNotIn(temp_path, payload)
        self.assertNotIn(profile_path, payload)
        self.assertNotIn(temp_path.encode("utf-8").hex(), payload)
        self.assertIn("%USERPROFILE%", payload)
        self.assertIn("%TEMP%", payload)
        self.assertTrue(details["path"].startswith("%TEMP%"))
        self.assertIn("%TEMP%", bytes.fromhex(details["stderr_hex"]).decode("utf-8"))
        self.assertEqual(details["tool"], "%PATH%")
        self.assertEqual(details["unc_tool"], "%PATH%")
        self.assertEqual(details["posix_tool"], "%PATH%")
        self.assertEqual(details["raw_hex"], b"value=\xe9".hex())
        self.assertEqual(find_redaction_leaks(redacted), [])

    def test_cli_e2e_json(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_agent_windows_lab.py"), "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["name"], "agent-windows-lab")
        self.assertNotIn("fail", report["summary"], report)

    def test_cli_e2e_redacted_json(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_agent_windows_lab.py"), "--json", "--redact"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        payload = json.dumps(report)
        self.assertTrue(report["redacted"])
        self.assertNotIn(str(Path.home()), payload)
        self.assertNotIn(Path.home().name, payload)

    def test_issue_packet_markdown_uses_redacted_report(self) -> None:
        report = redact_report(run_checks(["mcp"]))
        markdown = issue_packet_to_markdown(report, target="modelcontextprotocol-python-sdk")
        self.assertIn("modelcontextprotocol/python-sdk", markdown)
        self.assertIn("--case mcp", markdown)
        self.assertIn("agent-windows-lab-report.json", markdown)
        self.assertNotIn(str(Path.home()), markdown)

    def test_cli_e2e_focused_case_json(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_agent_windows_lab.py"),
                "--json",
                "--redact",
                "--case",
                "stdio",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["cases"], ["stdio"])
        self.assertEqual(
            [check["name"] for check in report["checks"]],
            ["environment", "stdio_newline_framing"],
        )

    def test_cli_e2e_issue_packet_implies_redaction(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            out = Path(raw)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_agent_windows_lab.py"),
                    "--out",
                    str(out),
                    "--case",
                    "mcp",
                    "--issue-target",
                    "modelcontextprotocol-python-sdk",
                    "--json",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            issue_markdown = (out / "agent-windows-lab-issue.md").read_text(encoding="utf-8")
            self.assertTrue(report["redacted"])
            self.assertIn("modelcontextprotocol/python-sdk", issue_markdown)
            self.assertEqual(find_redaction_leaks(report), [])


if __name__ == "__main__":
    unittest.main()
