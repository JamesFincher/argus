# Argus Endpoint Security Boundary

Endpoint Security is optional and requires a separate entitlement and
distribution path. Argus must keep it isolated from the default macOS app.

Rules:

- Do not assume the entitlement is available.
- Do not make Endpoint Security a default dependency of Argus Sensor.
- Collect process/file execution metadata only when explicitly approved and
  entitled.
- Keep policy, redaction, audit, and pause controls identical to other sensors.
