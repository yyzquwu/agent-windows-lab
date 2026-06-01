from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_windows_lab.harness import (
    ARGUMENTS_WITH_SHELL_METACHARS,
    check_node_argument_roundtrip,
    check_python_child_stdout_encoding,
    check_stdio_newline_framing,
    check_subprocess_argument_roundtrip,
    redact_report,
    report_to_markdown,
    run_all_checks,
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
        self.assertIn(result.status, {"pass", "skip"}, result.details)

    def test_run_all_checks_report_shape(self) -> None:
        report = run_all_checks()
        names = {check["name"] for check in report["checks"]}
        self.assertIn("environment", names)
        self.assertIn("stdio_newline_framing", names)
        self.assertIn("subprocess_argument_roundtrip", names)
        environment = next(check for check in report["checks"] if check["name"] == "environment")
        self.assertIn("python_default_encoding", environment["details"])
        self.assertIn("preferred_encoding", environment["details"])
        self.assertNotIn("fail", report["summary"], report)

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


if __name__ == "__main__":
    unittest.main()
