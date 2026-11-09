# HTTP API and limits

The API is unauthenticated and intended for trusted local access. Requests below use the running app origin. Browser preview controls and dry runs do not operate hardware; live dispatch does.

## Routes

| Method / path | Behavior |
| --- | --- |
| `GET /`, `GET /teach-moves` | DanceMode and TeachMoves pages |
| `GET /api/presets` | Built-in event and keyframe routines |
| `POST /api/analyze-audio` | Multipart upload under field `audio`; returns filename, tempo, duration, events, event_count |
| `GET /api/moves` | Object mapping saved slot names to frame arrays |
| `GET /api/moves/<name>` | Move frames, optional stock events, and stock_compatible flag |
| `PUT /api/moves/<name>` | Replace `{frames, events?}`; omitted/null events clears the stock track |
| `DELETE /api/moves/<name>` | Delete the slot and its command track |
| `POST /api/moves/<name>/send` | Saved-move validation or dispatch; **defaults to dry-run** |
| `POST /api/send-to-robot` | Event validation or dispatch; **defaults to live** when dry_run is omitted |
| `GET /api/robot/status` | App dispatch active/cancellation_requested state; not device telemetry |
| `POST /api/robot/cancel` | Request cancellation; returns 202 when active, 200 when no active job |

Move names are Move1–Move6. Missing saved moves return 404. Send JSON objects with `Content-Type: application/json`.

## Safe validation example

```bash
curl -sS http://127.0.0.1:5000/api/send-to-robot \
  -H 'Content-Type: application/json' \
  --data '{"dry_run":true,"events":[{"t":0,"kind":"joystick","payload":[0,40]},{"t":1,"kind":"button","payload":"Stop"}]}'
```

Always set `dry_run` explicitly. Dry-run responses describe normalized event count, timeline duration, speed, stock compatibility, and whether pose firmware is required. They do not establish device connectivity or capabilities. Live requests must use an origin allowed by the app's `KAME32_ROBOT_ORIGINS` configuration. Credentials, URL paths/queries/fragments, and redirects are rejected.

Saved-move sends accept `base_url`, `send_speed` and strict boolean `dry_run`, plus `playback_mode`: `auto` (default), `stock`, or `pose`. Auto prefers pose-capable watchdog firmware, otherwise the move's saved stock track. Stock mode rejects pose-only recordings; pose mode requires the firmware update. Live results include playback_mode and watchdog_active when available.

## Event and keyframe contracts

An event is `{"t":0.2,"kind":"joystick","payload":[0,70]}`. Supported kinds:

| Kind | Payload |
| --- | --- |
| `joystick` | Two integer coordinates in [-100,100]; no booleans, fractions, strings, or non-finite values |
| `button` | One of A, B, C, X, Y, Z, Start, Stop |
| `pose` | Object with exactly s0–s7, each a finite numeric angle in [0,180] |

Events must be a non-empty array, sorted by finite nonnegative t. Normalized timelines are limited to 5,000 events and a last timestamp of 600 seconds. Stock timelines enforce initial Start/neutral and terminal neutral/Stop. Pose timelines enforce Start/Stop without inserting gait-home commands. Generated controls count toward limits.

A keyframe is `{"t":0,"pose":{"s0":90,"s1":90,"s2":90,"s3":90,"s4":90,"s5":90,"s6":90,"s7":90}}`. Saved moves require 2–1,202 frames, sorted times, first t=0, positive duration up to 60 seconds, and all eight finite angles in [0,180]. Optional stock events must use only joystick/button and fit within that duration. Save replaces frames and commands atomically.

Send speed ranges from 0.25 to 1.0. One dispatch runs per app process; another receives `409 robot_busy`. The wait deadline is normalized duration / speed + 15 seconds. Cancellation interrupts waits and attempts cleanup; the slot remains held until the worker exits. Network calls use a 3-second timeout, except stock button routines allow 8 seconds. Updated firmware provides a separate device watchdog; stock cancellation can be delayed by blocking firmware handlers.

## Audio analysis budgets

| Limit | Value |
| --- | --- |
| Total request size | 50 MiB |
| Supported upload suffixes | mp3, wav, ogg, m4a, flac |
| Concurrent admitted analyses | One per app process |
| Decoded duration | At most 599 seconds; decoding reads at most 600 before rejecting |
| Worker CPU time | 120 seconds soft / 125 seconds hard |
| Worker address space | 4 GiB (not a resident-memory measurement) |
| Elapsed-time deadline | 180 seconds |

A disposable Linux worker applies resource limits before importing scientific libraries. Parent timeout/finalization kills its process group and reaps the worker. Upload cleanup runs after success and failure. Robot control uses a separate executor; these boundaries contain analysis failures but do not guarantee hard real-time behavior.

## Errors

Handled API errors use `error` with optional `code` and sanitized `details`; do not assume every infrastructure failure is JSON.

| Status / code | Meaning |
| --- | --- |
| 400 missing_audio / missing_filename | Missing upload field or filename |
| 400 unsupported_audio_format / audio_analysis_failed | Unsupported suffix, invalid file, duration/resource rejection, or failed worker |
| 413 upload_too_large | Request size exceeds 50 MiB |
| 429 audio_analysis_busy | Another analysis has admission |
| 504 audio_analysis_timeout | Worker exceeded the wall deadline |
| 400 invalid_robot_send_request | Invalid body, event data, speed, or dry-run type |
| 400 robot_destination_not_allowed | Live origin absent from allowlist |
| 400 robot_firmware_required | Unsupported pose playback or firmware requirement failure |
| 409 robot_busy / robot_dispatch_cancelled | Busy dispatch slot or cancelled job |
| 502 robot_unreachable | Robot network operation failed |
| 504 robot_dispatch_timeout | Deadline exceeded; cancellation requested |
| 500 robot_dispatch_failed | Unexpected dispatch failure |

Move and browser-control validation may return only `error`. A timeout or failure response is not proof that hardware has stopped. Do not automatically retry a live request after an uncertain outcome.

## Browser bridge

`GET/POST /api/browser-clients` lists/registers tab heartbeats. `POST /api/browser-commands` queues `{client_id, action, arguments}`; `GET` with client_id delivers queued commands once. `GET /api/browser-commands/<id>` reads status; `POST` acknowledges completed/failed with the matching client_id.

Connected tabs expire after 10 seconds without heartbeat. Commands expire after 30 seconds; history lasts five minutes and clears on app restart. Limits are 32 clients, 64 outstanding commands, and 512 retained commands. Browser actions are preview-only. See [MCP browser controls](mcp.md#browser-controls) for actions, arguments, and acknowledgment semantics.
