# SPEC.md

## Purpose

This specification reflects the **current implementation in this repository** and adds a detailed code review summary so future contributors can continue without rediscovering behavior or risks.

---

## 1) Product scope

The app is a Flask-based workflow tool for Kame32 dance experimentation:

1. Load audio and auto-generate a dance event timeline.
2. Preview movement in-browser (3D when possible, fallback 2D otherwise).
3. Edit/import timelines or keyframes.
4. Optionally send validated timelines to a robot over the known stock HTTP API.

It is **not** intended to be:

- a CAD-accurate digital twin,
- a full inverse-kinematics choreographer,
- or a firmware replacement.

---

## 2) Backend contract (`app.py`)

### Routes

- `GET /` → renders UI.
- `GET /api/presets` → returns demo routines.
- `POST /api/analyze-audio` → accepts uploaded audio and returns generated event timeline.
- `POST /api/send-to-robot` → validates timeline and either dry-runs or dispatches to robot endpoints.

### Upload limits and validation

- Max request body: `50 MB`.
- Allowed upload extensions: `.mp3`, `.wav`, `.ogg`, `.m4a`, `.flac`.
- Invalid or missing upload payloads return structured JSON errors with machine-friendly `code` values.
- Logging verbosity is configurable via `KAME32_LOG_LEVEL` (default `INFO`).

### Audio analysis pipeline

`build_events(audio_path)` currently does the following:

1. Loads mono audio at `22050 Hz` via `librosa.load`.
2. Splits harmonic/percussive components (`librosa.effects.hpss`).
3. Computes onset envelope, beat track, RMS, centroid, STFT-derived bass energy.
4. Falls back to synthetic beat grid when beat detection is sparse (<8 beats).
5. Samples features at beat times, z-score normalizes/clips feature tracks.
6. Infers bar offset from accent+bass profile.
7. Classifies bars (`low`/`mid`/`high`) using percentile thresholds.
8. Emits button and joystick events with phrase-aware heuristics.
9. Appends terminal neutral joystick + Stop events.
10. Compacts near-duplicate joystick events.

Response payload includes:

- `filename`, `tempo`, `duration`, `events`, `event_count`.

### Send-to-robot pipeline

- Base URL is normalized and defaults to `http://192.168.4.1`.
- Event payload is validated:
  - non-empty list,
  - sorted ascending by `t` before normalization (unsorted requests return 400),
  - max event count `5000`,
  - max timeline `600s`,
  - kinds limited to `button`, `joystick`, and `pose` (pose requires upgraded firmware),
  - button labels limited to `A/B/C/X/Y/Z/Start/Stop`.
- Boundary controls are enforced after validating the original events: initial Start and neutral at t=0, terminal neutral and Stop for stock events. Pose timelines enforce Start/Stop without inserting gait-home commands. Normalized events are revalidated against count and duration limits.
- Joystick coordinates must be numeric integers in `[-100, 100]`; booleans are rejected.
- `dry_run=true` returns metadata only; a strict JSON boolean is required.
- Live send uses a single-thread executor and timing-aligned dispatch.
- `send_speed` in `[0.25, 1.0]` stretches dispatch schedule.
- Live destinations must match `KAME32_ROBOT_ORIGINS` (comma-separated exact origins; default `http://192.168.4.1`). Credentials, paths, queries, fragments, and redirects are rejected.
- One dispatch can run per process; concurrent sends return `409 robot_busy` with no queueing.
- Wait deadline is normalized duration / send_speed + 15 seconds. Timeout signals cancellation; the worker interrupts waits and attempts neutral/Stop on failure. The slot remains held until the worker finishes. HTTP calls remain bounded by the 3-second call timeout. Network loss can prevent stop delivery.

### Error model

Handled API errors are returned with:

- human-readable `error`,
- optional `code`,
- optional `details`.

Robot network failures return `502 robot_unreachable` with sanitized details; unexpected dispatch failures return `500 robot_dispatch_failed` without raw exceptions. Wait expiry returns `504 robot_dispatch_timeout`. Non-object JSON bodies, non-string base URLs, and invalid dry-run types return structured 400 errors.

---

