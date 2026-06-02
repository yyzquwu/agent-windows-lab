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
python .\scripts\run_agent_windows_lab.py --out .\artifacts\python-sdk-session --case mcp-python-sdk-session --redact --issue-target modelcontextprotocol-python-sdk
python .\scripts\run_agent_windows_lab.py --out .\artifacts\browser-use-mcp --case browser-use-mcp --redact --issue-target browser-use
python .\scripts\select_upstream_target.py --out .\artifacts\target-selection --comment-template
python .\scripts\verify_redacted_report.py .\artifacts\agent-windows-lab-report.json
python .\scripts\verify_shareable_artifact.py .\artifacts\target-selection
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
`browser`, `browser-use-mcp`, `environment`, `paths`, `subprocess`, `encoding`,
`mcp`, `mcp-python-sdk-session`, `shell`, and `stdio`; repeat `--case` to
combine them. Focused reports include the environment check automatically so the
output still has useful Windows/runtime context for upstream maintainers. The
`mcp-python-sdk-session` case is opt-in for an installed `mcp` Python SDK and
checks `ClientSession` lifecycle behavior. The `browser-use-mcp` case is opt-in
for external process launch; set
`AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND` to a JSON command array such as
`["uvx", "--from", "browser-use[cli]", "browser-use", "--mcp"]`.
When that command is set, the `browser-use-mcp` case also runs a focused
env-key probe for browser-use#4846: it compares direct MCP browser tool calls
with `OPENAI_API_KEY` unset and with a redacted dummy key present. Override the
dummy key with `AGENT_WINDOWS_LAB_BROWSER_USE_MCP_DUMMY_OPENAI_KEY` only when
you intentionally need to test a different key shape. For source checkouts,
set `AGENT_WINDOWS_LAB_BROWSER_USE_MCP_CWD` to the browser-use repo path. The
startup probe runs there. The env-key probe keeps that cwd for cwd-dependent
commands such as `uv run`, but auto-isolates `python -m browser_use.mcp`
commands with the checkout on `PYTHONPATH` so a local `.env` does not
contaminate the no-key baseline. Override isolation with
`AGENT_WINDOWS_LAB_BROWSER_USE_MCP_ISOLATE_CWD=true` or `false`.

Use `--issue-target` to generate a redacted upstream packet:

- `agent-windows-lab-report.json`
- `agent-windows-lab-report.md`
- `agent-windows-lab-issue.md`

Issue targets currently include `browser-use`, `modelcontextprotocol-python-sdk`,
`modelcontextprotocol-servers`, and `microsoft-playwright-mcp`.

Use `select_upstream_target.py` to scan active MCP/browser/agent repos, avoid
already-logged contributions in `docs/contribution-log.json`, rank the next
non-duplicate Windows issue or PR where a redacted packet would help, and write
a maintainer-ready comment template with `--comment-template`.

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
- 51 passing unit tests

The most useful findings were CRLF text-mode stdout, child Python stdout
defaulting to `cp1252`, and long nested path failure at 416 characters. See
[docs/upstream-notes.md](docs/upstream-notes.md).
