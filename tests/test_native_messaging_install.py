import importlib.util
import json
from pathlib import Path

import pytest

from argus_services.native_messaging import NATIVE_HOST_NAME


ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = ROOT / "scripts/install_native_messaging_host.py"


spec = importlib.util.spec_from_file_location("install_native_messaging_host", INSTALLER_PATH)
installer = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(installer)


def make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_native_host_manifest_shape_and_host_name(tmp_path):
    host = make_executable(tmp_path / "argus-native-host")

    manifest = installer.native_host_manifest(
        host,
        [
            "chrome-extension://abcdefghijklmnopabcdefghijklmnop/",
            "chrome-extension://abcdefghijklmnopabcdefghijklmnop/",
        ],
    )

    assert manifest == {
        "name": NATIVE_HOST_NAME,
        "description": "Argus Sensor browser page-context native messaging host",
        "path": str(host),
        "type": "stdio",
        "allowed_origins": ["chrome-extension://abcdefghijklmnopabcdefghijklmnop/"],
    }


def test_native_host_manifest_requires_absolute_host_path():
    with pytest.raises(installer.NativeHostInstallError, match="host path must be absolute"):
        installer.native_host_manifest(
            "argus-native-host",
            ["chrome-extension://abcdefghijklmnopabcdefghijklmnop/"],
        )


def test_allowed_origin_validation_requires_chrome_extension_origin():
    with pytest.raises(installer.NativeHostInstallError, match="at least one allowed origin"):
        installer.normalize_allowed_origins([])

    assert installer.normalize_allowed_origins(
        ["", "chrome-extension://abcdefghijklmnopabcdefghijklmnop/"]
    ) == ["chrome-extension://abcdefghijklmnopabcdefghijklmnop/"]

    for origin in [
        "https://example.com/",
        "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
    ]:
        with pytest.raises(installer.NativeHostInstallError, match="allowed origins"):
            installer.normalize_allowed_origins([origin])


def test_browser_manifest_path_rejects_unsupported_browser_and_normalizes_empty(tmp_path):
    with pytest.raises(installer.NativeHostInstallError, match="unsupported browser"):
        installer.manifest_path_for_browser("firefox", manifest_root=tmp_path)

    assert installer.normalize_browsers(["", "chrome", "chrome"]) == ["chrome"]
    assert installer.normalize_browsers([""]) == ["chrome"]


def test_install_writes_browser_manifest_for_packaged_executable(tmp_path):
    host = make_executable(tmp_path / "bin" / "argus-native-host")
    manifest_root = tmp_path / "native-hosts"

    written = installer.install_native_host(
        host_path=host,
        allowed_origins=["chrome-extension://abcdefghijklmnopabcdefghijklmnop/"],
        browsers=["chrome", "edge"],
        manifest_root=manifest_root,
    )

    assert written == [
        manifest_root / "chrome" / f"{NATIVE_HOST_NAME}.json",
        manifest_root / "edge" / f"{NATIVE_HOST_NAME}.json",
    ]
    for path in written:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert manifest["name"] == NATIVE_HOST_NAME
        assert manifest["path"] == str(host.resolve())
        assert manifest["type"] == "stdio"
        assert manifest["allowed_origins"] == [
            "chrome-extension://abcdefghijklmnopabcdefghijklmnop/"
        ]


