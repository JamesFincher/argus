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
- MailKit target is bundled only when Apple Mail integration is enabled.
- File Provider target is bundled only when Argus Memory drive support is
  enabled.
- Endpoint Security component is excluded unless the entitlement and separate
  approval path are present.

## Signing And Notarization Gate

Required release inputs:

- Developer ID Application certificate.
- Hardened runtime enabled.
- Entitlements reviewed for each app/extension target.
- `xcrun notarytool` credentials configured outside the repository.
- Stapled notarization ticket verified on the final artifact.

No secrets, signing credentials, or notarization profiles should be stored in
this repository.
