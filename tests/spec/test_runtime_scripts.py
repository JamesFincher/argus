from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_event_gateway_runner_sets_services_pythonpath():
    run_script = read("scripts/dev/run_event_gateway.sh")
    start_script = read("scripts/dev/start_event_gateway.sh")

    assert "PYTHONPATH" in run_script
    assert "$PWD/services" in run_script
    assert 'PYTHONPATH="$PWD/services${PYTHONPATH:+:$PYTHONPATH}"' in start_script
    assert "ARGUS_EVENT_GATEWAY_HOST" in start_script
    assert "ARGUS_EVENT_GATEWAY_PORT" in start_script
    assert "http://${HOST}:${PORT}/health" in start_script


def test_macos_app_packaging_script_creates_bundle_structure():
    script = read("scripts/dev/package_macos_app.sh")

    assert 'APP_NAME="Argus Sensor"' in script
    assert '.app"' in script
    assert "CFBundleIdentifier" in script
    assert "com.argus.sensor" in script
    assert "CFBundleExecutable" in script
    assert "plutil -lint" in script


def test_status_script_reports_mesh_and_gateway():
    script = read("scripts/dev/status_stack.sh")

    assert "docker compose -f infra/compose.yaml ps" in script
    assert "http://${HOST}:${PORT}/health" in script