def test_install_rejects_missing_or_non_executable_host(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(installer.NativeHostInstallError, match="not found"):
        installer.install_native_host(
            host_path=missing,
            allowed_origins=["chrome-extension://abcdefghijklmnopabcdefghijklmnop/"],
            manifest_root=tmp_path,
        )

    not_executable = tmp_path / "argus-native-host"
    not_executable.write_text("#!/bin/sh\n", encoding="utf-8")
    not_executable.chmod(0o644)

    with pytest.raises(installer.NativeHostInstallError, match="not executable"):
        installer.install_native_host(
            host_path=not_executable,
            allowed_origins=["chrome-extension://abcdefghijklmnopabcdefghijklmnop/"],
            manifest_root=tmp_path,
        )


def test_config_and_environment_behavior(tmp_path, monkeypatch):
    host = make_executable(tmp_path / "argus-native-host")
    config = tmp_path / "native-host.json"
    config.write_text(
        json.dumps(
            {
                "host_path": str(host),
                "allowed_origins": ["chrome-extension://configconfigconfigconfigcfg/"],
                "browsers": ["chromium"],
            }
        ),
        encoding="utf-8",
    )

    loaded = installer.load_config(config)
    assert installer.resolve_host_path(None, loaded) == host
    assert installer.resolve_allowed_origins([], loaded) == [
        "chrome-extension://configconfigconfigconfigcfg/"
    ]
    assert installer.resolve_browsers([], loaded) == ["chromium"]

    monkeypatch.setenv("ARGUS_NATIVE_ALLOWED_ORIGINS", "chrome-extension://envenvenvenvenvenvenvenvenvenv/")
    assert installer.resolve_allowed_origins([], {}) == [
        "chrome-extension://envenvenvenvenvenvenvenvenvenv/"
    ]
    assert installer.resolve_allowed_origins(
        ["chrome-extension://cliclicliclicliclicliclicli/"],
        loaded,
    ) == ["chrome-extension://cliclicliclicliclicliclicli/"]
    assert installer.resolve_browsers([], {}) == ["chrome"]


def test_config_validation_and_resolution_errors(tmp_path, monkeypatch):
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{", encoding="utf-8")
    with pytest.raises(installer.NativeHostInstallError, match="invalid config JSON"):
        installer.load_config(invalid_json)

    non_object = tmp_path / "list.json"
    non_object.write_text("[]", encoding="utf-8")
    with pytest.raises(installer.NativeHostInstallError, match="JSON object"):
        installer.load_config(non_object)

    with pytest.raises(installer.NativeHostInstallError, match="allowed_origins must be a list"):
        installer.resolve_allowed_origins([], {"allowed_origins": "chrome-extension://bad/"})

    monkeypatch.delenv("ARGUS_NATIVE_ALLOWED_ORIGINS", raising=False)
    with pytest.raises(installer.NativeHostInstallError, match="at least one allowed origin"):
        installer.resolve_allowed_origins([], {})

    with pytest.raises(installer.NativeHostInstallError, match="browsers must be a list"):
        installer.resolve_browsers([], {"browsers": "chrome"})


def test_host_path_resolution_uses_environment_path_or_path_lookup(tmp_path, monkeypatch):
    host = make_executable(tmp_path / "argus-native-host")

    monkeypatch.setenv("ARGUS_NATIVE_HOST_PATH", str(host))
    assert installer.resolve_host_path(None, {}) == host

    monkeypatch.delenv("ARGUS_NATIVE_HOST_PATH")
    monkeypatch.setattr(installer.shutil, "which", lambda name: str(host))
    assert installer.resolve_host_path(None, {}) == host

    monkeypatch.setattr(installer.shutil, "which", lambda name: None)
    with pytest.raises(installer.NativeHostInstallError, match="was not found on PATH"):
        installer.resolve_host_path(None, {})


def test_uninstall_removes_existing_manifests_and_ignores_missing(tmp_path):
    chrome_manifest = tmp_path / "chrome" / f"{NATIVE_HOST_NAME}.json"
    edge_manifest = tmp_path / "edge" / f"{NATIVE_HOST_NAME}.json"
    chrome_manifest.parent.mkdir(parents=True)
    edge_manifest.parent.mkdir(parents=True)
    chrome_manifest.write_text("{}", encoding="utf-8")
    edge_manifest.write_text("{}", encoding="utf-8")

    removed = installer.uninstall_native_host(
        browsers=["chrome", "edge", "chromium"],
        manifest_root=tmp_path,
    )

    assert removed == [chrome_manifest, edge_manifest]
    assert not chrome_manifest.exists()
    assert not edge_manifest.exists()
    assert installer.uninstall_native_host(browsers=["chrome"], manifest_root=tmp_path) == []


def test_cli_install_and_uninstall(tmp_path, capsys):
    host = make_executable(tmp_path / "argus-native-host")
    manifest_root = tmp_path / "manifests"
    origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop/"

    assert installer.main(
        [
            "install",
            "--host-path",
            str(host),
            "--allowed-origin",
            origin,
            "--browser",
            "chrome",
            "--manifest-root",
            str(manifest_root),
        ]
    ) == 0
    manifest_path = manifest_root / "chrome" / f"{NATIVE_HOST_NAME}.json"
    assert manifest_path.exists()
    assert f"installed {manifest_path}" in capsys.readouterr().out

    assert installer.main(
        [
            "uninstall",
            "--browser",
            "chrome",
            "--manifest-root",
            str(manifest_root),
        ]
    ) == 0
    assert not manifest_path.exists()
    assert f"removed {manifest_path}" in capsys.readouterr().out


def test_cli_reports_install_errors(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc_info:
        installer.main(
            [
                "install",
                "--host-path",
                str(tmp_path / "missing-host"),
                "--allowed-origin",
                "chrome-extension://abcdefghijklmnopabcdefghijklmnop/",
                "--manifest-root",
                str(tmp_path / "manifests"),
            ]
        )

    assert exc_info.value.code == 2
    assert "host executable not found" in capsys.readouterr().err
