Tested this on Windows.

Environment:
- Windows 11
- Node `v24.9.0`
- npm `11.6.0`
- PR head `de13fd24781943c8414d3330b9c0dba78b87307f`

Results:

```text
npm run build --workspace @modelcontextprotocol/server-filesystem
# passed

npm test --workspace @modelcontextprotocol/server-filesystem -- --run
# 7 test files passed
# 159 tests passed
```

The Windows-only UNC cases in `path-validation.test.ts` and `lib.test.ts` ran as part of the filesystem suite. This looks like the more complete fix for #3756 compared with #3921 because it covers `validatePath` and startup allowed-directory normalization too.

Posted at: https://github.com/modelcontextprotocol/servers/pull/3981#issuecomment-4596743655
