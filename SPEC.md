# SPEC.md

## Purpose

This document captures the current known specification for the Kame32 dance-preview work completed so far in this conversation. It combines:
- confirmed behavior from the current stock Kame32 gamepad firmware,
- the current Flask 3D preview app implementation,
- the MP3-to-dance analysis pipeline,
- and the requested playback-speed additions.

It is intentionally detailed so the project can be continued without re-discovering the same design decisions.

## Project scope

The current project is **not** a full robot digital twin and **not** a full inverse-kinematics choreographer.

The current goal is to provide a practical workflow:

1. preview likely Kame32 motion in the browser,
2. import or auto-generate event timelines,
3. audition those timelines with uploaded music,
4. slow the preview to 50% or 25% speed when needed,
5. and keep the data structures close to the stock Wi-Fi firmware currently running on the robot.

## Confirmed Kame32 stock control model

### Current user setup
- The user's deployed robot is currently managed through the stock-style web interface at `192.168.4.1`.
- The current working assumption is that the robot is reachable over HTTP at that address.

### Stock HTTP API shape
The currently known stock firmware exposes:

- `GET /`
- `GET /joystick?x=...&y=...`
- `GET /button?label=...`

### Known joystick semantics
- `x` is turn / angular intent.
- `y` is forward-back / linear intent.
- The firmware stores the most recent joystick values and keeps producing gait motion until another joystick value is sent.
- Sending `x=0` and `y=0` is the practical stop command for movement.
- When there is no active joystick input, the firmware returns the robot to `home()`.

### Known button labels
The stock button handler currently recognizes:

- `A` → `hello()`
- `B` → `jump()`
- `C` → `pushUp(4, 1000)`
- `X` → `dance(2, 1000)`
- `Y` → `moonwalkL(2, 2000)`
- `Z` → `frontBack(2, 1000)`
- `Start` → `arm()`
- `Stop` → `disarm()`

### Known stock gait parameters
The current preview app mirrors these values from the stock gamepad firmware:

- `period = 450`
- `leg_spread = 20`
- `body_height = 10`
- `step_height = 20`

### Known stock phase arrays
Linear-dominant movement uses:

- `phase_linear = [90, 90, 270, 90, 270, 270, 90, 270]`

Angular-dominant movement uses:

- `phase_angular = [90, 270, 270, 90, 270, 90, 90, 270]`

### Known oscillator grouping
The stock gait logic treats:
- servos `0, 1, 4, 5` as the step-amplitude group,
- servos `2, 3, 6, 7` as the step-height group.

The preview app maps these to hips vs knees for visualization.

## Preview app architecture

### Backend
Current backend: Flask.

Current routes:
- `/` → serves the app UI
- `/api/presets` → returns demo event and keyframe presets
- `/api/analyze-audio` → accepts uploaded audio and returns a generated event timeline

### Frontend
Current frontend: one HTML page plus one browser-side JS module using Three.js.

Main frontend responsibilities:
- render a 3D quadruped preview,
- maintain a playback transport,
- provide multiple preview modes,
- import JSON timelines,
- upload audio for analysis,
- keep browser audio and preview motion synchronized,
- and expose playback-speed presets.

## Supported preview modes

### 1. Live joystick mode
Purpose:
- preview stock-style gait behavior driven by `x` and `y`.

Inputs:
- joystick x
- joystick y
- period
- step height
- leg spread
- body height

Behavior:
- if `abs(y) >= abs(x)`, the app uses the linear phase array and models forward/back walking behavior.
- otherwise it uses the angular phase array and models turning behavior.
- the preview synthesizes servo angles over time using sinusoidal motion.

### 2. Button routine mode
Purpose:
- preview the style and timing of stock button-triggered routines.

Important limitation:
- these are **visual approximations**, not exact reconstructions of the internal Kame library routines.

Approximate durations used in the preview:
- `A`: `1.2s`
- `B`: `0.8s`
- `X`: `1.4s`
- `Y`: `2.2s`
- `Z`: `1.2s`
- `Start`: `0.2s`
- `Stop`: `0.2s`

### 3. Manual servo pose mode
Purpose:
- preview a direct 8-servo pose.

Behavior:
- user adjusts sliders for `s0` through `s7`,
- pose is immediately applied to the 3D model.

### 4. Event timeline JSON mode
Purpose:
- preview event streams shaped like the Wi-Fi control script.

