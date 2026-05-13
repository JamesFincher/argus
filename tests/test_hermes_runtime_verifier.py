import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_hermes_runtime.py"
SPEC = importlib.util.spec_from_file_location("verify_hermes_runtime", SCRIPT_PATH)
verifier = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_mcp_config_snippet_points_hermes_at_argus_stdio(tmp_path):
    db_path = tmp_path / "timeline.db"

    snippet = verifier.mcp_config_snippet(db_path)

    assert "mcp_servers:" in snippet
    assert "argus-sensor:" in snippet
    assert 'command: "uv"' in snippet
    assert 'args: ["run", "argus-sensor-mcp"]' in snippet
    assert f'ARGUS_TIMELINE_DB_PATH: "{db_path}"' in snippet


def test_validate_entry_points_accepts_packaged_argus_metadata():
    verifier.validate_entry_points()


def test_find_hermes_and_package_origin_use_local_environment():
    assert verifier.find_hermes("python3")
    assert verifier.package_origin("json") is not None
    assert verifier.package_origin("argus_module_that_does_not_exist") is None


def test_validate_entry_points_reports_missing_console_scripts(monkeypatch):
    class FakeEntryPoints:
        def select(self, group):
            if group == "console_scripts":
                return []
            return [
                type(
                    "EntryPoint",
                    (),
                    {
                        "name": "argus",
                        "value": "argus_services.hermes_plugin:register",
                    },
                )()
            ]

    monkeypatch.setattr(verifier.metadata, "entry_points", lambda: FakeEntryPoints())

    with pytest.raises(RuntimeError, match="console script"):
        verifier.validate_entry_points()


def test_validate_entry_points_reports_missing_hermes_plugin(monkeypatch):
    class FakeEntryPoints:
        def select(self, group):
            if group == "console_scripts":
                return [
                    type("EntryPoint", (), {"name": name, "value": value})()
                    for name, value in verifier.EXPECTED_CONSOLE_SCRIPTS.items()
                ]
            return []

    monkeypatch.setattr(verifier.metadata, "entry_points", lambda: FakeEntryPoints())

    with pytest.raises(RuntimeError, match="Hermes plugin"):
        verifier.validate_entry_points()


def test_run_command_captures_exit_and_output():
    result = verifier.run_command(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"]
    )

    assert result.returncode == 3
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"


def test_call_stdio_mcp_returns_last_json_response(monkeypatch, tmp_path):
    monkeypatch.setattr(
        verifier,
        "run_command",
        lambda *args, **kwargs: verifier.CommandResult(
            ["uv"],
            0,
            '{"jsonrpc":"2.0","id":0}\n{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n',
            "",
        ),
    )

    response = verifier.call_stdio_mcp({"jsonrpc": "2.0", "id": 1}, timeline_db_path=tmp_path / "db")

    assert response == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}


def test_call_stdio_mcp_reports_process_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        verifier,
        "run_command",
        lambda *args, **kwargs: verifier.CommandResult(["uv"], 9, "", "boom"),
    )

    with pytest.raises(RuntimeError, match="Argus MCP stdio command failed"):
        verifier.call_stdio_mcp({"jsonrpc": "2.0"}, timeline_db_path=tmp_path / "db")


def test_call_stdio_mcp_reports_empty_response(monkeypatch, tmp_path):
    monkeypatch.setattr(
        verifier,
        "run_command",
        lambda *args, **kwargs: verifier.CommandResult(["uv"], 0, "\n", ""),
    )

    with pytest.raises(RuntimeError, match="no JSON-RPC response"):
        verifier.call_stdio_mcp({"jsonrpc": "2.0"}, timeline_db_path=tmp_path / "db")


def test_seed_timeline_event_returns_event_id(monkeypatch, tmp_path):
    monkeypatch.setattr(
        verifier,
        "run_command",
        lambda *args, **kwargs: verifier.CommandResult(["uv"], 0, "noise\nevent-1\n", ""),
    )

    assert verifier.seed_timeline_event(tmp_path / "timeline.sqlite3") == "event-1"


def test_seed_timeline_event_reports_failure_or_empty_output(monkeypatch, tmp_path):
    monkeypatch.setattr(
        verifier,
        "run_command",
        lambda *args, **kwargs: verifier.CommandResult(["uv"], 1, "", "seed failed"),
    )
    with pytest.raises(RuntimeError, match="Failed to seed"):
        verifier.seed_timeline_event(tmp_path / "timeline.sqlite3")

    monkeypatch.setattr(
        verifier,
        "run_command",
        lambda *args, **kwargs: verifier.CommandResult(["uv"], 0, "\n", ""),
    )
    with pytest.raises(RuntimeError, match="no event_id"):
        verifier.seed_timeline_event(tmp_path / "timeline.sqlite3")


