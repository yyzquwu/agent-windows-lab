Tested this on Windows.

Environment:
- Windows 11
- Python `3.13.13`
- PR head `a176ccc07a5c48d439a909f1d9dcb9c71287dc81`

What passed:

```text
pytest tests/cli -q
# 27 passed

ruff check src/mcp/cli/cli.py tests/cli/test_utils.py
# passed
```

One thing still fails locally:

```text
pyright src/mcp/cli/cli.py tests/cli/test_utils.py
# tests/cli/test_utils.py:87:29 - "shutil" is not exported from module ".cli"
# tests/cli/test_utils.py:98:29 - "shutil" is not exported from module ".cli"
# tests/cli/test_utils.py:125:29 - "subprocess" is not exported from module ".cli"
# tests/cli/test_utils.py:157:29 - "subprocess" is not exported from module ".cli"
# tests/cli/test_utils.py:204:29 - "subprocess" is not exported from module ".cli"
# tests/cli/test_utils.py:228:29 - "subprocess" is not exported from module ".cli"
```

The fix itself looks right to me. The remaining issue seems test-side: the new tests monkeypatch `cli.shutil` and `cli.subprocess`, which trips `reportPrivateImportUsage`. Importing `shutil` and `subprocess` in the test module and monkeypatching those module objects directly should keep the same behavior without the private import warnings, because `cli.py` holds the same imported modules.

Posted at: https://github.com/modelcontextprotocol/python-sdk/pull/2524#issuecomment-4596910584