Supported event styles:
- joystick events: `{"t": 1.2, "kind": "joystick", "payload": [x, y]}`
- button events: `{"t": 2.0, "kind": "button", "payload": "X"}`
- pose events: `{"t": 3.5, "kind": "pose", "pose": {...}}`

Behavior:
- joystick events update internal joystick state,
- button events activate approximate routine previews,
- pose events can be treated like pose keyframes.

### 5. Keyframe JSON mode
Purpose:
- preview exact user-authored servo poses over time.

Format:
- `[{ "t": 0.0, "pose": {...} }, ...]`

Behavior:
- frames are sorted by time,
- interpolation is linear per-servo,
- missing servos are filled from the app's `homePose`.

## Servo mapping used by the preview

The current preview uses this practical mapping:

- `s0` front-left hip
- `s1` front-right hip
- `s2` front-left knee
- `s3` front-right knee
- `s4` rear-right hip
- `s5` rear-left hip
- `s6` rear-left knee
- `s7` rear-right knee

This mapping is suitable for preview and can be adjusted later if the physical build differs.

## 3D viewer model

The current 3D model is a stylized preview mesh, not a CAD-accurate Kame32 replica.

### Current scene elements
- body box
- top shell box
- four legs
- each leg has:
  - leg root
  - hip pivot
  - upper segment
  - knee pivot
  - lower segment
  - foot sphere
- ground disc
- grid helper
- hemisphere light
- directional light
- orbit camera controls

### Current leg anchor layout
- front-left mount: `(1.6, 0.0, 1.0)`
- front-right mount: `(1.6, 0.0, -1.0)`
- rear-left mount: `(-1.6, 0.0, 1.0)`
- rear-right mount: `(-1.6, 0.0, -1.0)`

### Current segment lengths
- upper leg length: `1.3`
- lower leg length: `1.3`

### Current home pose
- `s0 = 110`
- `s1 = 70`
- `s2 = 80`
- `s3 = 100`
- `s4 = 70`
- `s5 = 110`
- `s6 = 100`
- `s7 = 80`

## MP3 / audio analysis pipeline

### Upload flow
1. user selects an audio file in the browser,
2. browser uploads it as form field `audio` to `/api/analyze-audio`,
3. backend stores it temporarily,
4. backend analyzes it with `librosa`,
5. backend returns:
   - original filename,
   - estimated tempo,
   - duration,
   - generated events,
   - event count.

### Current analysis parameters
- audio is loaded mono,
- sample rate is resampled to `22050 Hz`,
- beat tracking is based on onset strength,
- RMS energy is also computed.

### Current extracted features
- onset strength envelope
- beat frames / beat times
- RMS energy
- z-score normalized RMS
- z-score normalized onset

### Current section classifier
For each beat:
- `score = 0.65 * rms + 0.35 * onset`

Classification:
- `score > 1.1` → `high`
- `score > 0.2` → `mid`
- else → `low`

### Current event-generation rules
The backend currently builds a Kame32-style event stream as follows:

#### Common initialization
Always prepend:
- `Start` button at `t = 0.00`
- neutral joystick `[0, 0]` at `t = 0.15`

#### Strong-bar rule
If:
- beat is at bar position `0`,
- combined RMS + onset is above the 90th percentile,
- and a large move has not happened very recently,

then:
- use `Y` if section is `high`,
- otherwise use `X`,
- then schedule a joystick stop shortly after.

#### Accent jump rule
If:
- onset is above the 80th percentile,
- gap is long enough,
- bar position is `2` or `6`,
- and a large move has not happened very recently,

then:
- schedule `B`,
- then schedule a joystick stop.

#### High section motion
Use larger joystick swings and a counter-sway stop:
- x alternates left/right,
- y nudges slightly forward/back,
- additional stop points are inserted.

#### Mid section motion
Use medium joystick swings and moderate forward push.

#### Low section motion
Use smaller sways and gentler movement.

#### Occasional phrase ending accent
At bar position `7`, on non-low sections, with a random chance:
- use `Z` for `mid`,
- use `X` for `high`.

#### Common finalization
Always append:
- joystick `[0, 0]` at `duration + 0.10`
- `Stop` button at `duration + 0.20`

#### Event compaction
Near-duplicate joystick entries are removed if the same payload repeats within `0.15s`.

## Audio playback in the browser

### Current audio preview behavior
- uploaded audio is loaded into a browser `<audio>` element using an object URL,
- the browser audio player is shown after a file is selected,
- once analysis succeeds, the event timeline is auto-loaded,
- the app switches into Event timeline mode,
- the browser audio clock becomes the transport source.

