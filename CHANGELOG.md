# Changelog

All notable changes to the Fellow Stagg EKG+ integration are documented here.
Before tagging a release, add a `## <version>` section (matching the version in
`manifest.json`); the release workflow publishes that section verbatim as the
GitHub release notes. Older releases predate this file - see the
[releases page](https://github.com/samwiseg0/ha-stagg-ekg-plus/releases).

## 0.8.0

The integration now reports when the kettle is unreachable.

### Added
- A **Reachable** diagnostic binary sensor. It is on while Home Assistant is connected to the kettle or hears it advertise. It turns off after 5 minutes with neither, and the log gets one warning. It shows unknown for up to 5 minutes after a restart. Use it to get a notification when the kettle needs a power cycle.

### Fixed
- In on-demand mode, entities no longer go unavailable after a Home Assistant restart while the kettle is off. They show unknown until the kettle first reports. A tap on **Power** now connects, or shows a "not reachable" error. Before, Home Assistant rejected the tap and the integration logged nothing.
- In on-demand mode, a failed first connect at startup no longer leaves the entry in setup retry with no entities.
- **Enable debug logging** no longer logs every Bluetooth signal from every nearby device. It still logs the kettle frames and the connection retries.

### Notes
- Persistent mode keeps its entity availability. It also gets the **Reachable** sensor.
- On demand, an automation that checks kettle entities for `unavailable` no longer fires when the kettle is unreachable. Trigger it on **Reachable** turning off instead.

## 0.7.9

Fix for the current temperature on a kettle set to Celsius.

### Fixed
- In Celsius, the **Current temperature** sensor is unavailable while the kettle is off or lifted, instead of showing 0 °C. (#50)
- In Celsius, a real reading of 32 °C now shows as 32 °C. Before, the sensor went unavailable at that value. (#50)

### Notes
- Fahrenheit kettles are unaffected. No changes to options or entities.

## 0.7.8

Fixes for persistent mode and for bogus temperature readings.

### Fixed
- In persistent mode, an idle kettle no longer reconnects every 22 seconds. The kettle repeats an unchanged state about once a second, and the keep-alive now counts those frames. (#42)
- In persistent mode, entities go unavailable as soon as the connection drops and come back when it reconnects. Before, they kept showing the last state until something changed. (#42)
- A lost Bluetooth notification no longer produces bogus values. These included a current temperature equal to the target while off, negative temperatures, and brief power flips. The decoder now skips a frame that arrived out of order, and the kettle repeats it a second later. (#46)

### Notes
- No changes to options or entities.

## 0.7.7

Now available directly in HACS.

### Changed
- Installation through HACS no longer needs a custom repository. The integration is in the HACS default list.

### Internal
- Dropped `bleak-retry-connector` from `manifest.json` requirements. Home Assistant core ships and pins that package, so declaring it here added nothing and could only conflict if the pins diverged.

### Notes
- No changes to options, entities, or the protocol. Existing installs upgrade transparently.

## 0.7.6

Entity-accuracy fixes and Bluetooth/diagnostics hardening, plus CI and test-quality improvements.

### Fixed
- The climate entity now reports **Idle** when the kettle has reached its target and is keeping warm, or when it is lifted off the base, instead of always showing **Heating** while powered on. It shows **Heating** only while the water is actively warming up.
- The **On base** binary sensor stays *Unknown* until the kettle reports its base state, instead of briefly claiming **On base** before any reading has arrived.

### Changed
- Before the first reading on a fresh connection, the climate slider now follows your Home Assistant temperature unit (°F/°C) instead of always defaulting to Celsius; once the kettle reports its own unit, that takes over as before.
- Diagnostics downloads now redact the kettle's Bluetooth address.
- BLE commands re-check the active connection on each write retry, so a reconnect that happens mid-retry can no longer send to a stale link.

### Internal
- Added a Ruff lint check to CI and pinned the test toolchain for reproducible builds.
- Corrected the downloadable release `.zip` layout so a manual install extracts into `custom_components/stagg_ekg_plus/` as expected.
- Added pip dependency updates to Dependabot and expanded entity, config-flow, and coordinator test coverage (148 tests, 100%).

### Notes
- No changes to options, entities, or the protocol. The one behavior change to be aware of is the more accurate climate action above: an automation that triggers on the climate entity's `hvac_action` being `heating` will now read `idle` while the kettle keeps warm at temperature. The **Holding temp** binary sensor remains the most reliable "at temperature" signal. Existing installs upgrade transparently.

## 0.7.5

### Fixed
- The power switch no longer momentarily appears as a definitive (non-assumed) state during a background poll. A background poll only briefly connects to check for a physical power-on, so the switch now stays "assumed" through it and is treated as definitive only during a genuine live session (kettle on, or persistent mode).

### Internal
- CI maintenance: updated GitHub Actions (checkout, setup-python, codecov) and pinned the HACS validation action to its maintained branch. No effect on the integration itself.

### Notes
- No changes to options, entities, or the protocol. Existing installs upgrade transparently.

## 0.7.4

Small correctness and code-quality improvements. No configuration changes.

### Changed
- The power switch now reports `assumed_state` while disconnected (in on-demand mode the shown state is the last known value and may be stale if the kettle was toggled physically); a live connection reflects the real state.
- Overridden entity and config-flow methods are now decorated with `typing.override`, matching current Home Assistant conventions and verified by strict type checking.
- Corrected an internal comment about the default temperature unit before the first state frame.

### Notes
- No changes to options, entities, or the protocol. Existing installs upgrade transparently.

## 0.7.3

Bluetooth reliability improvements, drawn from patterns in Home Assistant's `pysnooz` library. No configuration or entity changes.

### Changed
- The reconnect path now re-resolves the freshest `BLEDevice` on each internal retry (via `ble_device_callback`), instead of reusing a device captured once. This improves recovery on a busy or slow Bluetooth adapter.
- Commands are now serialized with a write lock so the switch and climate entities (separate platforms) can never overlap writes on the kettle's single characteristic.
- Transient BlueZ write errors (`org.bluez.Error.Failed` / `InProgress`) are retried with a short backoff before giving up; other errors surface immediately.

### Notes
- No changes to options, entities, or the protocol. Existing installs upgrade transparently.

## 0.7.2

A documentation and test-quality release. No user-facing behavior changes.

### Changed
- Reworked the README: a table of contents, shields.io badges (release, build, coverage, license, HACS), a consolidated feature/entity reference, and a condensed Connection mode section with less repetition.

### Added
- Codecov coverage reporting in CI.
- Full coordinator test coverage (100%); the suite now has 112 tests at 99% overall.

### Notes
- No changes to the BLE protocol, entities, or options. Existing installs upgrade transparently.
