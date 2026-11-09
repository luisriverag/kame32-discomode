# User guide

First [start Docker](docker.md) or [run from source](development.md). The app has two pages linked in its navigation. The preview is an approximation of the robot's motion, not a calibrated physical simulation.

## DanceMode

1. Choose an audio file (`mp3`, `wav`, `ogg`, `m4a`, or `flac`). Selecting it starts analysis; **Analyze audio into dance** can run it again.
2. Inspect the generated Event timeline JSON. Edit it or load a demo if needed.
3. Use Play, Pause, Reset, seeking, and speed controls to preview. With audio synchronization active, the media clock drives the timeline.
4. To operate hardware, configure a reachable allowed robot origin and explicitly choose **Send timeline to robot**. Preview playback speed and hardware send speed are separate settings.

Audio requests have [upload, duration, CPU, memory, and time budgets](api.md#audio-analysis-budgets). One analysis can run per app process; a busy response means retry after the current job finishes.

## TeachMoves

1. Choose a slot, Move1 through Move6.
2. Select a manual source: joystick gait, button routine, or servo pose.
3. Click Record, adjust controls, then Stop recording. Recordings last at most 60 seconds. Stop before navigating away to save.
4. Select a saved slot to Play, Re-record, Delete, or **Use in DanceMode**. Transfer loads its keyframes paused.

Saved slots live in the server's SQLite database and are shared with MCP clients. Re-recording replaces the slot when saved. Existing browser-local recordings import once into empty shared slots. Concurrent edits use the last completed write; there is no version history or undo.

## Choose hardware playback

| Mode | Behavior |
| --- | --- |
| Auto | Checks capabilities; uses exact pose frames on supported firmware, otherwise the recording's saved stock commands |
| Compatibility: stock firmware | Uses the native joystick/button track, even when updated firmware is available |
| Exact servo poses: updated firmware | Requires pose, watchdog, and controller-lease support; refuses unsupported devices before motion |

For stock compatibility, record only joystick/button controls, with default gait settings and 100% speed, while preview playback stays active. Manual poses, custom gait parameters, pauses, or non-unit speed make a recording pose-only. Old pose-only recordings must be re-recorded with supported controls or used with updated firmware. The app never guesses joystick commands from servo poses.

**Validate for robot** is an offline dry run. It does not probe firmware or move the robot. **Send move to robot** is live. **Cancel robot playback** requests cancellation of the current app job; it is not an acknowledgment from the robot. Closing a tab does not cancel a job already running on the server.

Stock button routines can block HTTP handling and delay subsequent commands or cancellation. Stock firmware cannot stop independently after connection loss. The [optional firmware update](firmware.md) adds pose streaming and a watchdog; physical acceptance remains required.

## Storage and troubleshooting

Docker's `moves` volume retains recordings across recreation. Do not use `docker compose down -v` unless deleting saved data is intentional. Volume persistence does not protect against host loss; independent backups remain follow-up work.

- **3D unavailable:** local Three.js is bundled. See [3D troubleshooting](development.md#3d-preview).
- **Robot destination rejected:** configure `KAME32_ROBOT_ORIGINS` on the app process/container; setting a UI address alone does not add it to the allowlist.
- **No stock commands:** re-record using supported controls and default settings, or use updated firmware.
- **Robot busy:** wait for the active dispatch/cleanup to finish. Cancellation retains the slot until the worker exits.
- **No MCP browser client:** open the relevant page and ensure its JavaScript is running. Browser registrations and commands are temporary; see [MCP](mcp.md).
