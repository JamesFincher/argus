# macOS Packaging Plan

Argus Sensor should ship as a signed and notarized macOS app once real signing
credentials are available. This document is a packaging gate, not a claim that
signing has already been completed.

## Build Gate

```sh
swift build --target ArgusSensorMac
swift test
```

## Local App And DMG Build

The local packaging script creates `dist/Argus Sensor.app` and, by default,
`dist/Argus-Sensor-release.dmg` using Apple's `hdiutil`.

```sh
scripts/dev/package_macos_app.sh release
```

Unsigned local builds are supported by default so contributors can inspect the
bundle and DMG without Developer ID credentials. To exercise signing readiness,
set `ARGUS_CODESIGN_IDENTITY` to a Developer ID Application identity or `-` for
ad-hoc signing before running the script. Set `ARGUS_CREATE_DMG=0` to build only
the `.app` bundle.

The bundle stages packaging resources under `Contents/Resources`:

- `NativeMessaging/install_native_messaging_host.py` plus installation notes.
- `services/argus_services`, used by the packaged native host wrapper.
- `BrowserExtension/ArgusSafariExtension` when the scaffold exists.
- `LaunchAgents` plists for the loopback gateway and storage worker.
- This packaging checklist for release review.

The bundle also stages `Contents/MacOS/argus-native-host`, a wrapper that runs
`python3 -m argus_services.native_messaging` with `Contents/Resources/services`
on `PYTHONPATH`. This makes the host path used in the native messaging manifest
real for local MVP packages.

## Extension Packaging Gate

Required before a release build:

- Safari Web Extension target is bundled and enablement is visible to the user.
- Browser native messaging host manifest is installed for the current user with
  the packaged `argus-native-host` executable path and the release extension
  origin.
- MailKit target is bundled only when Apple Mail integration is enabled.
- File Provider target is bundled only when Argus Memory drive support is
  enabled.
- Endpoint Security component is excluded unless the entitlement and separate
  approval path are present.

## Native Messaging Host

The MVP installer writes Chromium-family native messaging manifests under the
current user's `~/Library/Application Support/.../NativeMessagingHosts`
directory. The manifest name is `com.argus.sensor.native`, the host `path` must
point at an executable packaged `argus-native-host`, and `allowed_origins` must
list the exact extension origins allowed to call the host.

Install for Chrome:

```sh
python scripts/install_native_messaging_host.py install \
  --host-path "$(command -v argus-native-host)" \
  --allowed-origin "chrome-extension://<extension-id>/" \
  --browser chrome
```

Install from a packaged app:

```sh
python3 "/Applications/Argus Sensor.app/Contents/Resources/NativeMessaging/install_native_messaging_host.py" install \
  --host-path "/Applications/Argus Sensor.app/Contents/MacOS/argus-native-host" \
  --allowed-origin "chrome-extension://<extension-id>/" \
  --browser chrome
```

Install with config:

```json
{
  "host_path": "/Applications/Argus Sensor.app/Contents/MacOS/argus-native-host",
  "allowed_origins": ["chrome-extension://<extension-id>/"],
  "browsers": ["chrome", "edge"]
}
```

```sh
python scripts/install_native_messaging_host.py install --config native-host.json
```

Uninstall:

```sh
python scripts/install_native_messaging_host.py uninstall --browser chrome
```

## Signing And Notarization Gate

Required release inputs:

- Developer ID Application certificate.
- Hardened runtime enabled.
- Entitlements reviewed for each app/extension target.
- `xcrun notarytool` credentials configured outside the repository.
- Stapled notarization ticket verified on the final artifact.

No secrets, signing credentials, or notarization profiles should be stored in
this repository.
