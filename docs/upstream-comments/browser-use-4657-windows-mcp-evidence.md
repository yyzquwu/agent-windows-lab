I ran an independent Windows MCP startup baseline for this PR because the validation note says the patch still needs Windows-side behavioral confirmation.

Environment:

- Windows 11 (`Windows-11-10.0.26200-SP0`)
- Python 3.13.13
- `browser-use` launched through `python -m uv tool run --from browser-use[cli] browser-use --mcp`
- Cold `uv` path using a repo-local cache, with package install included in elapsed time

Result:

- The server answered a JSON-RPC `initialize` request successfully.
- Harness summary: `{"pass": 3}`
- MCP response: `protocolVersion=2025-06-18`, `serverInfo.name=browser-use`, `serverInfo.version=0.1.0`
- Elapsed time to first initialize response: `25.766s` with a `90s` timeout
- Browser-agent prerequisites passed, including a Unicode profile-path round trip.
- The redacted report verifier passed.
- No orphan `uv` / `browser-use` processes remained after the run.

Public harness / CI:

- Harness repo: https://github.com/yyzquwu/agent-windows-lab
- Relevant commit: https://github.com/yyzquwu/agent-windows-lab/commit/32a96b4dc15aaff8f8585a24d82a573427f8104c
- Windows CI: https://github.com/yyzquwu/agent-windows-lab/actions/runs/26778127761
- CI jobs green: Windows / Python 3.11 and Windows / Python 3.13

Local command used:

```powershell
$env:UV_CACHE_DIR = (Join-Path (Get-Location) 'artifacts\uv-cache')
$env:AGENT_WINDOWS_LAB_BROWSER_USE_MCP_COMMAND = '["python", "-m", "uv", "tool", "run", "--from", "browser-use[cli]", "browser-use", "--mcp"]'
$env:AGENT_WINDOWS_LAB_BROWSER_USE_MCP_TIMEOUT_S = '90'
python .\scripts\run_agent_windows_lab.py --out .\artifacts\browser-use-mcp-live --case browser-use-mcp --redact --issue-target browser-use --json
python .\scripts\verify_redacted_report.py .\artifacts\browser-use-mcp-live\agent-windows-lab-report.json
```

This does not prove every Windows startup-timeout path is fixed, but it gives maintainers a repeatable Windows baseline: with the current package path above, `browser-use --mcp` can cold-start and answer MCP `initialize` on Windows within 90 seconds, and the evidence packet is redacted/shareable.
