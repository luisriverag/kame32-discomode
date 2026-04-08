
# Kame32 3D Preview

A small Flask web app that previews Kame32 movements in 3D.

## Features

- Live joystick gait preview based on the current stock Kame32 gamepad firmware parameters
- Button-routine previews for A / B / X / Y / Z
- Manual 8-servo pose editing
- Event timeline JSON import
- Keyframe JSON import with interpolation
- MP3/audio upload that analyzes beats and auto-builds a dance event timeline for preview
- Guided **Quick workflow** card for **Load MP3 → Visualize → Send to robot**
- Dedicated **Visualize analyzed dance** action to jump into event-timeline preview mode
- Optional browser audio playback synced to the preview timeline
- Quick playback presets for 100%, 50%, and 25% speed, with music and move timing slowed together in audio-sync mode
- **Copy script for robot** button that copies the current event JSON to clipboard for use in your uploader/sender tool

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000

## MP3 workflow (recommended)

1. Open the app in your browser.
2. In **Load MP3 and auto-build dance**, pick an MP3.
3. Click **Analyze audio into dance**.
4. The server extracts beats with `librosa` and generates a Kame32-style event timeline.
5. Click **Visualize analyzed dance** (or press **Play**, which auto-activates analyzed events) to ensure source mode is **Event timeline JSON**.
6. Press **Play** to preview in 3D with browser audio as the timeline clock.
7. Use **100% / 50% / 25%** to audition in slow motion (music and movement stay aligned in audio-sync mode).
8. Click **Copy script for robot** in the Event timeline panel, then paste into your robot sender/uploader flow.

## JSON formats

### Event timeline

```json
[
  {"t": 0.0, "kind": "button", "payload": "Start"},
  {"t": 0.2, "kind": "joystick", "payload": [0, 70]},
  {"t": 1.4, "kind": "button", "payload": "X"},
  {"t": 3.0, "kind": "joystick", "payload": [0, 0]}
]
```

### Keyframes

```json
[
  {"t": 0.0, "pose": {"s0": 90, "s1": 90, "s2": 80, "s3": 100, "s4": 90, "s5": 90, "s6": 100, "s7": 80}},
  {"t": 0.7, "pose": {"s0": 110, "s1": 70, "s2": 75, "s3": 105, "s4": 70, "s5": 110, "s6": 105, "s7": 75}}
]
```

## Notes

- The joystick gait uses the same period, leg spread, body height, step height, and phase arrays as the current Kame32 stock gamepad firmware.
- The button routines are visual approximations for previewing style and timing.
- The MP3/audio analysis produces a Kame32-style event timeline, not inverse-kinematics choreography.
- This app does not directly upload commands to the robot; it previews and exports timeline JSON.
- The app uses a CDN import for Three.js, so internet access is needed unless you vendor those files locally.


## Playback speed behavior

- The numeric **Playback speed** field still accepts custom values from `0.25` to `3.0`.
- The preset buttons provide one-click **100%**, **50%**, and **25%** playback.
- In audio-sync mode, the app sets the browser audio element's `playbackRate` and uses the audio clock as the transport, so the music and the move timeline stay aligned while slowed down.
- In non-audio modes, the preview timeline itself advances at the selected speed.
