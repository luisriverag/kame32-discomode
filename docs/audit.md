# Audit and validation

Last consolidated: 2026-11-09. Scope: Flask validation, uploads, robot dispatch, browser preview/recording, MCP, firmware compatibility, and Docker. This report describes implemented protections and observed checks; physical acceptance and a dependency vulnerability scan have not been performed.

## Implemented protections

| Finding | Current behavior | Validation |
| --- | --- | --- |
| Timeout ignored playback speed and left work running | Deadline is normalized duration / speed + 15 seconds; timeout signals cooperative cancellation. Interruptible waits and bounded HTTP calls let the worker exit and attempt neutral/Stop. | Deadline, cancellation, stop attempts, and slot retention regression tests |
| Start/Stop anywhere suppressed safe boundaries | Stock timelines enforce initial Start/neutral and terminal neutral/Stop; pose streams enforce Start/Stop without gait-home commands. Original and normalized events are validated. | Misplaced Start/Stop regression; original input remains unchanged |
| Arbitrary server-side destinations and redirects | Live sends require an exact configured origin; default is `http://192.168.4.1`. Redirects rejected; URL credentials, paths, queries, fragments rejected. | Configured/unconfigured destinations and redirect policy tests |
| Unbounded dispatch queue | One active dispatch per process; concurrent sends return `409 robot_busy`. Slot retained through cancellation cleanup. | Busy and timeout regression tests |
| Unbounded joystick values | Integer coordinates in `[-100, 100]`; fractional values, booleans, strings, and non-finite values rejected. | Range/type boundary tests |
| Malformed JSON caused HTML 500 responses | Top-level object, URL type/syntax, and strict dry-run boolean validated with structured 400 responses. Unsorted timelines rejected. | Malformed-request and unsorted-input tests |
| Raw dispatch exceptions exposed internals | Unexpected errors omit details; network details are sanitized. Full errors remain available in server logs. | Exception and network redaction tests |

Audio analysis now runs in a disposable Linux process with one admitted job, CPU/address-space/wall-time limits, bounded decoding, and process-group cleanup. See [API budgets](api.md#audio-analysis-budgets). Native analysis failures cannot terminate the Flask process, but resource isolation does not guarantee real-time scheduling.

Exact pose playback probes firmware before motion and requires pose/watchdog/lease-token support. Stock compatibility replays a saved native track; it does not approximate servo poses. The companion firmware implements a separate routine worker and independent FreeRTOS PWM-disarm watchdog. See [firmware](firmware.md).

## Validation evidence

| Check | Recorded outcome |
| --- | --- |
| Latest Docker backend suite | 55 tests passed, including real stdio MCP integration and isolated audio |
| Real MP3 during concurrent requests | Analysis succeeded, another upload received 429, robot status responded in 25 ms |
| Browser smoke checks | Local-static 3D startup, recording, persistence, playback, DanceMode transfer, deletion, and stock-mode validation passed |
| MCP | Stdio and Streamable HTTP initialization, tools/resources/prompts, browser acknowledgments, and explicit backend-host trust checks passed |
| Docker | Non-root UID 10001, health checks, dependency consistency, restart/recreation, and persisted frames/native tracks passed |
| Firmware | Both ESP32 gamepad/calibration targets compiled; native lease boundary/late-heartbeat/wrap-around tests passed |
| Patch reproducibility | Applied to a pristine archive of pinned upstream; files matched built sources |
| Live hardware / firmware flashing | Not performed |
| Vulnerability database scan | Not performed; pip check is not a vulnerability scan |

The 25 ms result is one smoke observation, not a latency guarantee. The suite count is a recorded baseline, not a claim that all future builds pass or that frontend/hardware coverage is complete. Tests use mocks or local simulated firmware endpoints for hardware dispatch.

## Remaining limitations and priorities

1. **Physical acceptance:** calibrate servos and measure cancellation/watchdog behavior on the robot. Stock firmware has no independent disconnect stop. Updated firmware disables PWM, which can remove holding torque and let the robot sag.
2. **Remote access:** app/MCP have no authentication, authorization, or remote OAuth. Docker publishes on host loopback. Add authenticated TLS access before remote exposure; origin allowlists and lease tokens are not user authentication.
3. **Independent backups:** implement move export/import and scheduled, tested backups. SQLite and named volumes persist data across recreation but do not protect against deletion or host loss.
4. **Shared coordination:** dispatch admission, cancellation, audio admission, browser clients, and command history are process-local. Keep one app worker/container; scaling needs shared coordination.
5. **Network semantics:** cancellation is best effort. Stock HTTP routines can block up to the eight-second client allowance. Host allowlists do not pin DNS, and browser command acknowledgments can be uncertain on disconnect.
6. **Dependencies and coverage:** Docker Python packages are pinned; base image/OS packages are not digest/version locked. Vulnerability scanning and full frontend interaction coverage remain follow-up work.

## Operational notes

Use a writable dedicated Numba cache; initial onboarding encountered a package-local native-cache crash whose exact cause remains unproven. Docker configures a dedicated cache automatically. Restart testing also identified a shared-network-namespace race; the final Compose deployment uses normal service networking and an explicitly trusted app hostname.

Cloud environment publication is separate from Git pushes and Docker rollout. The user reported publishing the initial environment; later code/documentation updates do not automatically publish a new cloud version.

[Documentation index](README.md) · [Development](development.md) · [Docker](docker.md)
