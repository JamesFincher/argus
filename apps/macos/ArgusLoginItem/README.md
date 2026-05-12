# Argus Login Item

ArgusOS should keep local sensing visible and user-controlled. The first
production persistence path should use an app-managed login item or a
LaunchAgent installed by explicit user action.

Rules:

- Do not install hidden background agents.
- Start paused unless the user previously opted into active sensing.
- Keep menu bar status visible while the helper is running.
- Bind helper services to loopback only.
- Store tokens and service credentials in Keychain, not plist files.
