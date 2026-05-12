# macOS File Activity Sensor Plan

Argus may use FSEvents for metadata-level file activity when the user enables a
scope. It should not read file contents by default.

Allowed event fields:

- path hash or user-approved relative path
- event flags
- observed timestamp
- scoped root identifier
- file type hint if available without opening the file

Rules:

- User chooses watched roots.
- Metadata-only by default.
- Raw file contents require explicit policy-gated expansion.
- Denylist sensitive roots such as password-manager stores, keychains, browser
  profile secrets, SSH keys, and payroll/banking exports.
- Pause/forget controls apply to file activity like every other sensor.
