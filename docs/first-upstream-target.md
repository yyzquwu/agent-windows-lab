# First Upstream Target

## Recommended Target

`modelcontextprotocol/python-sdk`

URL: https://github.com/modelcontextprotocol/python-sdk

## Why This Target

The MCP Python SDK is an official implementation of Model Context Protocol
servers and clients, including stdio server examples. Windows stdio behavior is
one of the most transferable agentic-tooling seams: it affects local MCP
servers, desktop clients, coding agents, and CI repros.

Agent Windows Lab now produces a redacted issue packet for this lane:

```powershell
python .\scripts\run_agent_windows_lab.py --out .\artifacts\issue-packet --case mcp --case shell --issue-target modelcontextprotocol-python-sdk
python .\scripts\verify_redacted_report.py .\artifacts\issue-packet\agent-windows-lab-report.json
```

## Prepared Issue Angle

Title:

```text
Add Windows stdio framing regression coverage for MCP server/client examples
```

Contribution shape:

- Open an issue first with `agent-windows-lab-issue.md` as the body
- Attach or paste the redacted check summary
- Offer a follow-up PR that adds a Windows-focused stdio framing regression test
- Keep the PR small: documentation or test coverage before behavior changes

## Evidence To Use

The `mcp` case captures two important signals:

- `stdio_newline_framing`: text-mode stdout can emit CRLF on Windows
- `mcp_stdio_jsonrpc_probe`: binary stdio can round-trip JSON-RPC with LF framing

The `shell` case adds launch evidence for PowerShell and cmd:

- shell-launched child process cwd
- environment propagation
- Unicode argument preservation

## Not Posted Yet

This repo prepares the upstream packet. It does not automatically open an
upstream issue, because final issue wording should be checked against the latest
target repository state immediately before posting.
