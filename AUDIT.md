# Audit Notes (2026-04-08)

## Scope

Code review + security-focused audit of the Flask backend and frontend posture for:
- upload handling,
- robot dispatch controls,
- error handling,
- runtime configuration,
- frontend module loading resilience,
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

### 4) Robot send speed lacked explicit validation (fixed)
- **Risk:** Without guardrails, malformed or out-of-range speed values could cause unstable dispatch timing.
- **Action:** Added `_validate_send_speed` with explicit finite-number and range checks (`0.25` to `1.0`), and return structured 400 errors for invalid requests.

### 5) Invalid robot-send requests used ambiguous error labeling (fixed)
- **Risk:** Mixed validation failures were reported under event-specific wording, making debugging harder.
- **Action:** Standardized request validation failures under `invalid_robot_send_request`, with concrete messages (timeline or send-speed specific).

### 6) 3D load path depended on a single CDN (fixed)
- **Risk:** If a single CDN is blocked (network policy, region, ad-blocking), users lose 3D preview.
- **Action:** Frontend now attempts `three.js` module loading from jsDelivr, then unpkg; if both fail, app falls back to built-in 2D rendering while keeping analyze/send workflow available.

### 7) UI overlay placement conflict for meter/status (fixed)
- **Risk:** Bottom-anchored meter and absolute overlays reduced usability and obscured controls in some viewport sizes.
- **Action:** Moved transport/servo meter to top of viewer and offset status box below it with explicit stacking order.

## Additional review observations (open)

1. **No authentication/authorization for `/api/send-to-robot`.**
   - In trusted LAN use this may be acceptable, but any exposed deployment should gate access.
2. **No rate limiting on robot dispatch route.**
   - Consider per-client throttling to prevent accidental flooding.
3. **CDN dependency remains for 3D in offline setups.**
   - Fallback now improves robustness, but true offline 3D still requires vendoring Three.js assets.

## Notes

- Existing `MAX_CONTENT_LENGTH` protection (50 MB) remains in place.
- Temporary-file cleanup in a `finally` block is already correctly implemented.
- Current test coverage includes send-speed validation and dry-run behavior for `/api/send-to-robot`.
