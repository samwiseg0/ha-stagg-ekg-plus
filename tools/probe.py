# Fellow Stagg EKG+ integration for Home Assistant
# Copyright (C) 2026 samwiseg0
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Standalone protocol probe for the Fellow Stagg EKG+ kettle.

Connects to the kettle, authenticates, subscribes to state notifications, and
prints both the raw frames and the decoded state so the protocol decoding can be
calibrated against the physical kettle's display.

Examples:
    # Just listen and print state for 30 seconds.
    .venv/bin/python tools/probe.py

    # Turn the kettle on, then listen.
    .venv/bin/python tools/probe.py --power on

    # Set target temperature (value in the kettle's current display units).
    .venv/bin/python tools/probe.py --temp 205

    # Connect by explicit address/UUID instead of scanning by name.
    .venv/bin/python tools/probe.py --address 082FFC1C-1678-8180-F7AB-C8E70E111D20
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

from bleak import BleakScanner

# Load api.py directly by path so we don't trigger the HA package __init__.
_API_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "stagg_ekg_plus"
    / "api.py"
)
_spec = importlib.util.spec_from_file_location("stagg_api", _API_PATH)
assert _spec and _spec.loader
api = importlib.util.module_from_spec(_spec)
sys.modules["stagg_api"] = api
_spec.loader.exec_module(api)


def _print_state(state: "api.KettleState") -> None:
    print(f"  STATE -> {state}")


async def find_device(address: str | None):
    if address:
        print(f"Looking up device {address}...")
        device = await BleakScanner.find_device_by_address(address, timeout=15.0)
        if device is None:
            print(f"Device {address} not found.")
        return device

    print(f"Scanning for a device named {api.NAME_PREFIX}*...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, adv: bool(
            (adv.local_name or "").upper().startswith(api.NAME_PREFIX)
            or api.SERVICE_UUID.lower()
            in [u.lower() for u in (adv.service_uuids or [])]
        ),
        timeout=15.0,
    )
    if device is None:
        print("Kettle not found. Is it powered/advertising and not connected elsewhere?")
    return device


async def main() -> int:
    parser = argparse.ArgumentParser(description="Stagg EKG+ BLE protocol probe")
    parser.add_argument("--address", help="BLE address/UUID to connect to directly")
    parser.add_argument("--power", choices=["on", "off"], help="Set power before listening")
    parser.add_argument("--temp", type=int, help="Set target temp (display units) before listening")
    parser.add_argument("--duration", type=float, default=30.0, help="Listen seconds")
    args = parser.parse_args()

    device = await find_device(args.address)
    if device is None:
        return 1

    print(f"Connecting to {device.address} ({device.name})...")
    client = api.StaggClient(device, on_state=_print_state)

    # Wrap the notify handler to also dump raw frames for calibration.
    original = client._handle_notify

    def _verbose_notify(sender, data):
        print(f"  RAW <- {bytes(data).hex()}")
        original(sender, data)

    client._handle_notify = _verbose_notify  # type: ignore[method-assign]

    await client.connect()
    print("Connected. Authenticated. Listening...\n")

    try:
        if args.power is not None:
            print(f"Sending power {args.power}")
            await client.set_power(args.power == "on")
            await asyncio.sleep(1.0)
        if args.temp is not None:
            print(f"Setting target temp to {args.temp}")
            await client.set_target_temp(args.temp)
            await asyncio.sleep(1.0)

        await asyncio.sleep(args.duration)
    finally:
        print("\nFinal decoded state:")
        print(f"  {client.state}")
        await client.disconnect()
        print("Disconnected.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
