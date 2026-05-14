#!/usr/bin/env python3
"""Verify Argus MCP/plugin wiring against a local Hermes runtime."""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARGUS_MCP_SERVER_NAME = "argus-sensor"
ARGUS_MCP_COMMAND = "uv"
ARGUS_MCP_ARGS = ["run", "argus-sensor-mcp"]
EXPECTED_CONSOLE_SCRIPTS = {
    "argus-mcp-stdio": "argus_services.mcp_stdio:main",
    "argus-sensor-mcp": "argus_services.mcp_stdio:main",
    "hermes-sensor-mcp": "argus_services.mcp_stdio:main",
}
EXPECTED_PLUGIN_GROUPS = ("hermes_agent.plugins", "hermes.plugins")
EXPECTED_PLUGIN_NAME = "argus"
EXPECTED_PLUGIN_VALUE = "argus_services.hermes_plugin:register"


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    hermes_path: str | None
    hermes_version: str | None
    hermes_python_packages: dict[str, str | None]
    config_snippet: str
    config_path: Path
    direct_mcp_tools: list[str]
    direct_raw_blocked: bool
    hermes_mcp_add: CommandResult | None
    hermes_mcp_test: CommandResult | None
    blockers: list[str]


def find_hermes(executable: str = "hermes") -> str | None:
    return shutil.which(executable)


def package_origin(module_name: str) -> str | None:
    code = (
        "import importlib.util, sys; "
        f"spec=importlib.util.find_spec({module_name!r}); "
        "print(spec.origin if spec else '')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    origin = result.stdout.strip()
    return origin or None


def validate_entry_points() -> None:
    entry_points = metadata.entry_points()
    scripts = {
        entry_point.name: entry_point.value
        for entry_point in entry_points.select(group="console_scripts")
    }
    missing_scripts = {
        name: value
        for name, value in EXPECTED_CONSOLE_SCRIPTS.items()
        if scripts.get(name) != value
    }
    if missing_scripts:
        raise RuntimeError(f"Argus console script entry points are missing: {missing_scripts}")

    missing_plugin_groups: list[str] = []
    for group in EXPECTED_PLUGIN_GROUPS:
        plugins = {
            entry_point.name: entry_point.value
            for entry_point in entry_points.select(group=group)
        }
        if plugins.get(EXPECTED_PLUGIN_NAME) != EXPECTED_PLUGIN_VALUE:
            missing_plugin_groups.append(group)
    if missing_plugin_groups:
        expected = ", ".join(
            f"{group}:{EXPECTED_PLUGIN_NAME}={EXPECTED_PLUGIN_VALUE}"
            for group in missing_plugin_groups
        )
        raise RuntimeError(f"Argus Hermes plugin entry points are missing: {expected}")


def mcp_config_snippet(timeline_db_path: Path) -> str:
    return (
        "mcp_servers:\n"
        f"  {ARGUS_MCP_SERVER_NAME}:\n"
        f'    command: "{ARGUS_MCP_COMMAND}"\n'
        '    args: ["run", "argus-sensor-mcp"]\n'
        "    env:\n"
        f'      ARGUS_TIMELINE_DB_PATH: "{timeline_db_path}"\n'
    )


def write_mcp_config_snippet(output_dir: Path, timeline_db_path: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "argus-hermes-mcp.yaml"
    config_path.write_text(mcp_config_snippet(timeline_db_path), encoding="utf-8")
    return config_path


def run_command(
    command: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: int = 30,
) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def call_stdio_mcp(request: dict[str, Any], *, timeline_db_path: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["ARGUS_TIMELINE_DB_PATH"] = str(timeline_db_path)
    payload = json.dumps(request, separators=(",", ":")) + "\n"
    result = run_command(
        [ARGUS_MCP_COMMAND, *ARGUS_MCP_ARGS],
        env=env,
        input_text=payload,
        timeout=20,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Argus MCP stdio command failed: "
            f"exit={result.returncode} stderr={result.stderr.strip()}"
        )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Argus MCP stdio command returned no JSON-RPC response")
    return json.loads(lines[-1])


def seed_timeline_event(timeline_db_path: Path) -> str:
    code = """
from argus_services.events import make_event
from argus_services.sqlite_store import SQLiteTimelineStore

store = SQLiteTimelineStore(r'''%s''')
try:
    event = store.add(
        make_event(
            "perception.note",
            {"summary": "Hermes verification note for alex@example.com"},
        )
    )
    print(event.event_id)
finally:
    store.close()
""" % str(timeline_db_path)
    result = run_command(["uv", "run", "python", "-c", code], timeout=20)
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to seed Argus timeline event: "
            f"exit={result.returncode} stderr={result.stderr.strip()}"
        )
    output_lines = result.stdout.strip().splitlines()
    if not output_lines:
        raise RuntimeError("Failed to seed Argus timeline event: no event_id returned")
    event_id = output_lines[-1].strip()
    return event_id


def run_direct_mcp_smoke(timeline_db_path: Path) -> tuple[list[str], bool]:
    event_id = seed_timeline_event(timeline_db_path)
    tools_response = call_stdio_mcp(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        timeline_db_path=timeline_db_path,
    )
    tools = [
        tool["name"]
        for tool in tools_response.get("result", {}).get("tools", [])
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    ]
    if "sensor_get_recent_notes" not in tools or "sensor_expand_event" not in tools:
        raise RuntimeError(f"Argus MCP tools missing expected sensor tools: {tools}")

    raw_response = call_stdio_mcp(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "sensor_expand_event",
                "arguments": {"event_id": event_id, "raw_mode": "full", "actor": "hermes"},
            },
        },
        timeline_db_path=timeline_db_path,
    )
    structured = raw_response.get("result", {}).get("structuredContent", {})
    raw_blocked = structured.get("ok") is False and "approval" in structured.get("error", "")
    return tools, raw_blocked