## 3) Frontend behavior (`templates/index.html`, `static/app.js`)

### UI structure

- Three-column layout: controls / viewer / robot-send panel.
- Workflow strip (“Analyze → Visualize → Send”) communicates expected sequence.
- Transport meter + time display + servo readout provide live feedback.

### Supported preview modes

1. **Joystick mode**: stock-like gait approximation from x/y + gait params.
2. **Button mode**: approximate routine-style movement for stock labels.
3. **Pose mode**: direct manual control of 8 servo angles.
4. **Events mode**: executes event timeline over transport clock.
5. **Keyframes mode**: linear interpolation between authored poses.

### Audio sync and transport

- When audio sync is active, transport follows `<audio>.currentTime`.
- Playback speed presets and numeric speed update both motion and (where active) audio playback rate.
- Seeking transport seeks audio in synchronized mode.

### Resilience

The client attempts dynamic ESM imports in this order for Three.js + OrbitControls:
1. local static modules under `/static/vendor/three/...`
2. `cdn.jsdelivr.net`
3. `unpkg.com`

A helper script (`scripts/install_three_local.sh`) can vendor local modules so restricted networks do not require browser policy changes.

If all sources fail, the app degrades gracefully:
- if the main app module still loads, a built-in 2D preview path is used and timeline/audio/send workflows continue,
- if the main module fails to load entirely, an inline HTML fallback keeps audio analysis available but disables timeline preview and robot send controls.

---

## 4) Data contracts

### Event timeline

```json
[
  {"t": 0.0, "kind": "button", "payload": "Start"},
  {"t": 0.2, "kind": "joystick", "payload": [0, 70]},
  {"t": 1.4, "kind": "button", "payload": "X"}
]
```

### Keyframe timeline

```json
[
  {"t": 0.0, "pose": {"s0": 90, "s1": 90, "s2": 80, "s3": 100, "s4": 90, "s5": 90, "s6": 100, "s7": 80}},
  {"t": 0.7, "pose": {"s0": 110, "s1": 70, "s2": 75, "s3": 105, "s4": 70, "s5": 110, "s6": 105, "s7": 75}}
]
```

---

## 5) Detailed code review summary

### Strengths

- Upload-size cap, extension filtering, and validation of event kinds, timestamps, labels, and send speed. See AUDIT.md for gaps.
- Structured errors for handled API failures, helpful for UI error handling.
- Enforced Start/neutral/Stop boundaries and best-effort cleanup on dispatch failures.
- **Robust music analysis fallback** when beat tracking is sparse.
- **Tests cover critical backend paths**: upload success, fallback behavior, validation failures, dry-run semantics, and dispatch error handling.

### Risks / technical debt

1. **Single-file backend concentration**: analysis, validation, HTTP dispatch, and routes all live in `app.py`; maintainability would improve by splitting modules.
2. **In-memory sync assumptions**: dispatch execution and app state are process-local (fine for current usage, but multi-worker deployments would need care).
3. **Frontend monolith**: `static/app.js` is large and multi-responsibility (rendering, state, transport, API calls), which increases regression risk.
4. **Algorithm opacity**: audio heuristic thresholds are data-driven percentile mixes but not externally configurable.
5. **No persistent project storage**: timeline/keyframe/audio metadata are session-local unless manually exported.

### Recommended next engineering steps

1. Factor backend into modules: `audio_analysis.py`, `robot_dispatch.py`, `api_routes.py`.
2. Add unit tests for individual helpers (`_compact_events`, `_infer_bar_offset`, `_with_safe_bookends`).
3. Add typed schema validation (e.g., Pydantic or Marshmallow) for request/response models.
4. Split frontend into smaller ES modules (transport, renderer, UI controls, API client).
5. Add optional persisted project format (JSON bundle with events/keyframes/settings).

---

## 6) Test status baseline

Current test suite (`tests/test_audio_analysis.py`) validates:

- successful audio uploads for bundled sample MP3s,
- fallback beat behavior on silence,
- upload validation failures,
- send-to-robot dry-run + base URL normalization,
- send speed validation,
- network and unexpected dispatch error responses.

