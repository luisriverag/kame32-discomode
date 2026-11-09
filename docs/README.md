# Documentation

Commands run from the repository root unless a guide explicitly changes directory. Configuration examples use local loopback addresses; they are not hosted previews.

| Goal | Guide |
| --- | --- |
| Analyze music, record moves, choose hardware playback | [User guide](user-guide.md) |
| Run app and MCP containers; manage persistent data | [Docker deployment](docker.md) |
| Install from source, run tests, diagnose 3D/audio | [Development](development.md) |
| Integrate uploads, recordings, dispatch, browser commands | [HTTP API](api.md) |
| Connect an AI client over stdio or Streamable HTTP | [MCP](mcp.md) |
| Apply/build firmware and test the on-robot watchdog | [Firmware](firmware.md) |
| Understand process boundaries and data flow | [Architecture](architecture.md) |
| Review validation evidence, limitations, next work | [Audit](audit.md) |
| Check firmware patch provenance and licensing | [Firmware assets](firmware-assets.md) |

## Operating boundaries

Preview/record actions stay in the browser. Live Send and MCP dispatch physically operate a robot. Dry-run validation checks data without contacting hardware or proving its firmware capabilities. Cancellation requests are best effort; physical watchdog acceptance still needs a calibrated robot.

The default deployment is for trusted local users. Remote authentication/TLS and scheduled, tested backups/export-import are not implemented. See the audit for the current scope and validation evidence.

[Repository overview](../README.md)