### Why audio-sync mode matters
In audio-sync mode:
- `state.time` comes from `audio.currentTime`,
- movement timing follows the media clock,
- seeking the transport seeks the audio,
- pausing the audio pauses the motion preview.

This is better than trying to run separate clocks for motion and sound.

## Playback-speed requirements implemented

### Requested behavior
The user requested:
- music playback at 50% speed,
- music playback at 25% speed,
- and matching movement playback at the same slowed rate.

### Implemented behavior
The app now supports:
- `100%` speed preset
- `50%` speed preset
- `25%` speed preset
- plus a numeric custom speed field from `0.25` to `3.0`

### Audio-sync implementation
When audio is active:
- the app sets the audio element's `playbackRate`,
- the preview transport follows `audio.currentTime`,
- therefore the visible movement slows down exactly with the music.

### Non-audio implementation
When audio is not active:
- the preview increments the internal transport by:
  - `delta_seconds * playback_speed`

This gives comparable slow-motion review for:
- joystick mode
- button mode
- pose mode
- event mode without audio
- keyframe mode

### UI behavior
The app now exposes:
- a numeric playback speed field,
- dedicated preset buttons for `100%`, `50%`, and `25%`,
- active-button highlighting for the currently selected preset.

## JSON data contracts

### Event timeline contract
The app currently accepts arrays of objects containing:
- `t` number, seconds
- `kind` string
- `payload` depending on kind

Examples:
```json
[
  {"t": 0.0, "kind": "button", "payload": "Start"},
  {"t": 0.2, "kind": "joystick", "payload": [0, 70]},
  {"t": 1.4, "kind": "button", "payload": "X"},
  {"t": 3.0, "kind": "joystick", "payload": [0, 0]}
]
```

### Pose event contract
Accepted inside event timelines:
```json
{"t": 2.5, "kind": "pose", "pose": {"s0": 90, "s1": 90, "s2": 80, "s3": 100, "s4": 90, "s5": 90, "s6": 100, "s7": 80}}
```

### Keyframe contract
```json
[
  {"t": 0.0, "pose": {"s0": 90, "s1": 90, "s2": 80, "s3": 100, "s4": 90, "s5": 90, "s6": 100, "s7": 80}},
  {"t": 0.7, "pose": {"s0": 110, "s1": 70, "s2": 75, "s3": 105, "s4": 70, "s5": 110, "s6": 105, "s7": 75}}
]
```

## Known limitations

1. The 3D viewer is a stylized approximation, not exact robot geometry.
2. Button routines are approximated by hand-authored preview motions, not decoded from firmware internals.
3. The MP3 analysis produces **event timelines**, not true physically optimized choreography.
4. There is no direct "send to robot" route in the current Flask app.
5. There is no raw `/pose` or `/servo` Wi-Fi endpoint in the known stock firmware.
6. The frontend currently uses Three.js from a CDN, so internet access is needed unless those assets are vendored locally.
7. The preview assumes a practical hip/knee mapping that may need adjustment for some physical builds.

## Existing artifacts created so far

### Standalone Wi-Fi dance script
A separate Python script was previously created to:
- analyze an MP3,
- generate a dance event stream,
- and send `/joystick` and `/button` requests directly to the robot.

That script is useful for live robot playback.

### Flask preview app
The Flask preview app is useful for:
- visual debugging,
- trying JSON timelines,
- and auditioning music-synced motion before sending anything to hardware.

## Recommended next steps

1. Add a "Send to Kame32" backend proxy so the same app can preview and then drive `http://192.168.4.1`.
2. Add export formats:
   - event timeline JSON
   - keyframe JSON
   - standalone Python control script
3. Add richer button-routine approximation or replace those with captured keyframes from the real robot.
4. Add direct servo-pose routes if the firmware is extended with `/pose` or `/routine`.
5. Add beat markers and event markers in the transport UI.
6. Add save/load projects containing:
   - audio metadata
   - event timeline
   - keyframes
   - chosen speed
   - mode
7. Replace the stylized mesh with a Kame32-shaped CAD-derived model.

## Source basis for this specification

This spec is based on:
- the current conversation and user constraints,
- the stock Kame32 `gamepad.cpp` behavior previously inspected,
- the generated standalone MP3 dance script,
- and the current Flask preview app codebase in this workspace.
