# Argus Mail Extension

MailKit support is intentionally optional and Apple Mail-specific. This
placeholder exists to keep the extension boundary explicit before adding an
Xcode target with entitlements.

Scope:

- Capture message metadata, compose lifecycle, and user-invoked actions where
  MailKit allows it.
- Do not treat MailKit as universal email access.
- Do not scrape private mail databases.
- Send metadata summaries to Argus Core; raw message bodies require explicit
  policy-gated expansion.
