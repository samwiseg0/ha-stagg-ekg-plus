# AGENTS.md

Guidance for AI coding agents working in this repository.

## What this project is

A native Home Assistant **custom integration** (HACS-installable) for the
**Fellow Stagg EKG+** electric kettle. It controls the kettle directly over
Bluetooth LE using Home Assistant's built-in Bluetooth stack (local adapter or
ESPHome Bluetooth proxy). There is **no separate server/bridge/add-on** - this
replaces the older Homebridge plugin + Pi BLE server approach.

Domain: `stagg_ekg_plus`. Target: Home Assistant 2026.x (Python 3.13+).

## Repository layout

```
custom_components/stagg_ekg_plus/
  __init__.py        # setup/unload; entry.runtime_data = StaggCoordinator
  manifest.json      # BT matchers (service 1820 + local_name FELLOW*), iot_class local_push
  const.py           # DOMAIN, MANUFACTURER, MODEL
  api.py             # PURE protocol codec + StaggClient. NO Home Assistant imports.
  coordinator.py     # StaggCoordinator: persistent BLE conn + reconnect
  config_flow.py     # Bluetooth auto-discovery + manual user step
  entity.py          # StaggEntity base (device info, availability)
  climate.py         # target temp + heat/off; follows kettle F/C unit
  switch.py          # power
  sensor.py          # current temp (None when off), target temp
  binary_sensor.py   # keep-warm (0x06), off-base (kettle lifted)
  strings.json, translations/en.json
hacs.json
tools/scan.py        # standalone BLE scanner to find the kettle
tools/probe.py       # standalone connect/auth/notify decoder (calibration)
```

## Key architectural rules

- **`api.py` must stay free of Home Assistant imports.** It is the protocol
  codec and is exercised both by `tools/probe.py` (standalone) and by the HA
  coordinator. Keep all HA-specific logic in `coordinator.py` and the platforms.
- The coordinator injects an HA-managed connection: it calls
  `bleak_retry_connector.establish_connection(...)` then `StaggClient.start(client)`.
  `StaggClient.connect()` is the standalone-only convenience path.
- Reconnection is driven by the bluetooth advertisement callback
  (`async_register_callback`), not a polling loop. `update_interval=None`.
- State is push-based: notifications -> `coordinator.async_set_updated_data(state)`.

## Bluetooth / kettle protocol facts (verified against real hardware)

- GATT service `00001820-0000-1000-8000-00805f9b34fb`,
  characteristic `00002a80-...` (write + notify).
- Advertised name: `FELLOW` + last 2 MAC bytes (e.g. `FELLOW46B9`).
- On connect, send the fixed auth frame `INIT_SEQUENCE` before commands work.
- All frames (rx and tx) start with separator `0xefdd`. Notifications arrive
  fragmented mid-frame; buffer across notifications (see `parse_frames`).
- Command frame: `ef dd 0a <seq> <type> <value> <checksum> <type>`
  (type 0x00 power, 0x01 temp; checksum = (seq+value) & 0xff; seq increments).
- Temp frames send `[value, unit]` twice for redundancy. Unit byte:
  `01` = Fahrenheit, `00` = Celsius. Ranges: F 140-212, C 40-100.
- `current_temp` byte `0x20` (32) is the OFF sentinel; the kettle only reports a
  real reading while powered on (entities report None when off).
- State frame types: 0x00 power, 0x01 hold BUTTON, 0x02 target temp+unit,
  0x03 current temp+unit, 0x04 lift countdown, 0x05 marker (ffffffff),
  0x06 hold MODE (keep-warm), 0x08 base presence.
- **0x08 is inverted vs intuition: byte `0x01` = ON BASE, `0x00` = lifted off
  base** (verified by physical lift test). `api.py` exposes `lifted = not byte`.
- The one-time auth echo also arrives as an oversized `0x08` frame; the periodic
  state frame is exactly 3 bytes. `api.py` guards on length.
- Only one BLE connection is allowed at a time. Any old Homebridge/Pi BLE server
  must be stopped before HA (or the probe) can connect.

## Build / test commands

This repo has no Home Assistant in the local venv, so validation is limited to
syntax + the pure protocol logic.

```bash
# one-time
python3 -m venv .venv && .venv/bin/pip install bleak

# syntax check everything
.venv/bin/python -m py_compile custom_components/stagg_ekg_plus/*.py tools/*.py

# find the kettle (Linux shows MAC; macOS shows a per-host UUID)
.venv/bin/python tools/scan.py

# read-only decode (calibration); add --power on/off --temp N to write
.venv/bin/python tools/probe.py --duration 25
```

When changing `api.py`, re-run the parse/command assertions (build_*_command
must reproduce captured frames; parse_frames+apply_frame must decode a real
capture). See conversation history / git log for the exact test snippet.

## Conventions

- US English spelling; plain ASCII only in source files (no em-dashes, smart
  quotes, or non-ASCII glyphs). Use `--`, `'`, `"`, `^2`, `x`.
- Follow current HA integration patterns (mirror `yalexs_ble`):
  `type StaggConfigEntry = ConfigEntry[StaggCoordinator]`, `entry.runtime_data`,
  `AddConfigEntryEntitiesCallback`, frozen kw_only entity descriptions,
  `dr.CONNECTION_BLUETOOTH` for device connections.
- Do not reintroduce a separate server/add-on; keep the single-integration design.

## Known open items / calibration TODO

- `hold` (0x06) = power AND hold-slider-on = "keep-warm actively engaged";
  verified stable in every state (controlled power/hold matrix test), so it is
  surfaced as the Keep warm binary sensor. `hold_button` (0x01) = the physical
  hold slider position alone (on=1/off=0, independent of heating) but it pulses
  when the element cycles right at setpoint, so it is decoded but NOT exposed.
- `lift_countdown` (0x04) behavior during a real lift-off timeout is unverified
  (stayed 0 during brief lifts).
- Not yet exercised inside a running HA instance.

## Credits

Protocol reverse engineering: philscott-dev (homebridge-stagg-ekg-plus-server)
and tlyakhov (fellow-stagg-ekg-plus).