def hermes_version(hermes_path: str) -> str | None:
    result = run_command([hermes_path, "version"], timeout=20)
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    for line in output.splitlines():
        if line.strip():
            return line.strip()
    return None


def run_live_hermes_mcp(hermes_path: str, timeline_db_path: Path) -> tuple[CommandResult, CommandResult]:
    with tempfile.TemporaryDirectory(prefix="argus-hermes-home-") as home:
        env = os.environ.copy()
        env["GENGAR_HOME"] = home
        env["HERMES_HOME"] = home
        add_result = run_command(
            [
                hermes_path,
                "mcp",
                "add",
                ARGUS_MCP_SERVER_NAME,
                "--command",
                ARGUS_MCP_COMMAND,
                "--env",
                f"ARGUS_TIMELINE_DB_PATH={timeline_db_path}",
                "--args",
                *ARGUS_MCP_ARGS,
            ],
            env=env,
            input_text="Y\n",
            timeout=45,
        )
        if add_result.returncode != 0:
            return add_result, CommandResult(
                [hermes_path, "mcp", "test", ARGUS_MCP_SERVER_NAME],
                99,
                "",
                "skipped because hermes mcp add failed",
            )
        test_result = run_command(
            [hermes_path, "mcp", "test", ARGUS_MCP_SERVER_NAME],
            env=env,
            timeout=45,
        )
        return add_result, test_result


def verify(*, hermes_executable: str = "hermes", output_dir: Path | None = None) -> VerificationResult:
    output_dir = output_dir or ROOT / "docs" / "generated"
    timeline_db_path = output_dir / "argus-hermes-verification.sqlite3"
    blockers: list[str] = []
    config_path = write_mcp_config_snippet(output_dir, timeline_db_path)

    validate_entry_points()
    direct_tools, raw_blocked = run_direct_mcp_smoke(timeline_db_path)

    hermes_path = find_hermes(hermes_executable)
    hermes_packages = {
        "hermes": package_origin("hermes"),
        "hermes_cli": package_origin("hermes_cli"),
        "gengar": package_origin("gengar"),
    }
    if hermes_path is None:
        blockers.append(
            "Hermes command not found on PATH; install Hermes/Gengar or pass --hermes PATH."
        )
        return VerificationResult(
            ok=False,
            hermes_path=None,
            hermes_version=None,
            hermes_python_packages=hermes_packages,
            config_snippet=mcp_config_snippet(timeline_db_path),
            config_path=config_path,
            direct_mcp_tools=direct_tools,
            direct_raw_blocked=raw_blocked,
            hermes_mcp_add=None,
            hermes_mcp_test=None,
            blockers=blockers,
        )

    version = hermes_version(hermes_path)
    add_result, test_result = run_live_hermes_mcp(hermes_path, timeline_db_path)
    if add_result.returncode != 0:
        blockers.append("Hermes MCP add failed; see command output.")
    if test_result.returncode != 0:
        blockers.append("Hermes MCP test failed; see command output.")
    if "sensor_get_recent_notes" not in add_result.stdout + test_result.stdout:
        blockers.append("Hermes did not report Argus sensor_get_recent_notes discovery.")

    return VerificationResult(
        ok=not blockers,
        hermes_path=hermes_path,
        hermes_version=version,
        hermes_python_packages=hermes_packages,
        config_snippet=mcp_config_snippet(timeline_db_path),
        config_path=config_path,
        direct_mcp_tools=direct_tools,
        direct_raw_blocked=raw_blocked,
        hermes_mcp_add=add_result,
        hermes_mcp_test=test_result,
        blockers=blockers,
    )


def print_result(result: VerificationResult) -> None:
    print("Argus Hermes runtime verification")
    print(f"Hermes command: {result.hermes_path or 'MISSING'}")
    print(f"Hermes version: {result.hermes_version or 'unavailable'}")
    print("Hermes Python packages visible to this verifier:")
    for name, origin in result.hermes_python_packages.items():
        print(f"  {name}: {origin or 'MISSING'}")
    print(f"Config snippet: {result.config_path}")
    print(f"Direct Argus MCP tools: {', '.join(result.direct_mcp_tools)}")
    print(f"Direct raw expansion without approval blocked: {result.direct_raw_blocked}")
    if result.hermes_mcp_add is not None:
        print(f"Hermes MCP add exit: {result.hermes_mcp_add.returncode}")
    if result.hermes_mcp_test is not None:
        print(f"Hermes MCP test exit: {result.hermes_mcp_test.returncode}")
    if result.blockers:
        print("Blockers:")
        for blocker in result.blockers:
            print(f"  - {blocker}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hermes",
        default="hermes",
        help="Hermes/Gengar executable to verify. Defaults to PATH lookup for hermes.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "docs" / "generated",
        help="Directory for the generated Argus MCP config snippet and verification DB.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = verify(hermes_executable=args.hermes, output_dir=args.output_dir)
    except Exception as exc:
        print(f"Argus Hermes runtime verification failed before Hermes launch: {exc}", file=sys.stderr)
        return 2
    print_result(result)
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
