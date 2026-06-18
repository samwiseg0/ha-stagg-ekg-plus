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

"""Watch the Fellow Stagg EKG+ BLE advertisement for state changes.

The kettle is normally controlled over a GATT connection, but this tool only
listens to the broadcast advertisement (no connection). The goal is to find out
whether the kettle encodes anything useful -- e.g. its power state -- in the
advertised manufacturer/service data. If it does, the integration could detect a
physical power-on in on-demand mode without holding a connection.

Usage:
    python3 -m pip install bleak
    python3 tools/adv_watch.py            # only print when the payload changes
    python3 tools/adv_watch.py --all      # print every advertisement packet

While it runs, physically toggle the kettle (off -> on, on -> off, lift off the
base, set hold) and watch whether the printed bytes change. Note the wall-clock
time of each action so it can be lined up with the log. Stop with Ctrl-C.
"""

from __future__ import annotations

import argparse
import asyncio
import time

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

SERVICE_UUID = "00001820-0000-1000-8000-00805f9b34fb"
TARGET_MAC = "00:1C:97:16:46:B9"
NAME_PREFIX = "FELLOW"


def _is_kettle(device: BLEDevice, adv: AdvertisementData) -> bool:
    name = (adv.local_name or device.name or "").upper()
    uuids = [u.lower() for u in (adv.service_uuids or [])]
    return (
        device.address.upper() == TARGET_MAC.upper()
        or SERVICE_UUID.lower() in uuids
        or name.startswith(NAME_PREFIX)
        or "STAGG" in name
    )


def _fmt_bytes(data: bytes) -> str:
    return data.hex(" ") if data else "(empty)"


def _signature(adv: AdvertisementData) -> str:
    """A stable string of just the parts that could carry state."""
    mfr = ";".join(
        f"{cid:04x}:{val.hex()}" for cid, val in sorted(adv.manufacturer_data.items())
    )
    svc = ";".join(
        f"{uuid}:{val.hex()}" for uuid, val in sorted(adv.service_data.items())
    )
    return f"mfr[{mfr}] svc[{svc}]"


def _describe(device: BLEDevice, adv: AdvertisementData) -> str:
    name = adv.local_name or device.name or "(no name)"
    lines = [f"{device.address}  rssi={adv.rssi}  name={name!r}"]
    if adv.manufacturer_data:
        for cid, val in sorted(adv.manufacturer_data.items()):
            lines.append(f"    manufacturer 0x{cid:04x}: {_fmt_bytes(val)}")
    else:
        lines.append("    manufacturer: (none)")
    if adv.service_data:
        for uuid, val in sorted(adv.service_data.items()):
            lines.append(f"    service_data {uuid}: {_fmt_bytes(val)}")
    else:
        lines.append("    service_data: (none)")
    if adv.tx_power is not None:
        lines.append(f"    tx_power: {adv.tx_power}")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="print every packet, not just changes",
    )
    args = parser.parse_args()

    last: dict[str, str] = {}
    start = time.monotonic()

    def callback(device: BLEDevice, adv: AdvertisementData) -> None:
        if not _is_kettle(device, adv):
            return
        sig = _signature(adv)
        if not args.all and last.get(device.address) == sig:
            return
        changed = device.address in last and last[device.address] != sig
        last[device.address] = sig
        stamp = time.strftime("%H:%M:%S")
        elapsed = time.monotonic() - start
        tag = " CHANGED" if changed else ""
        print(f"\n[{stamp} +{elapsed:6.1f}s]{tag}")
        print(_describe(device, adv))

    print("Listening for Fellow Stagg advertisements (active scan). Ctrl-C to stop.")
    print("Toggle the kettle physically and watch for 'CHANGED' lines.\n")
    scanner = BleakScanner(detection_callback=callback, scanning_mode="active")
    await scanner.start()
    try:
        while True:
            await asyncio.sleep(1.0)
    finally:
        await scanner.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
