# Upstream Notes From First Local Run

Run date: 2026-05-31.

Local result:

- Harness exit code: `0`
- Unit tests: `python -m unittest discover -s tests -v` passed, 7 tests
- Report summary: 5 pass, 3 warn

## Evidence Worth Using Upstream

### 1. MCP-style stdio framing can emit CRLF on Windows

Observed:

- Python text-mode stdout emitted bytes ending in `0d0a`
- Python binary stdout emitted bytes ending in `0a`

Why it matters:

MCP and similar protocols often use newline-delimited JSON over stdio. If an
implementation or parser assumes byte-exact LF framing, Windows text-mode IO can
be a real interop risk.

Best upstream target:

- [`modelcontextprotocol/python-sdk`](https://github.com/modelcontextprotocol/python-sdk)

Possible contribution:

- Add or improve a Windows regression test around stdio line endings.
- Prefer binary writes or explicit newline handling where strict framing matters.

### 2. Python child process stdout can default to `cp1252`

Observed:

- Parent PowerShell reported UTF-8 output encoding.
- Child Python process reported `stdout_encoding=cp1252`.
- Printing `chr(0x96ea)` failed with `UnicodeEncodeError`.

Why it matters:

Agents frequently launch local Python tools and MCP servers, then ingest stdout
into chat logs, tool results, or protocol frames. A child process can fail even
when the parent shell appears UTF-8-ready.

Best upstream targets:

- [`OpenHands/OpenHands`](https://github.com/OpenHands/OpenHands)
- [`cline/cline`](https://github.com/cline/cline)
- [`modelcontextprotocol/python-sdk`](https://github.com/modelcontextprotocol/python-sdk)

Possible contribution:

- Add repro docs recommending `PYTHONUTF8=1` or explicit `encoding="utf-8"` for
  subprocess environments.
- Add test cases where launched tools emit non-ASCII output.

### 3. Long nested paths failed at 416 characters

Observed:

- Creating a nested path of length 416 failed with `FileNotFoundError(2, 'The system cannot find the path specified')`.

Why it matters:

Agent workspaces and package caches can easily create deep paths, especially
inside temp directories, OneDrive, virtual environments, node_modules, or cloned
monorepos.

Best upstream targets:

- Coding agents that create temp workspaces or sandboxes
- MCP tools that create caches or downloaded artifacts

Possible contribution:

- Add workspace path-length probes to Windows CI or issue templates.
- Prefer shorter temp roots for generated workspaces on Windows.

## First Issue Comment Template

```markdown
I reproduced a related Windows edge case with a small local harness.

Environment:
- Windows: Windows-11-10.0.26200-SP0
- Python: 3.13.13 from Microsoft Store path
- PowerShell: 5.1.26100.8457
- cmd code page: 437

Observed:
- Python text-mode stdout emitted CRLF (`0d0a`) for newline-delimited JSON.
- Python binary stdout emitted LF (`0a`).
- A child Python process defaulted to `stdout_encoding=cp1252` and failed to print a non-ASCII character.
- Long nested path creation failed at path length 416.

Repro artifact:
Agent Windows Lab harness: `scripts/run_agent_windows_lab.py`

Happy to turn this into a focused regression test if maintainers agree on the desired behavior.
```
