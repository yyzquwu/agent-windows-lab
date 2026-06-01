from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
import sys

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from select_upstream_target import Target, report_to_markdown, scan_targets


class SelectUpstreamTargetTests(unittest.TestCase):
    def test_scan_targets_ranks_non_duplicate_windows_issue(self) -> None:
        issue = {
            "number": 1,
            "title": "Windows Playwright profile path fails in MCP launch",
            "url": "https://github.com/microsoft/playwright-mcp/issues/1",
            "labels": [{"name": "bug"}, {"name": "help wanted"}],
            "updatedAt": "2026-06-01T00:00:00Z",
            "createdAt": "2026-06-01T00:00:00Z",
            "author": {"login": "tester"},
            "body": "PowerShell launch fails with a Windows path",
            "state": "OPEN",
        }

        def fake_run_gh_json(args: list[str]) -> list[dict[str, object]]:
            repo = args[args.index("--repo") + 1]
            if args[0] == "issue" and repo == "microsoft/playwright-mcp":
                return [issue]
            return []

        with tempfile.TemporaryDirectory() as raw:
            log = Path(raw) / "contribution-log.json"
            log.write_text(json.dumps({"contributions": []}), encoding="utf-8")
            with patch("select_upstream_target._run_gh_json", side_effect=fake_run_gh_json):
                report = scan_targets(limit_per_query=2, log_path=log)

        self.assertEqual(report["targets"][0]["target"], "microsoft-playwright-mcp")
        self.assertEqual(report["targets"][0]["best_issue"]["url"], issue["url"])
        self.assertGreater(report["targets"][0]["best_score"], 0)
        self.assertEqual(report["targets"][0]["best_issue"]["kind"], "issue")
        self.assertNotIn("body", report["targets"][0]["best_issue"])
        self.assertFalse(Path(report["contribution_log"]).is_absolute())

    def test_scan_targets_can_rank_pull_request_candidate(self) -> None:
        pull_request = {
            "number": 10,
            "title": "Fix Windows MCP stdio path handling",
            "url": "https://github.com/modelcontextprotocol/python-sdk/pull/10",
            "labels": [{"name": "bug"}],
            "updatedAt": "2026-06-01T00:00:00Z",
            "createdAt": "2026-06-01T00:00:00Z",
            "author": {"login": "tester"},
            "body": "PowerShell and Windows path regression test",
            "state": "OPEN",
        }

        def fake_run_gh_json(args: list[str]) -> list[dict[str, object]]:
            if args[0] == "pr":
                return [pull_request]
            return []

        with tempfile.TemporaryDirectory() as raw:
            log = Path(raw) / "contribution-log.json"
            log.write_text(json.dumps({"contributions": []}), encoding="utf-8")
            with patch("select_upstream_target.TARGETS", [Target("x", "owner/repo", ("mcp",), ("windows",), "focus")]):
                with patch("select_upstream_target._run_gh_json", side_effect=fake_run_gh_json):
                    report = scan_targets(limit_per_query=1, log_path=log)

        self.assertEqual(report["targets"][0]["best_issue"]["url"], pull_request["url"])
        self.assertEqual(report["targets"][0]["best_issue"]["kind"], "pr")

    def test_scan_targets_filters_logged_contributions(self) -> None:
        issue = {
            "number": 2743,
            "title": "Windows stdio CRLF",
            "url": "https://github.com/modelcontextprotocol/python-sdk/issues/2743",
            "labels": [{"name": "bug"}],
            "updatedAt": "2026-06-01T00:00:00Z",
            "createdAt": "2026-06-01T00:00:00Z",
            "author": {"login": "tester"},
            "body": "Windows stdio",
            "state": "OPEN",
        }

        with tempfile.TemporaryDirectory() as raw:
            log = Path(raw) / "contribution-log.json"
            log.write_text(
                json.dumps(
                    {
                        "contributions": [
                            {
                                "url": "https://github.com/modelcontextprotocol/python-sdk/pull/2743"
                                "#issuecomment-4589858172"
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with patch("select_upstream_target.TARGETS", [Target("x", "owner/repo", ("mcp",), ("windows",), "focus")]):
                with patch("select_upstream_target._run_gh_json", return_value=[issue]):
                    report = scan_targets(limit_per_query=1, log_path=log)

        self.assertEqual(report["targets"][0]["candidate_count"], 0)
        self.assertEqual(report["targets"][0]["best_score"], 0)
        self.assertIsNone(report["targets"][0]["best_issue"])

    def test_scan_targets_keeps_going_when_query_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            log = Path(raw) / "contribution-log.json"
            log.write_text(json.dumps({"contributions": []}), encoding="utf-8")
            with patch("select_upstream_target.TARGETS", [Target("x", "owner/repo", ("mcp",), ("windows",), "focus")]):
                with patch("select_upstream_target._run_gh_json", side_effect=RuntimeError("denied")):
                    report = scan_targets(limit_per_query=1, log_path=log)

        self.assertEqual(report["targets"][0]["candidate_count"], 0)
        self.assertEqual(report["targets"][0]["errors"][0]["error"], "denied")

    def test_markdown_report_links_best_issue(self) -> None:
        report = {
            "generated_at": "2026-06-01T00:00:00+00:00",
            "targets": [
                {
                    "target": "microsoft-playwright-mcp",
                    "repo": "microsoft/playwright-mcp",
                    "cases": ["browser", "mcp"],
                    "focus": "focus",
                    "candidate_count": 1,
                    "best_score": 7,
                    "errors": [],
                    "best_issue": {
                        "title": "Windows issue",
                        "url": "https://github.com/microsoft/playwright-mcp/issues/1",
                        "labels": [{"name": "bug"}],
                        "updatedAt": "2026-06-01T00:00:00Z",
                    },
                }
            ],
        }
        markdown = report_to_markdown(report)
        self.assertIn("microsoft/playwright-mcp", markdown)
        self.assertIn("Best issue/PR: [Windows issue](https://github.com/microsoft/playwright-mcp/issues/1)", markdown)


if __name__ == "__main__":
    unittest.main()
