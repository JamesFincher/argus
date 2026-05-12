import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_safari_extension_manifest_and_native_message_contract():
    manifest = json.loads(read("apps/macos/ArgusSafariExtension/manifest.json"))
    content = read("apps/macos/ArgusSafariExtension/content.js")
    background = read("apps/macos/ArgusSafariExtension/background.js")

    assert manifest["name"] == "Argus Sensor"
    assert "nativeMessaging" in manifest["permissions"]
    assert "page_context" in content
    assert "href" in content
    assert "selection" in content
    assert "com.argus.sensor.native" in background


def test_optional_extension_boundaries_are_documented():
    mail = read("apps/macos/ArgusMailExtension/README.md")
    file_provider = read("apps/macos/ArgusFileProviderExtension/README.md")
    endpoint = read("apps/macos/ArgusEndpointSecurity/README.md")
    packaging = read("docs/macos-packaging.md")

    assert "Apple Mail-specific" in mail
    assert "Do not scrape private mail databases" in mail
    assert "Argus Memory" in file_provider
    assert "requires a separate entitlement" in endpoint
    normalized_packaging = " ".join(packaging.split())
    assert "not a claim that signing has already been completed" in normalized_packaging
    assert "No secrets" in packaging
