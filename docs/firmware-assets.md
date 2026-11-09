# Firmware asset provenance

- Upstream: <https://github.com/javierih/kame32>
- Base commit: `8f33e489f7425747ab62aeb509777a06d2f14f3e`
- License: Creative Commons Attribution-ShareAlike 4.0 International, as supplied by upstream; see [LICENSE.kame32](../firmware/LICENSE.kame32).
- Artifact: [pose/watchdog patch](../firmware/kame32-pose-watchdog.patch).

The patch contains pose streaming, controller leases, an independent PWM-disarm watchdog, native lease tests, and upstream README updates. Its contents retain upstream file paths and context so it can be applied to the pinned checkout. It is not automatically installed or flashed by this app or Docker.

See [firmware setup and acceptance](firmware.md) for applying, building, and testing it. Keep patch/license files under `firmware/`; project documentation lives here.
