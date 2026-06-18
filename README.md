# Fellow Stagg EKG+ for Home Assistant

A native Home Assistant integration for the [Fellow Stagg EKG+](https://fellowproducts.com/products/stagg-ekg-plus) electric kettle. It talks to the kettle directly over Bluetooth LE using Home Assistant's built-in Bluetooth stack, so **no separate bridge, server, or Homebridge instance is required**.

This is a from-scratch reimplementation of the protocol used by the
[homebridge-stagg-ekg-plus](https://github.com/philscott-dev/homebridge-stagg-ekg-plus)
project, built as a HACS-installable custom integration.

## Features

- **Climate** entity: set the target temperature and turn the kettle on/off.
- **Switch**: power on/off.
- **Sensors**: current temperature, target temperature, and a **Hold timer** (how long the kettle will keep going before it powers itself off: counts down from 60 minutes while keep-warm/hold is on, or 5 minutes after a boil without hold).
- **Diagnostic sensor** (disabled by default): **Signal strength** (Bluetooth RSSI).
- **Binary sensors**: **Holding temp** (on once the kettle has reached the target and is maintaining temperature; off while heating up) and **On base** (on when the kettle is seated on its base, off when lifted). An optional **Hold enabled** sensor (the physical hold slider position) is available but disabled by default.
- Follows the kettle's Fahrenheit/Celsius setting automatically (104-212 F / 40-100 C).
- Local push: state updates stream live over Bluetooth notifications, with automatic reconnect.
- Selectable **connection mode**: connect on demand (default - stays connected while the kettle is on, frees the adapter once it is off), or keep a persistent connection for always-live updates.
- Works with a local Bluetooth adapter **or** an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html).
- Automatic Bluetooth discovery.

## Requirements

- Home Assistant 2026.3 or newer.
- A Bluetooth adapter on the Home Assistant host, or an ESPHome Bluetooth proxy within range of the kettle.

> **Important:** Bluetooth LE allows only one active connection to the kettle at a time.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=samwiseg0&repository=ha-stagg-ekg-plus&category=integration)

