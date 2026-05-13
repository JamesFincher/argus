#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

CONFIGURATION="${1:-release}"
APP_NAME="Argus Sensor"
BUNDLE_ID="com.argus.sensor"
EXECUTABLE_NAME="ArgusSensorMac"
PRODUCT_NAME="argus-sensor-mac"
DIST_DIR="$PWD/dist"
APP_DIR="$DIST_DIR/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
NATIVE_MESSAGING_DIR="$RESOURCES_DIR/NativeMessaging"
BROWSER_EXTENSION_DIR="$RESOURCES_DIR/BrowserExtension/ArgusSafariExtension"
PACKAGED_SERVICES_DIR="$RESOURCES_DIR/services"
LAUNCHAGENTS_DIR="$RESOURCES_DIR/LaunchAgents"
NATIVE_HOST_EXECUTABLE="$MACOS_DIR/argus-native-host"
DMG_STAGING_DIR="$DIST_DIR/dmg/$APP_NAME"
DMG_PATH="$DIST_DIR/Argus-Sensor-$CONFIGURATION.dmg"
SIGN_IDENTITY="${ARGUS_CODESIGN_IDENTITY:-}"
CREATE_DMG="${ARGUS_CREATE_DMG:-1}"

swift build -c "$CONFIGURATION" --product "$PRODUCT_NAME"

PRODUCT_PATH=".build/$CONFIGURATION/$PRODUCT_NAME"
if [[ ! -f "$PRODUCT_PATH" ]]; then
  PRODUCT_PATH="$(find .build -path "*/$CONFIGURATION/$PRODUCT_NAME" -type f -print -quit)"
fi
if [[ ! -f "$PRODUCT_PATH" ]]; then
  echo "error: built product was not found for configuration '$CONFIGURATION': $PRODUCT_NAME" >&2
  exit 1
fi

rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" "$NATIVE_MESSAGING_DIR"

cp "$PRODUCT_PATH" "$MACOS_DIR/$EXECUTABLE_NAME"
chmod +x "$MACOS_DIR/$EXECUTABLE_NAME"

cp "scripts/install_native_messaging_host.py" "$NATIVE_MESSAGING_DIR/install_native_messaging_host.py"
chmod +x "$NATIVE_MESSAGING_DIR/install_native_messaging_host.py"

mkdir -p "$PACKAGED_SERVICES_DIR"
ditto --noextattr "services/argus_services" "$PACKAGED_SERVICES_DIR/argus_services"
find "$PACKAGED_SERVICES_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$PACKAGED_SERVICES_DIR" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete

cat > "$NATIVE_HOST_EXECUTABLE" <<'BASH'
#!/usr/bin/env bash
set -euo pipefail

CONTENTS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$CONTENTS_DIR/Resources/services${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m argus_services.native_messaging "$@"
BASH
chmod +x "$NATIVE_HOST_EXECUTABLE"

cat > "$NATIVE_MESSAGING_DIR/README.md" <<'MARKDOWN'
# Argus Native Messaging Host

This packaged helper installs Chromium-family native messaging manifests for
the current macOS user. The app bundle includes a real `argus-native-host`
wrapper at `Contents/MacOS/argus-native-host`; pass the exact extension origin
allowed to call it.

```sh
python3 "/Applications/Argus Sensor.app/Contents/Resources/NativeMessaging/install_native_messaging_host.py" install \
  --host-path "/Applications/Argus Sensor.app/Contents/MacOS/argus-native-host" \
  --allowed-origin "chrome-extension://<extension-id>/" \
  --browser chrome
```

The MVP app bundle includes this installer so release packaging can be reviewed
without writing per-user browser manifests during app installation.
MARKDOWN

if [[ -d "apps/macos/ArgusSafariExtension" ]]; then
  mkdir -p "$BROWSER_EXTENSION_DIR"
  ditto "apps/macos/ArgusSafariExtension" "$BROWSER_EXTENSION_DIR"
fi

cp "docs/macos-packaging.md" "$RESOURCES_DIR/macOS Packaging.md"

if [[ -d "infra/launchagents" ]]; then
  mkdir -p "$LAUNCHAGENTS_DIR"
  ditto --noextattr "infra/launchagents" "$LAUNCHAGENTS_DIR"
fi

cat > "$CONTENTS_DIR/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>$EXECUTABLE_NAME</string>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_ID</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundleDisplayName</key>
  <string>$APP_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>14.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSHumanReadableCopyright</key>
  <string>Copyright © 2026 Argus</string>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
</dict>
</plist>
PLIST

cat > "$CONTENTS_DIR/PkgInfo" <<PKG
APPL????
PKG

cat > "$CONTENTS_DIR/Argus.entitlements" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>com.apple.security.app-sandbox</key>
  <false/>
</dict>
</plist>
PLIST

plutil -lint "$CONTENTS_DIR/Info.plist" "$CONTENTS_DIR/Argus.entitlements"

if [[ -n "$SIGN_IDENTITY" ]]; then
  codesign --force \
    --options runtime \
    --timestamp \
    --entitlements "$CONTENTS_DIR/Argus.entitlements" \
    --sign "$SIGN_IDENTITY" \
    "$APP_DIR"
  codesign --verify --strict --deep --verbose=2 "$APP_DIR"
else
  echo "Skipping codesign: ARGUS_CODESIGN_IDENTITY is not set; created unsigned local app bundle."
fi

if [[ "$CREATE_DMG" == "1" ]]; then
  rm -rf "$DMG_STAGING_DIR" "$DMG_PATH"
  mkdir -p "$DMG_STAGING_DIR"
  ditto "$APP_DIR" "$DMG_STAGING_DIR/$APP_NAME.app"
  ln -s /Applications "$DMG_STAGING_DIR/Applications"
  cp "docs/macos-packaging.md" "$DMG_STAGING_DIR/Native Messaging Install.md"

  hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$DMG_STAGING_DIR" \
    -ov \
    -format UDZO \
    "$DMG_PATH"
  hdiutil verify "$DMG_PATH"
  echo "$DMG_PATH"
fi

echo "$APP_DIR"