def test_run_direct_mcp_smoke_lists_tools_and_blocks_raw(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(verifier, "seed_timeline_event", lambda _path: "event-1")

    def fake_call(request, *, timeline_db_path):
        calls.append(request)
        if request["method"] == "tools/list":
            return {
                "result": {
                    "tools": [
                        {"name": "sensor_get_recent_notes"},
                        {"name": "sensor_expand_event"},
                    ]
                }
            }
        return {"result": {"structuredContent": {"ok": False, "error": "approval required"}}}

    monkeypatch.setattr(verifier, "call_stdio_mcp", fake_call)

    tools, raw_blocked = verifier.run_direct_mcp_smoke(tmp_path / "timeline.sqlite3")

    assert tools == ["sensor_get_recent_notes", "sensor_expand_event"]
    assert raw_blocked is True
    assert calls[1]["params"]["arguments"]["event_id"] == "event-1"


def test_run_direct_mcp_smoke_reports_missing_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(verifier, "seed_timeline_event", lambda _path: "event-1")
    monkeypatch.setattr(
        verifier,
        "call_stdio_mcp",
        lambda *args, **kwargs: {"result": {"tools": [{"name": "sensor_get_recent_notes"}]}},
    )

    with pytest.raises(RuntimeError, match="tools missing"):
        verifier.run_direct_mcp_smoke(tmp_path / "timeline.sqlite3")


def test_hermes_version_returns_first_output_line(monkeypatch):
    monkeypatch.setattr(
        verifier,
        "run_command",
        lambda *args, **kwargs: verifier.CommandResult(["hermes"], 0, "\nGengar v1\n", "ignored"),
    )
    assert verifier.hermes_version("/bin/hermes") == "Gengar v1"

    monkeypatch.setattr(
        verifier,
        "run_command",
        lambda *args, **kwargs: verifier.CommandResult(["hermes"], 0, "", ""),
    )
    assert verifier.hermes_version("/bin/hermes") is None


def test_verify_returns_clear_blocker_when_hermes_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(verifier, "find_hermes", lambda _executable: None)
    monkeypatch.setattr(verifier, "validate_entry_points", lambda: None)
    monkeypatch.setattr(
        verifier,
        "run_direct_mcp_smoke",
        lambda _timeline_db_path: (["sensor_get_recent_notes", "sensor_expand_event"], True),
    )
    monkeypatch.setattr(
        verifier,
        "package_origin",
        lambda module_name: {"hermes": None, "hermes_cli": None, "gengar": None}[module_name],
    )

    result = verifier.verify(hermes_executable="missing-hermes", output_dir=tmp_path)

    assert result.ok is False
    assert result.hermes_path is None
    assert result.hermes_mcp_add is None
    assert result.hermes_mcp_test is None
    assert result.direct_raw_blocked is True
    assert result.config_path == tmp_path / "argus-hermes-mcp.yaml"
    assert result.config_path.exists()
    assert result.blockers == [
        "Hermes command not found on PATH; install Hermes/Gengar or pass --hermes PATH."
    ]


def test_verify_runs_live_hermes_mcp_when_command_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(verifier, "find_hermes", lambda _executable: "/bin/hermes")
    monkeypatch.setattr(verifier, "hermes_version", lambda _path: "Gengar v0.test")
    monkeypatch.setattr(verifier, "validate_entry_points", lambda: None)
    monkeypatch.setattr(
        verifier,
        "run_direct_mcp_smoke",
        lambda _timeline_db_path: (["sensor_get_recent_notes", "sensor_expand_event"], True),
    )
    monkeypatch.setattr(verifier, "package_origin", lambda _module_name: None)

    add_result = verifier.CommandResult(
        ["/bin/hermes", "mcp", "add"],
        0,
        "Connected. sensor_get_recent_notes discovered.",
        "",
    )
    test_result = verifier.CommandResult(
        ["/bin/hermes", "mcp", "test"],
        0,
        "Tools discovered: sensor_get_recent_notes",
        "",
    )
    monkeypatch.setattr(
        verifier,
        "run_live_hermes_mcp",
        lambda hermes_path, timeline_db_path: (add_result, test_result),
    )

    result = verifier.verify(output_dir=tmp_path)

    assert result.ok is True
    assert result.hermes_path == "/bin/hermes"
    assert result.hermes_version == "Gengar v0.test"
    assert result.hermes_mcp_add is add_result
    assert result.hermes_mcp_test is test_result
    assert result.blockers == []


def test_verify_collects_live_hermes_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(verifier, "find_hermes", lambda _executable: "/bin/hermes")
    monkeypatch.setattr(verifier, "hermes_version", lambda _path: "Gengar v0.test")
    monkeypatch.setattr(verifier, "validate_entry_points", lambda: None)
    monkeypatch.setattr(
        verifier,
        "run_direct_mcp_smoke",
        lambda _timeline_db_path: (["sensor_get_recent_notes", "sensor_expand_event"], True),
    )
    monkeypatch.setattr(verifier, "package_origin", lambda _module_name: None)

    add_result = verifier.CommandResult(["/bin/hermes", "mcp", "add"], 2, "failed", "nope")
    test_result = verifier.CommandResult(["/bin/hermes", "mcp", "test"], 3, "failed", "nope")
    monkeypatch.setattr(
        verifier,
        "run_live_hermes_mcp",
        lambda _hermes_path, _timeline_db_path: (add_result, test_result),
    )

    result = verifier.verify(output_dir=tmp_path)

    assert result.ok is False
    assert result.blockers == [
        "Hermes MCP add failed; see command output.",
        "Hermes MCP test failed; see command output.",
        "Hermes did not report Argus sensor_get_recent_notes discovery.",
    ]


def test_run_live_hermes_mcp_uses_isolated_home_and_argus_env(monkeypatch, tmp_path):
    calls = []

    def fake_run_command(command, *, cwd=verifier.ROOT, env=None, input_text=None, timeout=30):
        calls.append(
            {
                "command": command,
                "env": env,
                "input_text": input_text,
                "timeout": timeout,
            }
        )
        return verifier.CommandResult(command, 0, "sensor_get_recent_notes", "")

    monkeypatch.setattr(verifier, "run_command", fake_run_command)

    add_result, test_result = verifier.run_live_hermes_mcp("/bin/hermes", tmp_path / "db.sqlite3")

    assert add_result.returncode == 0
    assert test_result.returncode == 0
    add_call, test_call = calls
    assert add_call["command"] == [
        "/bin/hermes",
        "mcp",
        "add",
        "argus-sensor",
        "--command",
        "uv",
        "--env",
        f"ARGUS_TIMELINE_DB_PATH={tmp_path / 'db.sqlite3'}",
        "--args",
        "run",
        "argus-sensor-mcp",
    ]
    assert add_call["input_text"] == "Y\n"
    assert test_call["command"] == ["/bin/hermes", "mcp", "test", "argus-sensor"]
    assert add_call["env"]["GENGAR_HOME"] == test_call["env"]["GENGAR_HOME"]
    assert add_call["env"]["HERMES_HOME"] == add_call["env"]["GENGAR_HOME"]


def test_run_live_hermes_mcp_skips_test_after_add_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        verifier,
        "run_command",
        lambda command, **kwargs: verifier.CommandResult(command, 2, "", "add failed"),
    )

    add_result, test_result = verifier.run_live_hermes_mcp("/bin/hermes", tmp_path / "db.sqlite3")

    assert add_result.returncode == 2
    assert test_result.returncode == 99
    assert test_result.stderr == "skipped because hermes mcp add failed"


