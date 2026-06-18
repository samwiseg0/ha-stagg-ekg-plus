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
  __init__.py        # setup/unload; entry.runtime_data = StaggCoordinator; options update listener reloads entry
  manifest.json      # BT matchers (service 1820 + local_name FELLOW*), iot_class local_push
  const.py           # DOMAIN, MANUFACTURER, MODEL, connection-mode + timer constants
  api.py             # PURE protocol codec + StaggClient. NO Home Assistant imports.
  coordinator.py     # StaggCoordinator: BLE conn + reconnect + keep-alive + on-demand
  config_flow.py     # Bluetooth auto-discovery + manual user step + options flow (connection mode)
  entity.py          # StaggEntity base (device info, availability)
  climate.py         # target temp + heat/off; follows kettle F/C unit
  switch.py          # power
  sensor.py          # current temp (None when off), target temp, auto-off timer, rssi (diag, opt-in)
  binary_sensor.py   # holding (0x06), on-base (0x08), hold-enabled (0x01, opt-in)
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
  (`async_register_callback`) for instant reconnect, plus an exponential backoff
  retry loop (`async_call_later`) so an idle kettle that stopped advertising is
  still recovered. When no current advertisement is cached the coordinator falls
  back to the last known BLEDevice (`async_last_service_info`) for a directed
  connect. `update_interval=None` (no polling).
- State is push-based: notifications -> `coordinator.async_set_updated_data(state)`.
- On every successful connect the coordinator records `time.monotonic()`; on
  disconnect it logs how long the link was held (`_format_duration`) at INFO.

## Connection mode (user option)

- Set via the Configure dialog (options flow, `StaggOptionsFlow`). Option key
  `CONF_CONNECTION_MODE` in `entry.options`; values `on_demand` (default) or
  `persistent`. Changing it triggers `_async_update_listener` ->
  `async_reload(entry_id)`, so the coordinator is rebuilt with the new mode.
- A single predicate `StaggCoordinator._wants_connection()` gates all
  connection-holding behavior (advertisement auto-connect, backoff reconnect,
  keep-alive). Persistent: always True. On-demand: True only while
  `self.data.power` (kettle on).
- **Keep-alive watchdog** (`KEEP_ALIVE_TIMEOUT`, 60s): every notification rearms
  it via `_reset_keepalive`; if it fires the link is treated as stale and
  dropped (`_client.disconnect()`), which routes through `_on_disconnect` ->
  `_schedule_reconnect`. Runs whenever `_wants_connection()` and connected.
- **On-demand idle disconnect** (`ON_DEMAND_DISCONNECT_DELAY`, 10s): when the
  kettle reports power off, `_schedule_idle_disconnect(reset=False)` arms a
  one-shot timer (reset=False so the kettle's periodic off-state frames do not
  keep pushing it out). `_idle_disconnect_fired` sets `_expected_disconnect`
  then disconnects; `_on_disconnect` sees the flag (or `not _wants_connection()`)
  and does NOT reconnect. Commands and `_ensure_connected` schedule it with
  reset=True as a fallback; a resulting power-on state cancels it.
- Entity availability: `coordinator.available` = `is_connected` in persistent
  mode, but `data is not None` in on-demand (entities keep showing last-known
  state while the link is intentionally dropped). `entity.py` uses
  `super().available and self.coordinator.available`.

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
  `01` = Fahrenheit, `00` = Celsius. Ranges: F 104-212, C 40-100.
- `current_temp` byte `0x20` (32) is the OFF sentinel; the kettle only reports a
  real reading while powered on (entities report None when off).
- State frame types: 0x00 power, 0x01 hold BUTTON, 0x02 target temp+unit,
  0x03 current temp+unit, 0x04 auto-off countdown (16-bit LE seconds, sent as
  [lo,hi] twice; 3600 = 60 min with the hold slider on, 300 = 5 min without it,
  counts down to 0 then the kettle powers off; 0 when not in a hold window),
  0x05 marker (ffffffff), 0x06 hold MODE (keep-warm), 0x07 reserved (000000),
  0x08 base presence.
  0x05 and 0x07 are verified constant across every EKG+ state (nothing to decode).
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

- `hold` (0x06) = "actively holding/maintaining temperature": True once at
  target and maintaining (incl. the 5-min post-hold window with the slider off),
  False while heating up (current < target) or off. Surfaced as the **Holding**
  binary sensor. `hold_button` (0x01) = the physical hold slider position alone
  (on=1/off=0); it pulses when the element cycles right at setpoint, so it is
  surfaced as **Hold enabled** but disabled by default.
- `auto_off_remaining` (0x04) = the auto-off countdown, 16-bit little-endian
  seconds: 3600 (60 min) with the hold slider on, 300 (5 min) without. Surfaced
  as the **Auto-off timer** duration sensor (native seconds, suggested minutes).
- RSSI is exposed as a diagnostic **Signal strength** sensor (disabled by
  default) via `bluetooth.async_last_service_info`; it reflects the last
  advertised RSSI, not a live value (the kettle does not advertise while
  connected).
- No BLE write command for hold or units exists in any reverse-engineering
  reference; both are physical-only on this kettle.
- Not yet exercised against the HA test suite (no HA in the local venv).

## Credits

Protocol reverse engineering: philscott-dev (homebridge-stagg-ekg-plus-server)
and tlyakhov (fellow-stagg-ekg-plus).
