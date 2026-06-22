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
  const.py           # DOMAIN, MANUFACTURER, MODEL, connection-mode + poll + timer constants
  api.py             # PURE protocol codec + StaggClient. NO Home Assistant imports.
  coordinator.py     # StaggCoordinator: BLE conn + reconnect + keep-alive + on-demand + optional poll
  config_flow.py     # Bluetooth auto-discovery + manual user step + options flow (connection mode + poll interval)
  entity.py          # StaggEntity base (device info, availability)
  climate.py         # target temp + heat/off; follows kettle F/C unit
  switch.py          # power
  sensor.py          # current temp (None when off), target temp, auto-off timer, rssi (diag, opt-in)
  binary_sensor.py   # holding (0x06), on-base (0x08), hold-enabled (0x01, opt-in)
  strings.json, translations/en.json
  brand/             # bundled icon.png + logo.png + dark_logo.png (HA 2026.3+ local brand images)
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
- **Keep-alive watchdog** (`KEEP_ALIVE_TIMEOUT`, 20s): every notification rearms
  it via `_reset_keepalive`; if it fires the link is treated as stale
  (`_stale_disconnect = True`) and dropped (`_client.disconnect()`), which routes
  through `_on_disconnect` -> `_schedule_reconnect`. Runs whenever
  `_wants_connection()` and connected.
- **On-demand idle disconnect** (`ON_DEMAND_DISCONNECT_DELAY`, 10s): when the
  kettle reports power off, `_schedule_idle_disconnect(reset=False)` arms a
  one-shot timer (reset=False so the kettle's periodic off-state frames do not
  keep pushing it out). `_idle_disconnect_fired` disconnects; `_on_disconnect`
  gates reconnect SOLELY on `_wants_connection()` (kettle off -> no reconnect),
  which also fixes the race where the timer fires just as the kettle comes on.
  Commands and `_ensure_connected` schedule it as a fallback; a resulting
  power-on state cancels it. `_schedule_idle_disconnect(delay=...)` takes a
  custom delay so a probe uses the shorter `PROBE_DISCONNECT_DELAY`.
- **Background poll (on-demand only, optional)**: option key `CONF_POLL_INTERVAL`
  in `entry.options` (string seconds; `POLL_INTERVAL_OPTIONS` = Off/60/120/300,
  default `0` = Off). While on-demand AND disconnected AND `not
  _wants_connection()` (kettle believed off), `_schedule_poll` arms
  `_poll_timer_fired` every interval. `_async_probe` sets `_probing = True` and
  calls `_ensure_connected`; connect failures log at debug (expected for an off
  kettle). On a successful connect the normal `_handle_state` path decides: power
  on clears `_probing` and keeps the link (becomes a live session); power off
  arms the idle disconnect with `PROBE_DISCONNECT_DELAY` (5s) instead of 10s.
  `PROBE_DISCONNECT_DELAY` also bounds the wait for the first state frame on a
  kettle that turns out to be on, so it stays comfortably above the ~1s cadence.
  `_on_disconnect` reschedules the poll (and clears `_probing`) on an intentional
  drop; `_ensure_connected` cancels the poll timer on connect. Lets HA catch a
  physical power-on (advert carries no state) without persistent mode. No effect
  in persistent mode.
- Entity availability: `coordinator.available` = `is_connected` in persistent
  mode, but `data is not None` in on-demand (entities keep showing last-known
  state while the link is intentionally dropped). `entity.py` uses
  `super().available and self.coordinator.available`.

## Bluetooth / kettle protocol facts (verified against real hardware)

- GATT service `00001820-0000-1000-8000-00805f9b34fb`,
  characteristic `00002a80-...` (write + notify).
- Protocol lineage: shares the Acaia / pyacaia BLE family (the old-style Acaia
  scales use this same char `00002a80` and the same `0xefdd` header; see
  `zweckj/aioacaia`). The Stagg uses a SIMPLIFIED variant: state frames are just
  `efdd <type> <payload>` with NO length byte and NO trailing checksum (Acaia's
  canonical `efdd cmd length payload ck1 ck2` does not apply here). VERIFIED by
  live capture 2026-06-22 (tools/probe.py): each frame arrives as two
  notifications -- a 3-byte header `efdd<type>` then the payload. Payloads are
  tiny (3-4 bytes), values often sent twice. Decoded table: 00 power `010100`;
  01 hold-button `010100`; 02 target `d001d001` (208F,unit); 03 current
  `53015301` (83F,unit); 04 auto-off `00000000` (16-bit LE x2); 05 marker
  `ffffffff`; 06 hold-mode `000000`; 07 reserved `000000`; 08 base `010100`
  (01=on base) plus the oversized auth echo `09640202...` (ignored). So
  separator-split `parse_frames` is correct; do NOT add length-aware parsing
  (it would read a data byte as a length). False-separator risk ~0: every value
  is range-bounded below 0xef (temps cap 0xd4, auto-off max 0x0e10).
- Advertised name: `FELLOW` + last 2 MAC bytes (e.g. `FELLOW46B9`).
- On connect, send the fixed auth frame `INIT_SEQUENCE` before commands work.
- All frames (rx and tx) start with separator `0xefdd`. Notifications arrive
  fragmented mid-frame; buffer across notifications (see `parse_frames`).
- Command frame: `ef dd 0a <seq> <type> <value> <checksum> <type>`
  (type 0x00 power, 0x01 temp; checksum = (seq+value) & 0xff; seq increments).
- Temp frames send `[value, unit]` twice for redundancy. Unit byte:
  `01` = Fahrenheit, `00` = Celsius. Ranges: F 104-212, C 40-100.
- `current_temp` byte `0x20` (32) is the OFF sentinel; the kettle only reports a
  real reading while actively measuring. It reads `0x20` when powered off OR when
  powered on but lifted off the base. `api.py` decodes `0x20` to `current_temp =
  None` (entities report unavailable in both cases).
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
python3 -m venv .venv && .venv/bin/pip install bleak pytest

# syntax check everything
.venv/bin/python -m py_compile custom_components/stagg_ekg_plus/*.py tools/*.py

# unit tests (pure protocol codec; no Home Assistant needed)
.venv/bin/python -m pytest tests/test_api.py -q

# full suite incl. HA config/options flow tests (heavier; pulls in HA + the
# bluetooth/usb component deps via pytest-homeassistant-custom-component)
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest tests/ -q

# find the kettle (Linux shows MAC; macOS shows a per-host UUID)
.venv/bin/python tools/scan.py

# read-only decode (calibration); add --power on/off --temp N to write
.venv/bin/python tools/probe.py --duration 25
```

When changing `api.py`, run `tests/test_api.py` (build_*_command must reproduce
captured frames; parse_frames+apply_frame must decode a real capture). The codec
tests load `api.py` standalone by path, so they run without Home Assistant.
`tests/test_config_flow.py` covers the config + options flows via
pytest-homeassistant-custom-component; `tests/conftest.py` stubs the bluetooth
manager's D-Bus system-history load so the `bluetooth` dependency sets up in CI/
on macOS. CI runs everything via `.github/workflows/validate.yml` (the `tests`
job installs `requirements_test.txt`).

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
and tlyakhov (fellow-stagg-ekg-plus). Underlying BLE protocol family: Acaia /
pyacaia (see zweckj/aioacaia) -- the Stagg reuses the same characteristic and
`0xefdd` header with a simplified frame layout.
