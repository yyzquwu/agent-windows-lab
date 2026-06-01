from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_windows_lab.harness import (
    ARGUMENTS_WITH_SHELL_METACHARS,
    check_node_argument_roundtrip,
    check_python_child_stdout_encoding,
    check_stdio_newline_framing,
    check_subprocess_argument_roundtrip,
    report_to_markdown,
    run_all_checks,
)


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


if __name__ == "__main__":
    unittest.main()
