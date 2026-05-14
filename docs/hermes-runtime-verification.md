# Hermes Runtime Verification

Run the live Argus/Hermes verification from the repository root:

```sh
uv run python scripts/verify_hermes_runtime.py
```

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
