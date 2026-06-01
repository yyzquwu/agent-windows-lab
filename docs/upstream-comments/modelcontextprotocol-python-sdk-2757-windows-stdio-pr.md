## Summary

- Disable Windows CRLF translation in `stdio_server()` by setting `newline=""` on the default stdio wrappers.
- Add a regression test for the default stdout path so JSON-RPC frames stay LF-only.

Fixes #2433.

## Verification

Windows 11, Python 3.13.13:

```text
tests/server/test_stdio.py::test_stdio_server PASSED
tests/server/test_stdio.py::test_stdio_server_uses_lf_newlines_with_default_stdout PASSED
tests/server/test_stdio.py::test_stdio_server_invalid_utf8 PASSED
3 passed in 1.48s

b'{"jsonrpc":"2.0","id":3,"method":"ping"}\n'
```

Codex review passed before commit.

Posted at: https://github.com/modelcontextprotocol/python-sdk/pull/2757