1. Click the button above (or in HACS, add this repository as a custom repository with category **Integration**).
2. Install **Fellow Stagg EKG+**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/stagg_ekg_plus` into your Home Assistant `config/custom_components/` directory and restart.

## Setup

The kettle is discovered automatically once it is powered and in range. You will get a notification to set it up, or add it manually:

1. Go to **Settings -> Devices & Services -> Add Integration**.
2. Search for **Fellow Stagg EKG+** and select the discovered kettle.

The kettle advertises as `FELLOW` followed by the last bytes of its address (for example `FELLOW46B9`).

## Notes on behavior

- The kettle reports temperatures in whatever unit it is set to on the device (Fahrenheit or Celsius). The integration follows that setting automatically, including if you flip the physical F/C switch while it is running. Valid ranges are 104-212 deg F / 40-100 deg C.
- The current-temperature reading is only available while the kettle is actively measuring; when it is off **or lifted off its base**, the kettle reports a fixed sentinel value (32), so the integration reports it as unavailable.
- **Holding temp** turns on once the kettle reaches the target and starts maintaining temperature (it is off during the initial heat-up). **Hold timer** shows ~60 minutes when the hold slider is on, or ~5 minutes for the post-boil keep-warm without hold.
- Hold and unit (F/C) are physical controls on the kettle and cannot be changed over Bluetooth; they are read-only here.
- Bluetooth LE allows only one active connection to the kettle at a time. If you previously ran the Homebridge `homebridge-stagg-ekg-plus-server` on a Pi, stop it so Home Assistant can connect.

## Connection mode

Go to **Settings -> Devices & Services -> Fellow Stagg EKG+ -> Configure** to choose how Home Assistant talks to the kettle:

- **On demand (default):** connects when you send a command and stays connected while the kettle is **powered on** (so the temperature streams live while it heats and holds). Once the kettle turns off it disconnects after a few seconds to free the Bluetooth adapter for other devices. While the kettle is off, entities show the last known state.
- **Persistent:** holds one Bluetooth connection open at all times, so state updates stream live and commands take effect instantly. A keep-alive watchdog reconnects automatically if the link goes quiet.

On demand is the default because it shares the Bluetooth adapter more politely. Switch to persistent if you want always-live state or the fastest possible control while the kettle is off.

> **Note:** In on-demand mode, Home Assistant cannot tell when the kettle is turned on **physically** (using the dial on the kettle itself). The kettle does not broadcast its state in its Bluetooth advertisement, so while disconnected there is no way to know it was switched on - the entities only update once you next control it from Home Assistant. If you want physical power-ons reflected live, use **persistent** mode.

## Protocol notes

Two details of the kettle's Bluetooth protocol that are easy to get wrong:

### Auto-off timer (state frame `0x04`)

This frame is the countdown, in seconds, until the kettle powers itself off. The
value is a **16-bit little-endian** number - it's split across two bytes with the
*small* part sent first - and the pair is sent twice for redundancy
(e.g. `10 0e 10 0e`). Reassemble it as `low + (high * 256)`, so `10 0e` -> `0x0e10`
= `3600` seconds = 60 minutes.

- With the **hold (keep-warm) slider on**, it starts at **3600** (60 min).
- With hold **off** (the short post-boil warm), it starts at **300** (5 min).
- It counts down to `0`, then the kettle shuts off; it reads `0` when not in a hold
  window.

Reading only the first byte makes it look like a meaningless counter that rolls
`255 -> 0` every 256 seconds; reading both bytes reveals the real timer.

### "Holding" flag (state frame `0x06`)

This is a clean on/off flag that is **true only when the kettle has reached the
target and is actively maintaining temperature** (keep-warm), and **false while it
is still heating up** or off. It is more reliable than `0x01` (the physical
hold-slider position), which **flickers** as the heating element cycles on and off
at setpoint. `0x06` stays steady, so it is the dependable "is the kettle keeping
the water warm right now" signal, and it is what drives the **Holding temp** binary
sensor.

## Development

A standalone Bluetooth probe is included for protocol testing without Home Assistant:

```bash
python3 -m venv .venv
.venv/bin/pip install bleak
.venv/bin/python tools/scan.py            # find the kettle
.venv/bin/python tools/probe.py           # connect and print decoded state
.venv/bin/python tools/probe.py --power on --temp 200
```

The protocol codec lives in `custom_components/stagg_ekg_plus/api.py` and has no
Home Assistant dependencies, so it can be exercised directly.

### Debug logging

To inspect the raw Bluetooth protocol from inside Home Assistant, enable debug
logging on the integration (Settings -> Devices & Services -> Fellow Stagg EKG+
-> three-dot menu -> Enable debug logging). The log then contains the raw frames
(`rx ...`), each decoded frame (`frame 0xNN ...`), and the decoded state on every
change (`state ...`).

## AI disclosure

This integration was developed with the help of AI coding tools. I am not a
programmer by trade. Every change is reviewed by a human (me) before it is
committed, and the integration has been tested against a real Fellow Stagg EKG+
kettle. Issues and pull requests are welcome if you spot something that can be
improved.

## Credits

Protocol reverse engineering by
[philscott-dev](https://github.com/philscott-dev/homebridge-stagg-ekg-plus-server),
[tlyakhov](https://github.com/tlyakhov/fellow-stagg-ekg-plus), and
[levi](https://github.com/levi/stagg-ekg-plus-ha). tlyakhov first mapped out the
state frame types. This integration decoded the `0x04` auto-off timer as a 16-bit
little-endian value (his code read only its low byte and guessed it was a lift
countdown) and worked out the `0x06` "actively holding" signal (which his code
left undecoded).

## License

GPL-3.0. See [LICENSE](LICENSE).
