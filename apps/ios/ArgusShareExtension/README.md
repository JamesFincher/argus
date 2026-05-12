# Argus Share Extension

The Share Extension is the primary iOS intake path. It runs only when the user
explicitly shares content into Argus Sensor.

Message contract:

```json
{
  "type": "user_share",
  "source_app": "com.apple.mobilesafari",
  "content_type": "url|text|image|document",
  "title": "optional title",
  "url": "optional url",
  "text": "optional user-selected text"
}
```

The containing app must normalize and redact this payload before forwarding it
to Argus Core.
