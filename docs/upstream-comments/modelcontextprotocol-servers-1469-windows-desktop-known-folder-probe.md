Tested a focused Windows filesystem/Desktop path probe for this issue shape.

Environment:
- Windows 11
- Python `3.13.13`
- Node available for `fs.statSync` path checks

What the new packet checks:

```text
Path.home() / "Desktop"
[Environment]::GetFolderPath("Desktop")
Node fs.statSync(...) for each resolved Desktop candidate
MCP-style stdio LF framing
Windows path shapes with spaces and Unicode
Long nested path behavior
PowerShell/cmd launch context
```

Result on this machine:

```text
windows_desktop_known_folder_probe
# pass
# Path.home() / "Desktop" == [Environment]::GetFolderPath("Desktop")
# Node fs.statSync("%USERPROFILE%\\Desktop") returned ok=true, isDirectory=true

long_path_probe
# warn
# 416-character nested temp path failed with FileNotFoundError

stdio_newline_framing
# warn
# Python text-mode stdout emitted CRLF; binary stdout emitted LF

shell_launch_context
# warn
# PowerShell preserved cwd/env/Unicode; cmd failed in the Unicode temp cwd with "The network path was not found."
```

I did not reproduce the original `ENOENT` for Desktop on this machine. The useful part for this thread is that the packet now makes the likely fork explicit: if `C:\Users\<user>\Desktop` does not exist but `[Environment]::GetFolderPath("Desktop")` points somewhere like OneDrive Desktop, the filesystem server config should use the resolved known-folder path. If both paths exist and Node can `fs.statSync` the same configured path, then the remaining failure is more likely client config/version specific.

Commands:

```powershell
python .\scripts\run_agent_windows_lab.py --out .\artifacts\issue-packet-1469 --case filesystem --case mcp --case paths --case shell --issue-target modelcontextprotocol-servers --redact
python .\scripts\verify_redacted_report.py .\artifacts\issue-packet-1469\agent-windows-lab-report.json
python .\scripts\verify_shareable_artifact.py .\artifacts\issue-packet-1469
```
