Tested this against current `modelcontextprotocol/servers` main on Windows.

Environment:
- Windows 11
- Node `v24.9.0`
- Filesystem server commit `64b1cb0`

What passed:

```text
npm run build --workspace @modelcontextprotocol/server-filesystem
# passed
```

I also ran two probes against a temp allowed directory:

```text
validatePath + writeFileContent + readFileContent
# absolute new file: exists=true, readBack="absolute ok"
# relative new file: exists=true, readBack="relative ok"

MCP stdio client -> write_file -> read_file
# absolute new file: exists=true, readText="tool absolute ok"
# relative new file: exists=true, readText="tool relative ok"
```

I could not reproduce the silent-success/missing-file behavior on current main with either absolute or relative paths. The tool-level probe returned the normal success text and the files were visible via `fs.stat()` before `read_file`.

My read: this may be specific to the Claude Desktop bundled filesystem server version, the exact configured allowed directory, or the exact path shape being passed to `write_file`. The most useful next detail would be the full filesystem server command/args from Claude Desktop plus one exact redacted `write_file` argument that returns success but leaves no file behind.

Posted at: https://github.com/modelcontextprotocol/servers/issues/4138#issuecomment-4597082651
