from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_windows_lab.harness import available_cases, redact_report, report_to_markdown, run_checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Agent Windows Lab checks.")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts")
    parser.add_argument(
        "--case",
        action="append",
        choices=available_cases(),
        help="Run one focused repro case. Repeat for multiple cases. Defaults to all.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--redact", action="store_true", help="Redact local user and machine paths from the report.")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    report = run_checks(args.case)
    failed = [check for check in report["checks"] if check["status"] == "fail"]
    if args.redact:
        report = redact_report(report)

    json_path = args.out / "agent-windows-lab-report.json"
    md_path = args.out / "agent-windows-lab-report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(report_to_markdown(report), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Wrote {json_path}")
        print(f"Wrote {md_path}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
