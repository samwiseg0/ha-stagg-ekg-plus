# Fellow Stagg EKG+ for Home Assistant

[![GitHub Release](https://img.shields.io/github/release/samwiseg0/ha-stagg-ekg-plus.svg?style=flat-square)](https://github.com/samwiseg0/ha-stagg-ekg-plus/releases)
[![Build Status](https://img.shields.io/github/actions/workflow/status/samwiseg0/ha-stagg-ekg-plus/validate.yml?branch=main&style=flat-square)](https://github.com/samwiseg0/ha-stagg-ekg-plus/actions/workflows/validate.yml)
[![Test Coverage](https://img.shields.io/codecov/c/gh/samwiseg0/ha-stagg-ekg-plus?style=flat-square)](https://app.codecov.io/gh/samwiseg0/ha-stagg-ekg-plus/)
[![License](https://img.shields.io/github/license/samwiseg0/ha-stagg-ekg-plus.svg?style=flat-square)](LICENSE)
[![hacs](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://hacs.xyz/docs/faq/custom_repositories)

A native Home Assistant integration for the [Fellow Stagg EKG+](https://fellowproducts.com/products/stagg-ekg-plus) electric kettle. It talks to the kettle directly over Bluetooth LE using Home Assistant's built-in Bluetooth stack, so **no separate bridge, server, or Homebridge instance is required**.

This is a from-scratch reimplementation of the protocol used by the
[homebridge-stagg-ekg-plus](https://github.com/philscott-dev/homebridge-stagg-ekg-plus)
project, built as a HACS-installable custom integration.

## Contents

- [Features](#features)
- [Supported devices](#supported-devices)
- [Requirements](#requirements)
- [Installation](#installation)
  - [HACS (recommended)](#hacs-recommended)
  - [Manual](#manual)
- [Setup](#setup)
- [Connection mode](#connection-mode)
  - [Background poll (on demand only)](#background-poll-on-demand-only)
- [Entities](#entities)
- [How data is updated](#how-data-is-updated)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)
- [Example automation](#example-automation)
- [Blueprints](#blueprints)
  - [Stagg EKG Plus iOS Live Activity](#stagg-ekg-plus-ios-live-activity)
- [Removing the integration](#removing-the-integration)
- [Protocol notes](#protocol-notes)
  - [Hold timer (state frame `0x04`)](#hold-timer-state-frame-0x04)
  - ["Holding temp" flag (state frame `0x06`)](#holding-temp-flag-state-frame-0x06)
- [Development](#development)
  - [Debug logging](#debug-logging)
- [AI disclosure](#ai-disclosure)
- [Credits](#credits)
- [License](#license)

## Features

- **Climate, switch, sensors, and binary sensors** for the kettle - set the
  target temperature, turn it on/off, and read current/target temperature, the
  auto-off (hold) timer, holding status, and base presence. See [Entities](#entities).
- Follows the kettle's Fahrenheit/Celsius setting automatically (104-212 F / 40-100 C).
- **Local push:** state streams live over Bluetooth notifications, with automatic reconnect.
- Selectable **connection mode** (on demand or persistent), with an optional
  background poll to catch a physical power-on. See [Connection mode](#connection-mode).
- Works with a local Bluetooth adapter **or** an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html).
- Automatic Bluetooth discovery.

## Supported devices

- **Fellow Stagg EKG+** (the Bluetooth model). It advertises as `FELLOW` followed by the last bytes of its address (for example `FELLOW46B9`).
- **Not supported:** the **Fellow Stagg EKG Pro** (a different, WiFi-based kettle with its own protocol) and the original non-smart Stagg EKG.

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

## Connection mode

Go to **Settings -> Devices & Services -> Fellow Stagg EKG+ -> Configure** to choose how Home Assistant talks to the kettle:

- **On demand (default):** connects when you send a command and stays connected while the kettle is **powered on**, so temperature streams live while it heats and holds. It disconnects a few seconds after the kettle turns off to free the Bluetooth adapter; entities then show the last known state.
- **Persistent:** keeps one Bluetooth connection open at all times for always-live state and instant commands. A keep-alive watchdog reconnects automatically if the link goes quiet.

On demand shares the adapter more politely and is the default; choose persistent for always-live state or the fastest control while the kettle is off.

### Background poll (on demand only)

On demand cannot tell when the kettle is switched on **physically** (using the dial on the kettle), because the kettle does not broadcast its state - while disconnected, Home Assistant has no way to know. The background poll closes that gap: at the interval you choose (Off by default, or every 1 / 2 / 5 minutes) Home Assistant briefly reconnects while the kettle is off, checks its state, and disconnects again unless it finds the kettle on - in which case it keeps the connection and streams live.

A shorter interval notices a physical power-on sooner but uses the adapter more often; **Off** keeps the adapter free but means physical power-ons are not reflected until you next control the kettle from Home Assistant. The setting has no effect in persistent mode (already always connected).

## Entities

| Entity | Platform | Notes |
| --- | --- | --- |
| Kettle (target temp + heat/off) | `climate` | Follows the kettle's F/C unit; range 104-212 F / 40-100 C |
| Power | `switch` | On/off |
| Current temperature | `sensor` | Unavailable when off or lifted off the base |
| Target temperature | `sensor` | |
| Hold timer | `sensor` | Auto-off countdown (60 min with hold, 5 min post-boil) |
| Holding temp | `binary_sensor` | On once at target and maintaining |
| On base | `binary_sensor` | On when seated on the base |
| Hold enabled | `binary_sensor` | Physical hold-slider position (disabled by default) |
| Signal strength | `sensor` | Bluetooth RSSI, diagnostic (disabled by default) |

## How data is updated

This is a local **push** integration. While connected, the kettle streams its
state over Bluetooth notifications (roughly once a second), and Home Assistant
updates the entities as those arrive - there is no polling of values. The
optional background poll (on-demand mode) does not poll values; it only briefly
reconnects to learn whether the kettle has been switched on.

## Known limitations

- **Hold (keep-warm) and the temperature unit (F/C) are physical-only.** The
  kettle exposes no Bluetooth command for them, so they are read-only here.
- **One Bluetooth connection at a time.** If another app, bridge, or an old
  Homebridge/Pi server is connected to the kettle, Home Assistant cannot connect
  until it is released.
- **Signal strength is the last advertised value**, not a live measurement (the
  kettle stops advertising while connected).
- **Current temperature is unavailable when the kettle is off or lifted** off its
  base - the kettle only reports a real reading while actively measuring.
- **On-demand mode without the background poll cannot detect a physical
  power-on** (see Connection mode above).

## Troubleshooting

- **Entities show unavailable / cannot connect:** make sure nothing else is
  connected to the kettle, and that it is within range of a Bluetooth adapter or
  ESPHome proxy. Bluetooth allows only one connection at a time.
- **Slow connects or `[Errno 12] Out of memory` in the log:** these come from the
  host's Bluetooth adapter being under load, not the integration. A longer
  background-poll interval or moving the kettle onto an ESPHome Bluetooth proxy
  reduces the load.
- **Filing a bug:** open the device page (Settings -> Devices & Services ->
  Fellow Stagg EKG+ -> the device) and use **Download diagnostics**; attach that
  to the issue. Enabling debug logging (see below) and including the log helps too.

## Example automation

Notify when the water has reached the set temperature:

```yaml
automation:
  - alias: Kettle ready
    triggers:
      - trigger: state
        entity_id: binary_sensor.fellow_stagg_ekg_plus_holding_temp
        to: "on"
    actions:
      - action: notify.notify
        data:
          message: "The kettle has reached temperature."
```

## Blueprints

### Stagg EKG Plus iOS Live Activity

An automation blueprint that shows an iOS **Live Activity** for the kettle: the
current temperature while it heats, a "Ready" alert when it reaches the target,
and it clears when the kettle turns off.

[![Open your Home Assistant instance and show the blueprint import dialog with this blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fsamwiseg0%2Fha-stagg-ekg-plus%2Fblob%2Fmain%2Fblueprints%2Fstagg_ekg_live_activity.yaml)

**Requirements:** Home Assistant 2026.7 or newer, the Home Assistant Companion
app on iOS (Live Activities need iOS 16.1 or newer), and this integration set up.

Click the button above to import it, then create an automation from the blueprint
and fill in:

- **Power Switch** - the kettle's `switch` entity
- **Holding Temp Sensor** - the `binary_sensor.*_holding_temp` entity
- **Climate Entity** - the kettle's `climate` entity
- **Notify Service** - your phone's direct notify service
  (e.g. `notify.mobile_app_yourphone`), not a group (group services do not carry
  the Live Activity token)
- **Notification Tag** and **Device Name** - optional; sensible defaults are
  provided

## Removing the integration

Go to **Settings -> Devices & Services -> Fellow Stagg EKG+**, open the
three-dot menu on the entry, and choose **Delete**. If you installed it through
HACS and want it gone entirely, remove it from HACS afterward and restart Home
Assistant.

## Protocol notes

Two details of the kettle's Bluetooth protocol that are easy to get wrong:

### Hold timer (state frame `0x04`)

This frame backs the **Hold timer** sensor: the countdown, in seconds, until the
kettle powers itself off. The value is a **16-bit little-endian** number - it's
split across two bytes with the *small* part sent first - and the pair is sent
twice for redundancy (e.g. `10 0e 10 0e`). Reassemble it as `low + (high * 256)`,
so `10 0e` -> `0x0e10` = `3600` seconds = 60 minutes.

- With the **hold (keep-warm) slider on**, it starts at **3600** (60 min).
- With hold **off** (the short post-boil warm), it starts at **300** (5 min).
- It counts down to `0`, then the kettle shuts off; it reads `0` when not in a hold
  window.

Reading only the first byte makes it look like a meaningless counter that rolls
`255 -> 0` every 256 seconds; reading both bytes reveals the real timer.

### "Holding temp" flag (state frame `0x06`)

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
