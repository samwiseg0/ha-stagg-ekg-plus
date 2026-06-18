# Fellow Stagg EKG+ for Home Assistant

A native Home Assistant integration for the [Fellow Stagg EKG+](https://fellowproducts.com/products/stagg-ekg-plus) electric kettle. It talks to the kettle directly over Bluetooth LE using Home Assistant's built-in Bluetooth stack, so **no separate bridge, server, or Homebridge instance is required**.

This is a from-scratch reimplementation of the protocol used by the
[homebridge-stagg-ekg-plus](https://github.com/philscott-dev/homebridge-stagg-ekg-plus)
project, built as a HACS-installable custom integration.

## Features

- **Climate** entity: set the target temperature and turn the kettle on/off.
- **Switch**: power on/off.
- **Sensors**: current temperature and target temperature.
- **Binary sensors**: keep-warm (hold) and off-base.
- Local push: state updates stream live over Bluetooth notifications.
- Works with a local Bluetooth adapter **or** an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html).
- Automatic Bluetooth discovery.

## Requirements

- Home Assistant 2024.8 or newer.
- A Bluetooth adapter on the Home Assistant host, or an ESPHome Bluetooth proxy within range of the kettle.

> **Important:** Bluetooth LE allows only one active connection to the kettle at a time. If you previously used the Homebridge plugin and its companion `homebridge-stagg-ekg-plus-server` on a Raspberry Pi, **stop/decommission that server first** (e.g. `pm2 stop homebridge-stagg-ekg-plus-server`). While it holds the connection, Home Assistant cannot reach the kettle.

## Installation

### HACS (recommended)

1. In HACS, add this repository as a custom repository (category: Integration).
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

- The kettle reports temperatures in whatever unit it is set to on the device (Fahrenheit or Celsius). The integration follows that setting automatically. Valid ranges are 140-212 deg F / 40-100 deg C.
- The current-temperature reading is only available while the kettle is powered on; when off, the kettle reports a fixed sentinel value, so the integration reports it as unavailable.

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

## Credits

Protocol reverse engineering by
[philscott-dev](https://github.com/philscott-dev/homebridge-stagg-ekg-plus-server)
and [tlyakhov](https://github.com/tlyakhov/fellow-stagg-ekg-plus).

## License

MIT
