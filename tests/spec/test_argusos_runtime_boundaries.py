import plistlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_keychain_wrapper_uses_keychain_accessible_storage():
    source = read("apps/macos/ArgusCore/ArgusKeychain.swift")

    assert "SecItemAdd" in source
    assert "SecItemCopyMatching" in source
    assert "SecItemDelete" in source
    assert "kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly" in source
    assert "UserDefaults" not in source


def test_launch_agent_is_explicit_and_not_keepalive_hidden():
    with (ROOT / "infra/launchagents/com.argus.event-gateway.plist").open("rb") as handle:
        plist = plistlib.load(handle)

    assert plist["Label"] == "com.argus.event-gateway"
    assert plist["RunAtLoad"] is False
    assert plist["KeepAlive"] is False
    assert "/tmp/argus-event-gateway.log" == plist["StandardOutPath"]


def test_login_item_boundary_documents_visible_controls_and_keychain():
    text = read("apps/macos/ArgusLoginItem/README.md")

    assert "Do not install hidden background agents" in text
    assert "menu bar status visible" in text
    assert "Keychain" in text
