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
  - sorted ascending by `t`,
  - max event count `5000`,
  - max timeline `600s`,
  - kinds limited to `button` and `joystick`,
  - button labels limited to `A/B/C/X/Y/Z/Start/Stop`.
- Safety bookends are automatically inserted when absent:
  - Start button,
  - early neutral joystick,
  - Stop button.
- `dry_run=true` returns metadata only.
- Live send uses a single-thread executor and timing-aligned dispatch.
- `send_speed` in `[0.25, 1.0]` stretches dispatch schedule.

### Error model

Structured errors are consistently returned with:

- human-readable `error`,
- optional `code`,
- optional `details`.

Robot network failures return `502 robot_unreachable`; unexpected dispatch failures return `500 robot_dispatch_failed`.

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

- **Good guardrails on untrusted inputs** (upload-size cap, extension filtering, strict event validation).
- **Consistent API error shape**, helpful for UI error handling.
- **Practical safety defaults** before robot dispatch (auto Start/neutral/Stop).
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

This gives a strong baseline for backend behavior but leaves major frontend flows untested.
