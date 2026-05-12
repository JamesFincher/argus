from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ios_scaffold_uses_approved_consent_surfaces():
    ios = read("apps/ios/ArgusSensorIOS/README.md")
    share = read("apps/ios/ArgusShareExtension/README.md")
    safari = read("apps/ios/ArgusSafariWebExtension/README.md")
    device = read("apps/ios/ArgusDeviceActivityExtension/README.md")

    assert "Share Extension" in ios
    assert "App Intents" in ios
    assert "BackgroundTasks" in ios
    assert "Do not emulate macOS-style universal sensing" in ios
    assert "explicitly shares content" in share
    assert "redact" in share
    assert "user enables the extension" in safari
    assert "aggregate-only" in device
    assert "Raw screen contents" in device


def test_watchos_scaffold_is_thin_consent_companion():
    watch = read("apps/watchos/ArgusSensorWatch/README.md")

    assert "HealthKit aggregate summaries" in watch
    assert "WatchConnectivity" in watch
    assert "Pause/resume" in watch
    assert "Do not implement an invisible always-running daemon" in watch
    assert "Do not forward raw health free text by default" in watch
