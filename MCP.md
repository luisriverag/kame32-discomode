# MCP integration

The MCP server exposes DanceMode and TeachMoves through the official Python MCP SDK. Flask remains the single application backend: MCP calls the running app over loopback rather than creating a second robot executor. Both stdio and Streamable HTTP are supported.

## Install and run

From the repository directory, activate your Python environment and install the optional MCP dependencies:

```bash
python -m pip install -r requirements-mcp.txt
export NUMBA_CACHE_DIR=/workspace/.cache/kame32-numba
python app.py
```

Keep Flask running. In a second terminal, launch the MCP server:

```bash
python mcp_server.py
# Or an HTTP MCP endpoint on loopback port 8000 at /mcp:
python mcp_server.py --transport streamable-http
```

The stdio process is normally launched by the MCP client, not by a separate terminal. It writes protocol messages to stdout and logs to stderr. Starting the MCP server does not send robot commands.

Example client configuration (replace paths with your checkout and interpreter):

```json
{
  "mcpServers": {
    "kame32": {
      "command": "/workspace/.venvs/kame32-discomode/bin/python",
      "args": ["/workspace/kame32-discomode/mcp_server.py"],
      "env": {
        "KAME32_APP_URL": "http://127.0.0.1:5000",
        "KAME32_AUDIO_DIR": "/workspace/kame32-discomode"
      }
    }
  }
}
```

`KAME32_APP_URL` must be a loopback HTTP(S) origin by default; an administrator can explicitly allow a private app hostname with `KAME32_TRUSTED_APP_HOSTS` (comma-separated exact hostnames). Compose sets this to `app` for service networking; default is `http://127.0.0.1:5000`. `KAME32_AUDIO_DIR` defaults to the checkout and limits which local files `analyze_audio` can read, including resolved symlinks. Audio files are limited to 49 MiB to allow multipart overhead under Flask's 50 MiB request cap.

Both servers bind to loopback. There is no authentication layer: keep them restricted to trusted local clients and do not expose the HTTP endpoint publicly. For a remote MCP client, use an authenticated deployment or tunnel managed outside this app. This implementation does not include remote OAuth.

## Tools

| Tool | Behavior |
| --- | --- |
| `get_status` | App connectivity, connected tabs with recent preview state, and feature limits |
| `get_presets` | Built-in event and keyframe routines |
| `analyze_audio` | Analyze a file under the configured audio directory; returns events without dispatch |
| `validate_timeline` | Backend validation and safety-boundary checks in dry-run mode |
| `dispatch_robot` | **Live hardware motion**, using the app's configured origins and dispatch slot |
| `validate_move`, `dispatch_move` | Dry-run or explicitly stream a saved servo move; live playback requires the upgraded firmware |
| `cancel_robot_dispatch` | Request cancellation of the active app timeline; worker attempts neutral/Stop |
| `list_moves`, `get_move` | Read shared recordings |
| `save_move`, `delete_move` | Replace or delete Move1–Move6; server validates keyframes |
| `control_browser` | Queue a preview or teaching action for a specific connected tab |
| `get_browser_command` | Inspect its completed, failed, queued, delivered, or expired outcome |

Tools that can replace data or move hardware carry destructive-operation annotations. Annotations are client hints, not authorization enforcement. Live dispatch is a separate explicit tool and never happens through browser control. Validate timelines first; do not automatically retry a live dispatch after a timeout or uncertain response. `cancel_robot_dispatch` signals the active worker; inspect `get_status.robot` until inactive. It cannot guarantee stop delivery or stop motion started outside this app.

### Browser controls

Open DanceMode or TeachMoves in a browser on the same Flask instance. Tabs register automatically while the JavaScript module is running. `get_status` returns their `client_id`, page, last reported pose/mode/transport state, and heartbeat age. Clients without a heartbeat for 10 seconds disappear until they reconnect.

Call `control_browser(client_id, action, arguments)` with:

| Action | Arguments |
| --- | --- |
| `get_state` | `{}`; completed result includes the full event timeline and keyframes |
| `set_mode` | `{"mode":"joystick"}` (also button, pose, events, keyframes) |
| `set_pose` | `{"pose":{"s0":90,"s1":90,"s2":90,"s3":90,"s4":90,"s5":90,"s6":90,"s7":90}}` |
| `set_joystick` | `{"x":0,"y":70}`; each coordinate from -100 to 100 |
| `button` | `{"label":"X"}`; A, B, C, X, Y, Z, Stop |
| `load_events` | `{"events":[...]}`; backend-valid event timeline |
| `load_move` | `{"name":"Move1"}`; loads shared keyframes, paused |
| `play`, `pause`, `reset` | `{}` |
| `select_move` | `{"name":"Move1"}`; TeachMoves only |
| `record`, `stop_recording` | `{}`; TeachMoves only, selected slot |

A returned command ID means **queued**, not completed. Poll `get_browser_command` until a terminal status. Invalid action arguments are reported as failed by the browser. Commands are delivered once and expire after 30 seconds without acknowledgment. Disconnects can leave an uncertain result; inspect browser state before retrying changes. History lasts five minutes and does not survive app restart. There are at most 32 registered tabs, 64 outstanding commands, and 512 retained commands.

Example teaching sequence: get_status → select_move → set_pose → record → set_pose → stop_recording → get_move → load_move → play. Verify each acknowledgment before proceeding. Recording is capped at 60 seconds; Stop saves the selected slot to the server. Recorded keyframes can be sent explicitly with `dispatch_move` after installing the pose/watchdog firmware. Stock firmware is rejected before pose motion. See FIRMWARE.md for the reproducible patch and physical acceptance checks.

## Storage, resources, and prompts

Moves are stored in SQLite at `instance/moves.sqlite3` (ignored by Git). Override with `KAME32_MOVES_DB`. UI recordings and MCP tools share these six slots. Existing browser-local recordings are imported once into empty server slots; existing shared slots are not replaced during migration. Concurrent edits use the last completed write. Back up the database to preserve moves independently of the environment snapshot.

Resources: `kame32://status`, `kame32://presets`, and the template `kame32://moves/{name}`. The `teach_move(goal)` prompt guides an AI through a preview teaching session without dispatching hardware.

Run validation with the MCP dependencies installed:

```bash
python -m unittest discover -s tests -v
```

`tests/test_mcp.py` launches a real stdio MCP subprocess against an ephemeral Flask instance and tests discovery, resources, prompts, move operations, validation failures, and dry-run behavior. It is skipped if optional MCP dependencies are absent. Hardware dispatch is mocked in backend tests; no physical robot is required.

## Compatibility and Docker

`save_move` accepts optional `events` containing recorded stock joystick/button commands. `validate_move` and `dispatch_move` accept `playback_mode`: `auto` (prefer upgraded poses, fall back to saved commands), `stock` (requires commands), or `pose` (requires upgraded firmware). Stock playback has no on-device watchdog and may drift while its HTTP routines block. Manual poses are never approximated into stock commands.

The Docker stack runs the app and Streamable HTTP MCP together. See DOCKER.md for persistent volumes, loopback ports, and the stdio `docker compose exec -T` option.
