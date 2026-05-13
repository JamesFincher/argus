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
    assert "Storage worker" in script


def test_storage_worker_scripts_use_services_pythonpath_and_timeline_db():
    run_script = read("scripts/dev/run_storage_worker.sh")
    start_script = read("scripts/dev/start_storage_worker.sh")
    stop_script = read("scripts/dev/stop_storage_worker.sh")

    assert "ARGUS_TIMELINE_DB_PATH" in run_script
    assert "PYTHONPATH" in run_script
    assert "argus_services.storage_worker import main" in run_script
    assert "ARGUS_STORAGE_WORKER_PID_FILE" in start_script
    assert "ARGUS_STORAGE_WORKER_LOG_FILE" in start_script
    assert "ARGUS_STORAGE_WORKER_ERR_FILE" in start_script
    assert "ARGUS_STORAGE_WORKER_PID_FILE" in stop_script


def test_storage_worker_launchagent_points_at_repo_script():
    plist = read("infra/launchagents/com.argus.storage-worker.plist")

    assert "com.argus.storage-worker" in plist
    assert "scripts/dev/run_storage_worker.sh" in plist
    assert "ARGUS_TIMELINE_DB_PATH" in plist
