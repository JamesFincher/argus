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


def test_repo_bootstrap_script_sets_up_full_argus_system_for_hermes():
    setup_script = read("scripts/dev/setup_argus_system.sh")
    mcp_runner = read("scripts/dev/run_argus_sensor_mcp.sh")
    readme = read("README.md")

    assert "uv sync" in setup_script
    assert 'uv pip install -e "$REPO_ROOT"' in setup_script
    assert "scripts/dev/start_mesh.sh" in setup_script
    assert "scripts/dev/start_event_gateway.sh" in setup_script
    assert "scripts/dev/start_storage_worker.sh" in setup_script
    assert "scripts/dev/package_macos_app.sh release" in setup_script
    assert "scripts/install_native_messaging_host.py install" in setup_script
    assert "hermes mcp add argus-sensor" in setup_script
    assert "scripts/dev/run_argus_sensor_mcp.sh" in setup_script
    assert "hermes mcp test argus-sensor" in setup_script
    assert "uv run python scripts/verify_hermes_runtime.py" in setup_script
    assert "Argus setup complete." in setup_script

    assert "exec uv run argus-sensor-mcp" in mcp_runner
    assert "ARGUS_TIMELINE_DB_PATH" in mcp_runner
    assert 'if [[ -n "${ARGUS_LANCEDB_PATH:-}" ]]' in mcp_runner
    assert 'ARGUS_LANCEDB_PATH="${ARGUS_LANCEDB_PATH:-}"' in setup_script
    assert 'command+=(--env "ARGUS_LANCEDB_PATH=$ARGUS_LANCEDB_PATH")' in setup_script
    assert "Hermes Bootstrap" in readme
    assert "scripts/dev/setup_argus_system.sh" in readme
    assert "Do not stop at summarizing the README." in readme


def test_macos_app_packaging_script_creates_bundle_structure():
    script = read("scripts/dev/package_macos_app.sh")

    assert 'APP_NAME="Argus Sensor"' in script
    assert '.app"' in script
    assert "CFBundleIdentifier" in script
    assert "com.argus.sensor" in script
    assert "CFBundleExecutable" in script
    assert 'swift build -c "$CONFIGURATION" --product "$PRODUCT_NAME"' in script
    assert 'find .build -path "*/$CONFIGURATION/$PRODUCT_NAME"' in script
    assert 'NATIVE_HOST_EXECUTABLE="$MACOS_DIR/argus-native-host"' in script
    assert "python3 -m argus_services.native_messaging" in script
    assert "plutil -lint" in script


def test_macos_app_packaging_script_stages_resources_and_dmg():
    script = read("scripts/dev/package_macos_app.sh")

    assert "scripts/install_native_messaging_host.py" in script
    assert "NativeMessaging/install_native_messaging_host.py" in script
    assert 'PACKAGED_SERVICES_DIR="$RESOURCES_DIR/services"' in script
    assert "services/argus_services" in script
    assert "Resources/services" in script
    assert '-name "__pycache__"' in script
    assert '-name "*.pyc"' in script
    assert 'LAUNCHAGENTS_DIR="$RESOURCES_DIR/LaunchAgents"' in script
    assert "infra/launchagents" in script
    assert "apps/macos/ArgusSafariExtension" in script
    assert "BrowserExtension/ArgusSafariExtension" in script
    assert "docs/macos-packaging.md" in script
    assert "ln -s /Applications" in script
    assert "hdiutil create" in script
    assert "-format UDZO" in script
    assert "hdiutil verify" in script


def test_macos_app_packaging_script_supports_unsigned_and_signing_ready_builds():
    script = read("scripts/dev/package_macos_app.sh")

    assert 'SIGN_IDENTITY="${ARGUS_CODESIGN_IDENTITY:-}"' in script
    assert "Skipping codesign" in script
    assert "codesign --force" in script
    assert "--options runtime" in script
    assert "--timestamp" in script
    assert "--entitlements" in script
    assert "codesign --verify" in script


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
