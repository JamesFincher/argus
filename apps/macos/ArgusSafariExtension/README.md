# Argus Safari Extension

This target is the browser-native signal path for Argus Sensor. It should send
page context through Safari Web Extension native messaging to the containing
macOS app instead of relying on OCR when DOM-level context is available.

Initial message contract:

```json
{
  "type": "page_context",
  "href": "https://example.com/path",
  "domain": "example.com",
  "title": "Example",
  "selection": "selected text if the user selected any"
}
```

Rules:

- User approval and Safari extension enablement are required.
- Selection text is redacted before any downstream summary.
- Browser extension context takes precedence over screen OCR.
- Password-manager, banking, identity-provider, payroll, and other denied
  domains must flow to policy-blocked events by default.
