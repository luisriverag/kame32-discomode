# Recorded moves and the robot watchdog

TeachMoves can stream its recorded servo keyframes to an upgraded Kame32. The stock firmware has only joystick/button endpoints and cannot reproduce arbitrary poses. The app never approximates those keyframes as joystick commands.

## Firmware source and reproducible patch

Upstream: https://github.com/javierih/kame32, base commit `8f33e489f7425747ab62aeb509777a06d2f14f3e`.

The modified checkout for this task is `/workspace/kame32-firmware`. The portable patch is [firmware/kame32-pose-watchdog.patch](firmware/kame32-pose-watchdog.patch); upstream licensing/attribution is retained in that directory. Apply it to a fresh checkout at the pinned base:

```bash
git clone https://github.com/javierih/kame32.git kame32-firmware
cd kame32-firmware
git checkout 8f33e489f7425747ab62aeb509777a06d2f14f3e
git apply --check /path/to/kame32-discomode/firmware/kame32-pose-watchdog.patch
git apply /path/to/kame32-discomode/firmware/kame32-pose-watchdog.patch
```

Use a separate Python environment for PlatformIO. In this cloud workspace, PlatformIO is installed at `/workspace/.venvs/kame-firmware/bin/pio`:

```bash
cd /workspace/kame32-firmware/code
PLATFORMIO_CORE_DIR=/workspace/.platformio /workspace/.venvs/kame-firmware/bin/pio run -e gamepad -e calibration -j 2
```

Both targets use the existing pinned ESP32 platform 6.13.0 and Arduino framework. Calibration remains a separate image; the new HTTP/watchdog features are in **gamepad**. Flashing requires a connected ESP32 and the correct serial port. The following is an example command, not a step executed during this task:

```bash
pio run -e gamepad --target upload --upload-port /dev/ttyUSB0
```

No firmware was uploaded to a physical robot during development.

## Use from TeachMoves or MCP

Run Flask on a machine that can reach the robot's Wi-Fi/LAN origin. Configure `KAME32_ROBOT_ORIGINS` if it differs from `http://192.168.4.1`. A cloud machine cannot reach a laptop's local robot AP without an appropriate network connection/tunnel.

1. Record a move and stop recording to save it.
2. Select its slot and choose **Validate for robot**. This is an offline dry run; it does not contact or move hardware.
3. After installing the upgraded firmware and checking calibration, choose **Send move to robot**. This is an explicit live operation.
4. **Cancel robot playback** requests cancellation of the app's active job. Closing the browser tab does not cancel a job already running on the Flask server.

MCP equivalents are `validate_move(name)` and `dispatch_move(name, base_url, send_speed)`. `cancel_robot_dispatch` cancels the active app job. Record/preview actions remain local; no recording automatically sends motion.

The app checks `/capabilities` before starting a pose timeline. With Exact pose mode (or a pose-only recording), missing pose/watchdog/lease-token support produces `400 robot_firmware_required` before any motion commands. In Auto mode, a saved native joystick/button track is used when available; explicit Stock compatibility mode always uses that track. Legacy joystick/button event timelines remain supported on stock firmware (404 for capabilities). Connection failures and rejected redirects do not downgrade into a pose approximation. A missing/non-JSON capability endpoint is treated as legacy; Auto can then use only a saved stock command track.

## Device behavior and protocol

- `/capabilities` advertises `pose`, `watchdog`, `lease_token`, protocol 1, and a 1500 ms lease.
- `/button?label=Start&lease=<token>&mode=pose` explicitly arms pose playback. `mode=pose` prevents the gait loop from moving to its home position before the first pose.
- `/pose?s0=...&...&s7=...&lease=<token>` accepts all eight finite angles in `[0,180]`, validates the complete request before applying it, and holds that pose.
- `/heartbeat?lease=<token>` refreshes an active lease. The app sends heartbeats during timeline gaps, approximately every 250 ms.
- Joystick/button commands also refresh their owner's lease. A different controller's heartbeats cannot keep the active owner's motion alive. Stop is accepted regardless of owner.
- An independent FreeRTOS watchdog task checks expiry every 10 ms and disables servo PWM after 1500 ms without a valid refresh, plus scheduling/driver latency. Late heartbeats cannot re-arm an expired lease. Only an explicit Start can arm again.
- Button routines run in a separate worker so HTTP/heartbeat processing remains available. New motion commands interrupt the old routine before taking over. Servo output/disarm are synchronized, and long routines/pauses observe disarm.
- Pose streams preserve their final pose until Stop; they do not insert joystick-neutral/home commands that would jerk the robot into a different pose. Stop disables PWM rather than commanding a new posture.

This is a control watchdog, not a certified emergency stop. PWM disable can remove holding torque and allow the robot to sag. It does not cut battery power, protect against all MCU/driver failures, or replace a physical power switch. Lease tokens distinguish controllers; they are not authentication.

## Validation and physical acceptance

Verified: both ESP32 firmware targets compile; native lease tests cover timeout boundaries, explicit re-arming, late heartbeat rejection and `millis()` wrap-around. App tests exercise real HTTP against a simulated firmware endpoint, pose validation, heartbeat/token propagation, rejection of stock firmware before motion, and dry-run defaults. Browser smoke checks verify saved-slot selection and dry-run controls.

Still required on actual hardware, with the robot supported and servo calibration/mechanical limits checked:

- Confirm a benign pose is held, then Stop disables all eight PWM outputs.
- Remove the active controller's connection during motion and measure PWM disable near the lease deadline.
- Repeat during a long button routine and a stalled HTTP connection; expiry must not depend on the HTTP task returning.
- Confirm late/foreign heartbeats do not restart motion or extend another controller's lease.
- Confirm a new explicit Start is required after timeout, and exercise cancel/restart behavior.

No physical timing, servo movement, USB flashing, or Wi-Fi robot connectivity was validated here.

## Non-updated firmware compatibility

TeachMoves also records native joystick/button commands when the entire recording uses those controls, default gait parameters, 100% speed, and uninterrupted preview playback. Choose Stock compatibility to replay that track; Auto prefers upgraded pose firmware and otherwise falls back to the track. Pause, custom gait settings, or manual servo poses make the recording pose-only. Existing pose-only slots remain usable in preview but cannot be approximated for stock hardware.

The original blocking HTTP button handlers can delay later commands and cancellation. Stock button calls allow up to eight seconds for known routines; no disconnect watchdog can be added from the client side. The watchdog and precise servo playback still require the firmware update.
