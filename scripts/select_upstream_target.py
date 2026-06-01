from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from agent_windows_lab.harness import ISSUE_TARGETS


DEFAULT_CONTRIBUTION_LOG = ROOT / "docs" / "contribution-log.json"


@dataclass(frozen=True)
class Target:
    key: str
    repo: str
    cases: tuple[str, ...]
    search_terms: tuple[str, ...]
    focus: str


TARGETS = [
    Target(
        key="modelcontextprotocol-python-sdk",
        repo="modelcontextprotocol/python-sdk",
        cases=("mcp", "shell"),
        search_terms=("windows stdio", "windows CRLF", "windows subprocess"),
        focus=ISSUE_TARGETS["modelcontextprotocol-python-sdk"]["focus"],
    ),
    Target(
        key="modelcontextprotocol-servers",
        repo="modelcontextprotocol/servers",
        cases=("mcp", "paths", "shell"),
        search_terms=("windows path", "windows stdio", "powershell"),
        focus=ISSUE_TARGETS["modelcontextprotocol-servers"]["focus"],
    ),
    Target(
        key="microsoft-playwright-mcp",
        repo="microsoft/playwright-mcp",
        cases=("browser", "mcp", "shell"),
        search_terms=("windows browser", "windows profile", "powershell"),
        focus=ISSUE_TARGETS["microsoft-playwright-mcp"]["focus"],
    ),
    Target(
        key="browser-use",
        repo="browser-use/browser-use",
        cases=("browser", "paths", "shell"),
        search_terms=("windows playwright", "windows chrome", "windows path"),
        focus=ISSUE_TARGETS["browser-use"]["focus"],
    ),
    Target(
        key="modelcontextprotocol-typescript-sdk",
        repo="modelcontextprotocol/typescript-sdk",
        cases=("mcp", "subprocess", "shell"),
        search_terms=("windows stdio", "windows path", "powershell"),
        focus="TypeScript MCP stdio, subprocess, and Windows path behavior",
    ),
]


def _run_gh_json(args: list[str]) -> Any:
    completed = subprocess.run(
        ["gh", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    if not completed.stdout.strip():
        return []
    return json.loads(completed.stdout)


def _canonical_thread_url(url: str) -> str:
    base = url.split("#", 1)[0].split("?", 1)[0]
    return base.replace("/pull/", "/issues/")


def _load_log(path: Path) -> set[str]:
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {_canonical_thread_url(item["url"]) for item in payload.get("contributions", []) if "url" in item}


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return path.name


def _score_issue(issue: dict[str, Any], target: Target, contributed_urls: set[str]) -> int:
    if _canonical_thread_url(issue["url"]) in contributed_urls:
        return -100
    title = issue.get("title", "").lower()
    body = issue.get("body", "").lower()
    labels = {label["name"].lower() for label in issue.get("labels", [])}
    score = 0
    for token in ("windows", "powershell", "cmd", "stdio", "mcp", "playwright", "browser", "path"):
        if token in title:
            score += 3
        if token in body:
            score += 1
    for label in labels:
        if label in {"bug", "ready for work", "help wanted", "good first issue"}:
            score += 2
    if "fix proposed" in labels:
        score -= 2
    if "closed" in issue.get("state", "").lower():
        score -= 10
    if any(case in target.cases for case in ("mcp", "browser")):
        score += 1
    return score


def _candidate_summary(issue: dict[str, Any]) -> dict[str, Any]:
    author = issue.get("author") or {}
    return {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "url": issue.get("url"),
        "kind": issue.get("kind"),
        "state": issue.get("state"),
        "author": {"login": author.get("login")} if author.get("login") else None,
        "labels": [{"name": label.get("name")} for label in issue.get("labels", []) if label.get("name")],
        "createdAt": issue.get("createdAt"),
        "updatedAt": issue.get("updatedAt"),
    }


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for issue in issues:
        url = _canonical_thread_url(issue["url"])
        if url in seen:
            continue
        unique.append(issue)
        seen.add(url)
    return unique


def scan_targets(*, limit_per_query: int, log_path: Path) -> dict[str, Any]:
    contributed_urls = _load_log(log_path)
    results: list[dict[str, Any]] = []
    for target in TARGETS:
        issues: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for term in target.search_terms:
            query = f"{term} state:open"
            for kind in ("issue", "pr"):
                try:
                    found = _run_gh_json(
                        [
                            kind,
                            "list",
                            "--repo",
                            target.repo,
                            "--state",
                            "open",
                            "--search",
                            query,
                            "--limit",
                            str(limit_per_query),
                            "--json",
                            "number,title,url,labels,updatedAt,createdAt,author,body,state",
                        ]
                    )
                except RuntimeError as exc:
                    errors.append({"query": f"{kind}: {query}", "error": str(exc)})
                    continue
                issues.extend(dict(item, kind=kind) for item in found)
        fresh_issues = [
            issue for issue in _dedupe_issues(issues) if _canonical_thread_url(issue["url"]) not in contributed_urls
        ]
        ranked = sorted(
            fresh_issues,
            key=lambda issue: (_score_issue(issue, target, contributed_urls), issue.get("updatedAt", "")),
            reverse=True,
        )
        best = ranked[0] if ranked else None
        score = _score_issue(best, target, contributed_urls) if best else 0
        results.append(
            {
                "target": target.key,
                "repo": target.repo,
                "cases": list(target.cases),
                "focus": target.focus,
                "candidate_count": len(ranked),
                "best_score": score,
                "best_issue": _candidate_summary(best) if best else None,
                "errors": errors,
            }
        )
    results.sort(key=lambda item: (item["best_score"], item["candidate_count"]), reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "contribution_log": _display_path(log_path),
        "targets": results,
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Upstream Target Selection",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Ranked Targets",
        "",
    ]
    for item in report["targets"]:
        issue = item["best_issue"]
        lines.append(f"### {item['target']}")
        lines.append("")
        lines.append(f"- Repository: `{item['repo']}`")
        lines.append(f"- Cases: `{', '.join(item['cases'])}`")
        lines.append(f"- Candidate count: `{item['candidate_count']}`")
        lines.append(f"- Score: `{item['best_score']}`")
        lines.append(f"- Focus: {item['focus']}")
        if issue:
            labels = ", ".join(label["name"] for label in issue.get("labels", [])) or "none"
            kind = "PR" if issue.get("kind") == "pr" else "issue"
            lines.append(f"- Best issue/PR: [{issue['title']}]({issue['url']})")
            lines.append(f"- Type: `{kind}`")
            lines.append(f"- Labels: `{labels}`")
            lines.append(f"- Updated: `{issue.get('updatedAt', 'unknown')}`")
        else:
            lines.append("- Best issue/PR: none found")
        if item.get("errors"):
            lines.append("- Scan warnings:")
            for error in item["errors"]:
                lines.append(f"  - `{error['query']}`: {error['error']}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank upstream Windows OSS contribution targets.")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "target-selection")
    parser.add_argument("--limit-per-query", type=int, default=5)
    parser.add_argument("--log", type=Path, default=DEFAULT_CONTRIBUTION_LOG)
    parser.add_argument("--json", action="store_true", help="Print JSON report to stdout.")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    report = scan_targets(limit_per_query=args.limit_per_query, log_path=args.log)
    json_path = args.out / "upstream-target-selection.json"
    md_path = args.out / "upstream-target-selection.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(report_to_markdown(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Wrote {json_path}")
        print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
