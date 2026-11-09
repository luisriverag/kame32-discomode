# Audit and remediation — 2026-11-09

## Scope

Reviewed backend uploads, robot dispatch, frontend module loading, and documentation. Follow-up changes address dispatch and validation findings. Physical robot tests and dependency vulnerability scanning were not performed.

Current validation: all **55 tests passed inside Docker**, including isolated audio processing, dispatch safety, saved-move compatibility, and real MCP protocol checks. Separate browser/HTTP checks verified recording, stock-mode validation, MCP connectivity, persistence across container recreation and restart, and a real MP3 analysis with concurrent upload rejection. Robot status responded in 25 ms during that analysis; this is an observed smoke result, not a latency guarantee. Both containers were healthy after rollout.

## Addressed findings

| Finding | Current behavior | Validation |
| --- | --- | --- |
| Timeout ignored playback speed and left work running | Deadline is normalized duration / speed + 15 seconds; timeout signals cooperative cancellation. Interruptible waits and bounded HTTP calls let the worker exit and attempt neutral/Stop. | Deadline, cancellation, stop attempts, and slot retention regression tests |
| Start/Stop anywhere suppressed safe boundaries | Stock timelines enforce initial Start/neutral and terminal neutral/Stop; pose streams enforce Start/Stop without gait-home commands. Original and normalized events are validated. | Misplaced Start/Stop regression; original input remains unchanged |
| Arbitrary server-side destinations and redirects | Live sends require an exact configured origin; default is `http://192.168.4.1`. Redirects rejected; URL credentials, paths, queries, fragments rejected. | Configured/unconfigured destinations and redirect policy tests |
| Unbounded dispatch queue | One active dispatch per process; concurrent sends return `409 robot_busy`. Slot retained through cancellation cleanup. | Busy and timeout regression tests |
| Unbounded joystick values | Integer coordinates in `[-100, 100]`; fractional values, booleans, strings, and non-finite values rejected. | Range/type boundary tests |
| Malformed JSON caused HTML 500 responses | Top-level object, URL type/syntax, and strict dry-run boolean validated with structured 400 responses. Unsorted timelines rejected. | Malformed-request and unsorted-input tests |
| Raw dispatch exceptions exposed internals | Unexpected errors omit details; network details are sanitized. Full errors remain available in server logs. | Exception and network redaction tests |

## Remaining limitations

- **Authentication:** no authentication or authorization layer. Keep the default loopback bind and restrict access to trusted users. An origin allowlist does not authenticate callers.
- **Hardware stopping:** best-effort HTTP neutral/Stop cannot guarantee delivery during network loss. A watchdog is implemented in the companion firmware patch; it still requires flashing and physical acceptance testing. Stock compatibility mode has no on-device disconnect watchdog. Cancellation may wait for an in-flight request (stock routines allow up to eight seconds) and cleanup calls. Pose cleanup sends Stop without a gait-home command.
- **Multiple processes:** the dispatch slot is process-local. Use a single app process for robot control; a multi-worker deployment requires shared coordination.
- **Configured hosts:** administrators must configure trusted robot origins. A permitted hostname's DNS resolution remains deployment-controlled; this is not DNS pinning.
- **Audio resource use:** API analysis now runs in a disposable Linux subprocess with one admitted job, a 120-second CPU budget, 4 GiB address-space ceiling, 180-second wall deadline, and 599-second decoded-duration limit. Timeout kills the process group. These are containment limits, not a real-time scheduling guarantee.
- **Dependencies:** no vulnerability database scan was run. `pip check` establishes dependency compatibility only; Docker Python dependencies are pinned in requirements-docker.lock; the base image and OS packages are not digest/version locked.
- **Browser coverage:** onboarding confirmed local-static 3D initialization, MP3 analysis, and dry-run validation. Full browser interaction coverage and live hardware behavior remain unverified.

## Environment notes

Python 3.12 dependencies installed successfully. A default package-local Numba compilation cache caused a native crash during onboarding; a dedicated `NUMBA_CACHE_DIR=/workspace/.cache/kame32-numba` passed the original suite on initial compilation and reuse. The exact compiler/cache failure cause is unproven.

Cloud configuration draft reads and saves failed with `INVALID_ARGUMENT`; persistence was not confirmed. Fallback setup instructions remain at `/workspace/setup-instructions/`. Those failures describe the initial onboarding attempt. The user subsequently reported publishing that environment; later application changes are delivered through Git and Docker, not automatically published as a new cloud environment version.

## MCP follow-up validation

The optional MCP adapter supports stdio and loopback Streamable HTTP, with resources, a teaching prompt, shared SQLite move storage, bounded acknowledged browser commands, and explicit live-dispatch/cancellation tools. All 39 tests passed with MCP dependencies installed, including a real stdio client/server round trip and audio analysis. Streamable HTTP initialization and a full MCP-to-browser recording/playback flow passed separate smoke checks. No physical robot commands were sent.

MCP and its supporting APIs have no authentication layer and must remain restricted to trusted local clients. Browser command acknowledgments establish preview execution only. Cancellation remains best effort for hardware stopping; queued command delivery can become uncertain on disconnect. See MCP.md for operational limits.

## Compatibility, firmware, and Docker validation

TeachMoves now saves native joystick/button tracks for stock compatibility, alongside exact pose frames. Auto chooses upgraded pose firmware when supported and otherwise uses the saved native track; manual pose-only recordings are refused in stock mode. There is no servo-to-joystick approximation. Stock blocking routines and missing disconnect protection remain firmware limitations.

The companion firmware patch adds pose streaming, controller-scoped leases, a separate routine worker, and an independent FreeRTOS PWM-disarm watchdog. Both ESP32 gamepad/calibration targets compiled. Native lease boundary/wrap-around tests passed, and the portable patch was applied to a pristine pinned upstream archive and compared with the built sources. Physical flashing/timing/motion remain untested.

All 52 app tests passed on the host and inside the Docker image. Browser recording/compatibility checks, non-root UID, MCP port/tool discovery, dependency consistency, persisted frames/native tracks across container recreation, and a clean stack restart passed. Restart testing identified a namespace-sharing race; the final Compose design uses normal service networking with an explicitly trusted app hostname. Targeted MCP tests and host-trust checks passed on that final design. Both containers are healthy. Generated test recordings were removed. See DOCKER.md and FIRMWARE.md for operation and remaining hardware acceptance work.

## Outstanding priorities

- Perform physical servo calibration, cancellation, and watchdog acceptance checks using FIRMWARE.md. Stock firmware has no independent disconnect watchdog.
- Add authentication and TLS before exposing the app/MCP beyond trusted local access; current Docker ports bind to host loopback.
- Add move export/import and scheduled, tested database backups. SQLite/Docker volume persistence does not protect against volume deletion or host loss.

The audio containment work is implemented: a separate Linux worker, one admitted job, CPU/address-space/wall-time limits, bounded decoded duration, and process-group cleanup. Physical safety and hard real-time behavior remain separate concerns.
