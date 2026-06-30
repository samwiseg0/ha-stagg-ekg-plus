# Changelog

All notable changes to the Fellow Stagg EKG+ integration are documented here.
Before tagging a release, add a `## <version>` section (matching the version in
`manifest.json`); the release workflow publishes that section verbatim as the
GitHub release notes. Older releases predate this file - see the
[releases page](https://github.com/samwiseg0/ha-stagg-ekg-plus/releases).

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
