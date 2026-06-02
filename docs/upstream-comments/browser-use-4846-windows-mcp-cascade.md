I tested this on Windows against current `browser-use` main (`4931a7e`).

Raw MCP stdio calls show the same downstream state/screenshot cascade after navigation fails:

- `initialize` succeeds
- `browser_navigate("https://example.com/")` returns `Error: [WinError 5] Access is denied`
- `browser_list_tabs` returns `[]`
- `browser_get_state` returns `Expected at least one handler to return a non-None result`
- `browser_screenshot` returns `Root CDP client not initialized`

I ran the same sequence with provider keys absent and with a redacted dummy `OPENAI_API_KEY`. In this Windows setup both runs hit the same navigation failure, so I can confirm the Windows MCP cascade but not the env-key gating from the macOS repro above.

Evidence:
- Windows 11, Python 3.13.13
- Browser Use source checkout: `4931a7e`
- Agent Windows Lab case: `browser-use-mcp`
- Redaction/shareable checks: passed
- Harness commit: https://github.com/yyzquwu/agent-windows-lab/commit/dbf9a50f1e235cd0510dd999022aeaa972e39b8a
- Windows proof run: https://github.com/yyzquwu/agent-windows-lab/actions/runs/26798784238
