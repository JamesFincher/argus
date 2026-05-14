# Hermes Runtime Verification

Run the live Argus/Hermes verification from the repository root:

```sh
uv run python scripts/verify_hermes_runtime.py
```

For the full operator setup sequence, use
[`docs/hermes-setup.md`](hermes-setup.md). This verifier is a runtime smoke
test for the setup path, not a substitute for enabling the plugin in the exact
Hermes Python environment used by the operator.

The verifier checks that:

- a local `hermes` command is available;
- Argus console scripts plus `hermes_agent.plugins:argus` and legacy
  `hermes.plugins:argus` entry points are packaged;
- `uv run argus-sensor-mcp` exposes the expected MCP tools;
- full raw event expansion is blocked without approval;
- Hermes can add and test the Argus MCP server from an isolated temporary
  Hermes home.

The generated MCP config snippet is written to
`docs/generated/argus-hermes-mcp.yaml`. The snippet contains the local absolute
SQLite path for the current checkout, so both the snippet and runtime SQLite
state produced by verification are ignored.

If Hermes is not installed, the verifier exits nonzero after writing the config
snippet and reports the missing command as a blocker instead of claiming live
runtime success.

If the report says Hermes Python packages are `MISSING` but `hermes mcp add`
and `hermes mcp test` pass, the MCP integration is still verified. That package
line only reports what this Python process can import; plugin hook enablement
must be confirmed separately with `hermes plugins list` showing `argus`.
