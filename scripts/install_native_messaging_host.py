#!/usr/bin/env python3
"""Install or remove the per-user Argus browser native messaging manifest."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "services"
if str(SERVICES) not in sys.path:  # pragma: no cover - depends on invocation path.
    sys.path.insert(0, str(SERVICES))

from argus_services.native_messaging import NATIVE_HOST_NAME  # noqa: E402


DESCRIPTION = "Argus Sensor browser page-context native messaging host"
DEFAULT_BROWSERS = ("chrome",)
BROWSER_MANIFEST_DIRS = {
    "chrome": Path.home() / "Library/Application Support/Google/Chrome/NativeMessagingHosts",
    "chrome-canary": Path.home()
    / "Library/Application Support/Google/Chrome Canary/NativeMessagingHosts",
    "chromium": Path.home() / "Library/Application Support/Chromium/NativeMessagingHosts",
    "edge": Path.home() / "Library/Application Support/Microsoft Edge/NativeMessagingHosts",
}


class NativeHostInstallError(RuntimeError):
    """Raised when the host manifest cannot be generated or installed."""


def native_host_manifest(host_path: Path | str, allowed_origins: Iterable[str]) -> dict[str, Any]:
    resolved_host_path = Path(host_path).expanduser()
    if not resolved_host_path.is_absolute():
        raise NativeHostInstallError("host path must be absolute")

    origins = normalize_allowed_origins(allowed_origins)
    return {
        "name": NATIVE_HOST_NAME,
        "description": DESCRIPTION,
        "path": str(resolved_host_path),
        "type": "stdio",
        "allowed_origins": origins,
    }


def normalize_allowed_origins(allowed_origins: Iterable[str]) -> list[str]:
    origins: list[str] = []
    seen: set[str] = set()
    for origin in allowed_origins:
        value = str(origin).strip()
        if not value:
            continue
        if not value.startswith("chrome-extension://") or not value.endswith("/"):
            raise NativeHostInstallError(
                "allowed origins must be chrome-extension://<extension-id>/ values"
            )
        if value not in seen:
            origins.append(value)
            seen.add(value)

    if not origins:
        raise NativeHostInstallError(
            "at least one allowed origin is required; pass --allowed-origin or set "
            "ARGUS_NATIVE_ALLOWED_ORIGINS"
        )
    return origins


def install_native_host(
    *,
    host_path: Path | str,
    allowed_origins: Iterable[str],
    browsers: Iterable[str] = DEFAULT_BROWSERS,
    manifest_root: Path | str | None = None,
) -> list[Path]:
    resolved_host_path = Path(host_path).expanduser().resolve()
    if not resolved_host_path.is_file():
        raise NativeHostInstallError(f"host executable not found: {resolved_host_path}")
    if not os.access(resolved_host_path, os.X_OK):
        raise NativeHostInstallError(f"host executable is not executable: {resolved_host_path}")

    manifest = native_host_manifest(resolved_host_path, allowed_origins)
    written: list[Path] = []
    for browser in normalize_browsers(browsers):
        path = manifest_path_for_browser(browser, manifest_root=manifest_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


def uninstall_native_host(
    *,
    browsers: Iterable[str] = DEFAULT_BROWSERS,
    manifest_root: Path | str | None = None,
) -> list[Path]:
    removed: list[Path] = []
    for browser in normalize_browsers(browsers):
        path = manifest_path_for_browser(browser, manifest_root=manifest_root)
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def manifest_path_for_browser(browser: str, manifest_root: Path | str | None = None) -> Path:
    browser_name = browser.strip().lower()
    if browser_name not in BROWSER_MANIFEST_DIRS:
        allowed = ", ".join(sorted(BROWSER_MANIFEST_DIRS))
        raise NativeHostInstallError(f"unsupported browser '{browser}'; choose one of: {allowed}")

    directory = Path(manifest_root).expanduser() / browser_name if manifest_root else BROWSER_MANIFEST_DIRS[browser_name]
    return directory / f"{NATIVE_HOST_NAME}.json"


def normalize_browsers(browsers: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for browser in browsers:
        value = str(browser).strip().lower()
        if not value:
            continue
        if value not in seen:
            manifest_path_for_browser(value)
            normalized.append(value)
            seen.add(value)
    return normalized or list(DEFAULT_BROWSERS)


def load_config(path: Path | str | None) -> dict[str, Any]:
    if path is None:
        return {}
    config_path = Path(path).expanduser()
    try:
        parsed = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NativeHostInstallError(f"invalid config JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise NativeHostInstallError("config file must contain a JSON object")
    return parsed


def resolve_host_path(cli_host_path: str | None, config: dict[str, Any]) -> Path:
    candidate = cli_host_path or config.get("host_path") or os.environ.get("ARGUS_NATIVE_HOST_PATH")
    if candidate:
        return Path(str(candidate)).expanduser()

    discovered = shutil.which("argus-native-host")
    if discovered:
        return Path(discovered)
    raise NativeHostInstallError(
        "argus-native-host was not found on PATH; pass --host-path with the packaged executable"
    )


def resolve_allowed_origins(cli_origins: list[str], config: dict[str, Any]) -> list[str]:
    if cli_origins:
        return normalize_allowed_origins(cli_origins)

    configured = config.get("allowed_origins")
    if configured is not None:
        if not isinstance(configured, list):
            raise NativeHostInstallError("config allowed_origins must be a list")
        return normalize_allowed_origins(configured)

    env_value = os.environ.get("ARGUS_NATIVE_ALLOWED_ORIGINS", "")
    if env_value:
        return normalize_allowed_origins(env_value.split(","))

    return normalize_allowed_origins([])


def resolve_browsers(cli_browsers: list[str], config: dict[str, Any]) -> list[str]:
    if cli_browsers:
        return normalize_browsers(cli_browsers)

    configured = config.get("browsers")
    if configured is not None:
        if not isinstance(configured, list):
            raise NativeHostInstallError("config browsers must be a list")
        return normalize_browsers(configured)

    return list(DEFAULT_BROWSERS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("install", help="write native messaging host manifest")
    install.add_argument("--host-path", help="absolute path to the packaged argus-native-host executable")
    install.add_argument(
        "--allowed-origin",
        action="append",
        default=[],
        help="allowed extension origin, for example chrome-extension://abcdefghijklmnop/",
    )
    install.add_argument("--browser", action="append", default=[], choices=sorted(BROWSER_MANIFEST_DIRS))
    install.add_argument("--config", help="JSON config with host_path, allowed_origins, and browsers")
    install.add_argument("--manifest-root", help=argparse.SUPPRESS)

    uninstall = subparsers.add_parser("uninstall", help="remove native messaging host manifest")
    uninstall.add_argument("--browser", action="append", default=[], choices=sorted(BROWSER_MANIFEST_DIRS))
    uninstall.add_argument("--config", help="JSON config with browsers")
    uninstall.add_argument("--manifest-root", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(getattr(args, "config", None))
        browsers = resolve_browsers(args.browser, config)
        if args.command == "install":
            paths = install_native_host(
                host_path=resolve_host_path(args.host_path, config),
                allowed_origins=resolve_allowed_origins(args.allowed_origin, config),
                browsers=browsers,
                manifest_root=args.manifest_root,
            )
            for path in paths:
                print(f"installed {path}")
        else:
            paths = uninstall_native_host(browsers=browsers, manifest_root=args.manifest_root)
            for path in paths:
                print(f"removed {path}")
    except NativeHostInstallError as exc:
        parser.exit(2, f"error: {exc}\n")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
