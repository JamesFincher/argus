# macOS Packaging Plan

Argus Sensor should ship as a signed and notarized macOS app once real signing
credentials are available. This document is a packaging gate, not a claim that
signing has already been completed.

## Build Gate

```sh
swift build --target ArgusSensorMac
swift test
```

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
