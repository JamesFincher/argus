# Argus Sensor iOS

Argus Sensor on iOS is a consented companion, not a universal ambient observer.
It should collect user-shared and system-scheduled context using Apple-approved
extension and background surfaces.

Initial surfaces:

- Share Extension for user-invoked page, text, image, and document handoff.
- Safari Web Extension for browser context where the user enables it.
- App Intents/Shortcuts for explicit capture and controls.
- BackgroundTasks for scheduled sync of already-approved data.
- Optional DeviceActivity/FamilyControls aggregate reporting.

Rules:

- Do not emulate macOS-style universal sensing on iPhone.
- Do not rely on hidden background execution.
- Do not bypass extension process boundaries or permission prompts.
- Raw user-shared content must be redacted before summaries leave the device.
