Tested this on Windows.

Environment:
- Windows 11
- Node `v24.9.0`
- pnpm `10.26.1`
- PR head `e683ec1aafe65131a40c62dbff2d4244ae9a019c`

What passed:

```text
pnpm --filter @modelcontextprotocol/express build
# passed, generated dist/index.cjs and dist/index.d.cts

pnpm --filter @modelcontextprotocol/express test
# 1 test file passed
# 17 tests passed

node --input-type=module -e "await import('@modelcontextprotocol/express')"
# passed
```

The CJS consumer check still fails:

```text
node -e "require('@modelcontextprotocol/express')"
# FAIL ERR_PACKAGE_PATH_NOT_EXPORTED
# No "exports" main defined in ...\node_modules\@modelcontextprotocol\server\package.json
```

The generated Express CJS bundle now loads, but it calls `require("@modelcontextprotocol/server")`. Since `@modelcontextprotocol/server` is still ESM-only and has no `require` export, this does not fully fix #1858 for CommonJS consumers yet. I think this either needs CJS support for the server-side packages too, or the docs should steer `@modelcontextprotocol/express` users to ESM/NodeNext only.

Posted at: https://github.com/modelcontextprotocol/typescript-sdk/pull/1911#issuecomment-4596989470
