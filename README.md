# Kame32 DanceMode & TeachMoves

Analyze music into dance timelines, preview an eight-servo Kame32, and record reusable moves. Control the app through its browser UI or MCP. Hardware playback supports stock joystick/button commands and exact servo poses with the optional firmware update.

![DanceMode preview](SCREENSHOT.png)

## Start with Docker

```bash
docker compose up --build -d
```

Open the app on your Docker host at `http://127.0.0.1:5000`. Streamable HTTP MCP is available at `http://127.0.0.1:8000/mcp`. For a managed environment with a TLS-inspecting proxy, use the [cloud build override](docs/docker.md#managed-cloud-tls-proxy).

Docker runs the app and MCP as non-root users with persistent move storage. Keep one app container and one Gunicorn worker; dispatch coordination is process-local. [Docker deployment](docs/docker.md) covers configuration, updates, audio, and health checks. For a source checkout, see [development setup](docs/development.md).

## Choose a workflow

- **DanceMode:** upload audio, inspect its generated events, preview, and optionally send a timeline.
- **TeachMoves:** select Move1–Move6, record manual controls, then save, replay, or transfer a move to DanceMode.
- **MCP:** analyze audio, manage recordings, control connected browser tabs, or explicitly request robot dispatch.

| Hardware mode | Requirement |
| --- | --- |
| Auto | Prefers updated pose firmware; otherwise uses a saved stock command track |
| Stock compatibility | Recording made entirely with supported joystick/button controls and default gait/speed settings |
| Exact servo poses | Upgraded pose/watchdog firmware |

Manual servo poses cannot be converted into stock commands. Recording and browser playback do not move hardware; Send and MCP dispatch tools do. Stock firmware has no disconnect watchdog, and its routines can delay cancellation. [Firmware instructions](docs/firmware.md) explain the optional update and physical acceptance checks.

## Documentation

Start with the [documentation index](docs/README.md):

- [User guide](docs/user-guide.md)
- [Docker deployment](docs/docker.md) and [source development](docs/development.md)
- [HTTP API and limits](docs/api.md)
- [MCP client setup and tools](docs/mcp.md)
- [Firmware and watchdog](docs/firmware.md)
- [Architecture](docs/architecture.md) and [audit / remaining work](docs/audit.md)

The latest recorded Docker validation passed all 55 tests. Physical robot acceptance, authenticated remote access, and independent backups remain outstanding. Ports bind to host loopback by default; keep access restricted to trusted users. Docker volume persistence is not an independent backup.
