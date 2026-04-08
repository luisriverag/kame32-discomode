# Audit Notes (2026-04-08)

## Scope

Quick security-focused audit of the Flask backend and dependency posture for:
- upload handling,
- error handling,
- runtime configuration,
- and known dependency vulnerabilities.

## Findings and actions

### 1) Flask debug mode enabled by default (fixed)
- **Risk:** Running with `debug=True` in production can expose interactive debugger behavior and sensitive internals.
- **Action:** Switched to env-controlled debug mode via `FLASK_DEBUG` and defaulted to `False`.

### 2) Detailed backend exception text returned to clients (fixed)
- **Risk:** Returning raw exception text can leak implementation details.
- **Action:** Replaced raw exception echoing with a generic client-facing error while logging full stack traces server-side.

### 3) Audio upload suffix not allow-listed (fixed)
- **Risk:** Any suffix was accepted and forwarded to the analysis pipeline.
- **Action:** Added a conservative extension allow-list (`.mp3`, `.wav`, `.ogg`, `.m4a`, `.flac`) before processing.

## Notes

- Existing `MAX_CONTENT_LENGTH` protection (50 MB) remains in place.
- Temporary-file cleanup in a `finally` block is already correctly implemented.
