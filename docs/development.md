# Development

Run commands from the repository root. Linux with Python 3.12 is the validated source environment; isolated audio workers use POSIX process groups and Linux resource limits. Use [Docker](docker.md) for a consistent Linux runtime on other hosts.

## Install and start

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export NUMBA_CACHE_DIR="$PWD/.cache/numba"
python app.py
```

The development server binds to `127.0.0.1:5000`. Set `KAME32_LOG_LEVEL=DEBUG` for more logging. Debug mode is off unless explicitly enabled with `FLASK_DEBUG`; keep it off for exposed deployments. Docker uses Gunicorn rather than this development server.

For MCP, install `requirements-mcp.txt` in the same environment and follow [client setup](mcp.md). Docker's complete Python dependency set is pinned in [requirements-docker.lock](../requirements-docker.lock); the normal source manifests use a mix of exact versions and ranges.

A dedicated writable Numba cache is recommended for app and tests. During initial onboarding, the package-local compiled cache caused a native crash; a separate cache passed compilation and reuse checks. The exact cause was not established. Do not change package checksums or disable verification to work around native failures.

## Configure

| Variable | Purpose / default |
| --- | --- |
| `KAME32_ROBOT_ORIGINS` | Comma-separated exact live robot origins; `http://192.168.4.1` |
| `KAME32_MOVES_DB` | SQLite path; `instance/moves.sqlite3` in source deployment |
| `KAME32_LOG_LEVEL` | App log level; INFO |
| `FLASK_DEBUG` | Development debug toggle; off |
| `NUMBA_CACHE_DIR` | Writable scientific compilation cache |
| `KAME32_APP_URL` | MCP backend origin; `http://127.0.0.1:5000` |
| `KAME32_TRUSTED_APP_HOSTS` | Additional exact private backend hostnames for MCP; empty by default |
| `KAME32_AUDIO_DIR` | MCP readable audio directory; repository directory by default |

The MCP-specific variables belong to the adapter process. Robot origins and the database path belong to the app process. Docker overrides paths and explicitly trusts its `app` service hostname; see [deployment](docker.md).

## Validation

```bash
python -m pip install -r requirements-mcp.txt
python -m unittest discover -s tests -v
```

With optional MCP dependencies installed, the latest recorded suite completed 55 tests. Without them, the MCP integration test is skipped. Tests include bundled MP3 analysis, process admission/timeout cleanup, move storage, stock compatibility, dispatch validation/cancellation, and a real stdio MCP subprocess against an ephemeral Flask server. Live hardware dispatch is mocked or directed at a local simulated endpoint.

Useful checks after changes:

```bash
node --check static/app.js
node --check static/teach.js
node --check static/mcp-bridge.js
docker compose config --quiet
```

Node is needed only for these JavaScript checks or refreshing vendor assets; it is not a Flask runtime dependency. Full frontend coverage and physical acceptance remain separate from the backend suite.

## 3D preview

Three.js 0.164.1 and OrbitControls are already bundled under `static/vendor/three/`. The loader prefers local modules, then jsDelivr/unpkg. If unavailable, the main module uses a built-in 2D preview. If the main module itself cannot load, the HTML fallback only supports audio analysis.

Use `bash scripts/install_three_local.sh` only to refresh the bundled modules; it requires npm, modifies vendor files, and rewrites OrbitControls to use the local module path. Hard-refresh after changing failed imports. Avoid disabling browser security settings.

## Process boundaries

Keep one app process for robot control: dispatch admission, cancellation, and browser command queues are process-local. Audio analysis runs in its own disposable process. See [architecture](architecture.md) for data flow and [API limits](api.md) for exact budgets.
