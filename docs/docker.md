# Docker deployment

## Start

From the repository root:

```bash
docker compose up --build -d
```

The app is published on host loopback port **5000**, and Streamable HTTP MCP on host loopback port **8000** at `/mcp`. Open the app in a browser on the Docker host. MCP clients can connect to `http://127.0.0.1:8000/mcp`. These local addresses are configuration examples, not cloud preview links.

Override occupied ports and the configured robot origins as needed:

```bash
KAME32_WEB_PORT=5100 KAME32_MCP_PORT=8100 \
KAME32_ROBOT_ORIGINS=http://192.168.4.1 docker compose up --build -d
```

The services use normal Compose networking. MCP trusts the explicit `app` service hostname via `KAME32_TRUSTED_APP_HOSTS=app`; the default outside Docker remains loopback-only. Each service publishes its own port, bound to host loopback, and can restart independently. There is no remote authentication/OAuth; do not change publishing to public interfaces without adding authenticated access.

## Image and runtime

- Python 3.12 on Debian Bookworm, FFmpeg and libsndfile for audio decoding.
- All Python packages are pinned in `requirements-docker.lock`, including optional MCP dependencies and Gunicorn. The base image tag and Debian package updates are not digest/version locked.
- Non-root UID/GID 10001.
- One Gunicorn worker with eight threads. Keep **one app container and one worker**: robot dispatch/cancellation/browser command state is process-local.
- MCP has its own process and real MCP initialization/connectivity health check. The app health check makes an HTTP request.
- `moves` volume persists SQLite recordings and their stock command tracks; `cache` holds the Numba cache; `audio` holds audio available to MCP. Bundled sample MP3s seed the audio volume on first creation.
- No Docker socket or device is mounted. This stack does not flash firmware. The firmware patch/build instructions are in firmware.md.

Add audio through the writable app mount (the MCP mount is read-only):

```bash
docker compose cp ./my-song.mp3 app:/audio/my-song.mp3
```

Then call `analyze_audio(path="my-song.mp3")`. Files must remain under `/audio` after resolving symlinks. Browser uploads are analyzed temporarily and are not added to the audio library.

For a stdio MCP client, run an additional adapter in the existing container:

```bash
docker compose exec -T mcp python mcp_server.py
```

This adapter uses the same app instance and move store; it does not create another robot executor.

## Persistent data and updates

`docker compose down` retains named volumes. Restarting/recreating services retains saved moves but clears active browser commands and dispatch state. Do not use `down -v` unless you intend to delete recordings, audio, and cache. Stop active robot playback before stopping/updating containers. Stock firmware cannot independently stop on a lost app connection; upgraded firmware expires its lease.

Rebuild with `docker compose up --build -d`. Update the pinned Python packages deliberately by installing the application/MCP dependencies plus Gunicorn in a clean Python 3.12 environment, validating them, and regenerating `requirements-docker.lock` with `pip freeze`.

## Managed cloud TLS proxy

For environments with a TLS-inspecting proxy, use the provided optional override. It mounts the public CA bundle as a BuildKit secret during networked build steps and as a read-only runtime secret; it is not copied into the image:

```bash
docker compose -f compose.yaml -f compose.cloud.yaml up --build -d
```

`KAME32_BUILD_CA` overrides the default `/etc/ssl/certs/ca-certificates.crt` source path. Existing Docker proxy defaults remain in use. TLS and package signature verification stay enabled. The plain Compose file works with normal public CA trust and does not require the cloud-specific path.

## Robot connectivity and acceptance

The container must be able to reach the configured robot origin through its Docker host/network policy. A robot AP on a user's laptop is not automatically reachable from a cloud Docker host. Host USB forwarding, firmware flashing, VPN configuration and remote publication are outside this deployment.

In TeachMoves choose Auto, Stock compatibility, or Exact servo poses. Stock mode requires a joystick/button command track recorded with default gait settings and 100% preview speed. Manual pose recordings need upgraded firmware. Stock button routines block their HTTP handler, so timing can drift and cancellation may be delayed; that is a firmware limitation, not a precise servo replay.

Checks:

```bash
docker compose ps
docker compose exec -T app python -m unittest discover -s tests -v
docker compose exec -T mcp python docker/healthcheck.py mcp
```

Hardware dispatch is not part of these tests. Physical motion/watchdog acceptance still needs a supported, calibrated robot as described in firmware.md.

## Analysis containment

Audio uploads run in a disposable worker process with one admitted analysis, CPU/address-space/wall-time limits, and bounded decoded duration. Robot dispatch is separate from that process. See [the audio budgets](api.md#audio-analysis-budgets) for the exact limits. The Linux Docker runtime enforces the worker limits; they are not a guarantee of physical watchdog timing.