def test_print_result_reports_status_and_blockers(capsys, tmp_path):
    result = verifier.VerificationResult(
        ok=False,
        hermes_path=None,
        hermes_version=None,
        hermes_python_packages={"hermes": None, "gengar": "/tmp/gengar.py"},
        config_snippet="snippet",
        config_path=tmp_path / "argus-hermes-mcp.yaml",
        direct_mcp_tools=["sensor_get_recent_notes"],
        direct_raw_blocked=True,
        hermes_mcp_add=verifier.CommandResult(["hermes"], 1, "", ""),
        hermes_mcp_test=verifier.CommandResult(["hermes"], 2, "", ""),
        blockers=["blocked"],
    )

    verifier.print_result(result)

    output = capsys.readouterr().out
    assert "Hermes command: MISSING" in output
    assert "gengar: /tmp/gengar.py" in output
    assert "Hermes MCP add exit: 1" in output
    assert "  - blocked" in output


def test_parse_args_accepts_custom_hermes_and_output_dir(tmp_path):
    args = verifier.parse_args(["--hermes", "/bin/hermes", "--output-dir", str(tmp_path)])

    assert args.hermes == "/bin/hermes"
    assert args.output_dir == tmp_path


def test_main_returns_result_status(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        verifier,
        "verify",
        lambda **kwargs: verifier.VerificationResult(
            ok=True,
            hermes_path="/bin/hermes",
            hermes_version="v1",
            hermes_python_packages={},
            config_snippet="snippet",
            config_path=tmp_path / "config.yaml",
            direct_mcp_tools=[],
            direct_raw_blocked=True,
            hermes_mcp_add=None,
            hermes_mcp_test=None,
            blockers=[],
        ),
    )

    assert verifier.main(["--hermes", "/bin/hermes", "--output-dir", str(tmp_path)]) == 0
    assert "Argus Hermes runtime verification" in capsys.readouterr().out


def test_main_reports_prelaunch_failure(monkeypatch, capsys):
    def fail(**kwargs):
        raise RuntimeError("bad config")

    monkeypatch.setattr(verifier, "verify", fail)

    assert verifier.main([]) == 2
    assert "bad config" in capsys.readouterr().err
