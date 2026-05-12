# Argus Sensor watchOS

The watchOS app is a thin companion for controls, annotations, and consented
aggregate health/fitness context.

Initial surfaces:

- HealthKit aggregate summaries after authorization.
- WatchConnectivity transfer back to iPhone/Argus Core.
- Pause/resume and forget controls.
- User-authored annotations.

Rules:

- Do not implement an invisible always-running daemon.
- Do not forward raw health free text by default.
- Keep transfer payloads aggregate, redacted, and auditable.
