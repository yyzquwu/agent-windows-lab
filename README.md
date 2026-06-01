# Agent Windows Lab

[![Windows proof](https://github.com/yyzquwu/agent-windows-lab/actions/workflows/windows-proof.yml/badge.svg)](https://github.com/yyzquwu/agent-windows-lab/actions/workflows/windows-proof.yml)

Agent Windows Lab is a small research and repro harness for the Windows edge
cases that matter in agentic developer tools: MCP stdio framing, subprocess
quoting, shell encoding, long paths, spaces, Unicode, and local runtime bridges.

The goal is to turn "Windows feels under-loved" into evidence that can become
high-quality upstream issues or pull requests.

## Run

```powershell
python .\scripts\run_agent_windows_lab.py --out .\artifacts
python .\scripts\run_agent_windows_lab.py --out .\artifacts --redact
python .\scripts\run_agent_windows_lab.py --out .\artifacts --case stdio --redact --json
python .\scripts\run_agent_windows_lab.py --out .\artifacts --case subprocess --case encoding --redact
python .\scripts\run_agent_windows_lab.py --out .\artifacts\issue-packet --case mcp --case browser --case shell --issue-target modelcontextprotocol-python-sdk
python .\scripts\verify_redacted_report.py .\artifacts\agent-windows-lab-report.json
python -m unittest discover -s tests
```

The harness writes:

- `artifacts/agent-windows-lab-report.json`
- `artifacts/agent-windows-lab-report.md`

Generated artifacts are ignored by Git because they can contain local machine
paths. Use `--redact` before sharing report output as upstream evidence.
The verifier script fails if redacted output still contains common absolute
Windows, UNC, or POSIX tool paths.

Use `--case` for focused, issue-ready repro reports. Available cases are
`browser`, `environment`, `paths`, `subprocess`, `encoding`, `mcp`, `shell`,
and `stdio`; repeat `--case` to combine them. Focused reports include the
environment check automatically so the output still has useful Windows/runtime
context for upstream maintainers.

Use `--issue-target` to generate a redacted upstream packet:

- `agent-windows-lab-report.json`
- `agent-windows-lab-report.md`
- `agent-windows-lab-issue.md`

Issue targets currently include `modelcontextprotocol-python-sdk`,
`modelcontextprotocol-servers`, and `microsoft-playwright-mcp`.

## Current Focus

The first contribution thesis is:

> Agent frameworks are increasingly OS-touching software. On Windows, the most
> valuable contribution lane is validating and fixing process, stdio, path,
> encoding, and browser/computer-use bridge behavior.

See [docs/research-matrix.md](docs/research-matrix.md) for target repos and
initial issue clusters.

## First Local Result

On 2026-05-31, the harness completed end-to-end on Windows 11 with:

- 5 passing checks
- 3 warning/evidence checks
- 21 passing unit tests

The most useful findings were CRLF text-mode stdout, child Python stdout
defaulting to `cp1252`, and long nested path failure at 416 characters. See
[docs/upstream-notes.md](docs/upstream-notes.md).