The backend suite includes regression checks for destination restrictions, cancellation, busy rejection, terminal boundaries, malformed requests, coordinate limits, and exception redaction. Browser smoke validation confirmed local-static 3D startup during onboarding; full frontend interactions and physical hardware remain unverified. See AUDIT.md for remaining limitations.

## 7) TeachMoves

`GET /teach-moves` renders a separate teaching page with shared preview/manual controls and navigation to DanceMode (`GET /`). The shared pose engine samples the current joystick gait, button routine, or servo pose every 50 ms while recording, for up to 60 seconds. Recordings are keyframe arrays saved in six server-persisted slots named Move1 through Move6.

Selecting a slot enables playback, replacement recording, deletion, and transfer to DanceMode. Transfer uses session storage and loads the keyframe source paused on arrival. Moves use shared SQLite storage (see MCP.md), with one-time import from legacy browser-local slots. Storage failures are surfaced in the page; saved recordings are checked for finite timestamps and eight finite servo angles in the 0–180° range before use. Recording and browser playback never dispatch hardware commands. Explicit saved-move Send uses the upgraded pose/watchdog firmware; the stock robot API is rejected before pose motion. See FIRMWARE.md.

## 8) MCP and shared browser control

`mcp_server.py` uses the official MCP SDK and an HTTP adapter to the running Flask process (loopback by default, with explicitly trusted private service hosts for Docker). It supports stdio and Streamable HTTP, tools for analysis/moves/preview/dispatch, resources, and a teaching prompt. `control_api.py` registers validated move CRUD at `/api/moves` and bounded browser registration/command/acknowledgment endpoints. `static/mcp-bridge.js` reports preview state and executes commands in connected tabs. Browser control never sends hardware commands; live dispatch reuses the existing backend route. See MCP.md for contracts, limits, and deployment restrictions.

## 9) Pose dispatch and watchdog firmware

`POST /api/moves/<name>/send` defaults to dry-run and streams saved frames only when `dry_run=false` is explicit. The existing origin allowlist, single dispatch slot, speed-aware deadlines, and cancellation apply. The sender probes capabilities, requires pose/watchdog/controller-lease support for pose events, uses one lease token throughout playback, and sends heartbeats during gaps. The companion firmware patch adds `/pose`, scoped leases, a separate routine worker, and an independent watchdog that disables PWM on lease expiry. Physical acceptance remains unverified; see FIRMWARE.md.

## 10) Stock compatibility tracks

Shared storage also keeps optional validated joystick/button command tracks in `move_commands`; legacy pose-only rows remain valid. TeachMoves samples source controls at 20 Hz while recording pose frames. Unsupported source modes, custom gait settings, paused playback, or non-unit speed suppress the stock track. API save accepts optional `events`, validates that they contain only joystick/button and fit the move duration, and updates frames/commands transactionally. Saved-move dispatch accepts auto/stock/pose modes. Auto capability detection chooses poses when available, otherwise the native track. No servo-to-joystick approximation is performed. Stock firmware has no heartbeat watchdog and may reply only after a button routine finishes.

## 11) Isolated audio processing

The upload route saves a temporary input and calls `audio_process.analyze_in_process`. A nonblocking semaphore admits one analysis per app process; busy requests receive structured 429 errors. A new Linux process applies CPU (120 seconds soft / 125 hard) and address-space (4 GiB) limits before loading scientific dependencies, uses two numerical threads, and returns JSON. The parent enforces a 180-second wall deadline, terminates the worker process group on exit/timeout, reaps the worker, releases admission, and retains existing temporary-upload cleanup. Decoding reads at most 600 seconds and rejects decoded duration above 599 seconds before feature extraction. Robot dispatch remains in its independent executor; native analysis crashes cannot terminate the Flask process.

## 12) Current validation and roadmap

The Docker deployment passed all 55 tests after audio isolation. Browser/HTTP smoke checks additionally covered manual recording, stock compatibility, MCP connectivity, persisted recordings after recreation/restart, and robot-status responsiveness while a real audio analysis was active. Companion firmware builds and native lease tests passed. Physical acceptance, authenticated remote deployment, and independent backups/export-import remain outstanding; see AUDIT.md.
