from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SRC = ROOT / "src"
import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_windows_lab.harness import _temporary_directory
from verify_shareable_artifact import find_shareable_artifact_leaks


class VerifyShareableArtifactTests(unittest.TestCase):
    def test_rejects_raw_issue_body_and_private_path(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            path = Path(raw) / "target.json"
            path.write_text(
                json.dumps(
                    {
                        "best_issue": {
                            "title": "Windows issue",
                            "body": "raw upstream body",
                            "path": r"C:\Users\name\AppData\Local\tool.exe",
                        }
                    }
                ),
                encoding="utf-8",
            )
            leaks = find_shareable_artifact_leaks(path)

        self.assertTrue(any("raw `body` field" in leak for leak in leaks), leaks)
        self.assertTrue(any("path-like value" in leak for leak in leaks), leaks)

    def test_allows_public_windows_path_title(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            path = Path(raw) / "target.json"
            path.write_text(
                json.dumps({"best_issue": {"title": r"Mapped drive Y:\ input rejected"}}),
                encoding="utf-8",
            )
            leaks = find_shareable_artifact_leaks(path)

        self.assertEqual(leaks, [])

    def test_allows_redacted_placeholder_paths_in_markdown(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            path = Path(raw) / "report.md"
            path.write_text(
                r'{"path": "%USERPROFILE%\\AppData\\Local\\tool.exe", "module": "%WORKSPACE%\\.tmp\\pkg"}',
                encoding="utf-8",
            )
            leaks = find_shareable_artifact_leaks(path)

        self.assertEqual(leaks, [])

    def test_rejects_private_path_adjacent_to_placeholder(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            path = Path(raw) / "report.md"
            path.write_text(r'{"mixed": "%WORKSPACE%\\C:\\Users\\alice\\secret.txt"}', encoding="utf-8")
            leaks = find_shareable_artifact_leaks(path)

        self.assertTrue(any("path-like text" in leak for leak in leaks), leaks)

    def test_rejects_missing_or_empty_artifact_path(self) -> None:
        with _temporary_directory(prefix="agent-windows-lab-test-") as raw:
            path = Path(raw) / "missing"
            leaks = find_shareable_artifact_leaks(path)

        self.assertTrue(any("no files found" in leak for leak in leaks), leaks)


if __name__ == "__main__":
    unittest.main()
