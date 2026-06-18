"""Quick BLE scanner to find the Fellow Stagg EKG+ kettle.

On Linux (incl. HA OS) devices show a real MAC address.
On macOS, Core Bluetooth hides the MAC and shows a per-host UUID instead,
so match by advertised name there.

Run:
    python3 -m pip install bleak
    python3 tools/scan.py
"""

import asyncio

from bleak import BleakScanner

# Kettle's known MAC (only resolvable on Linux/HA OS, not macOS).
TARGET_MAC = "00:1C:97:16:46:B9"
SERVICE_UUID = "00001820-0000-1000-8000-00805f9b34fb"


async def main() -> None:
    print("Scanning for 10 seconds...\n")
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)

    for address, (device, adv) in sorted(devices.items()):
        name = adv.local_name or device.name or "(no name)"
        uuids = adv.service_uuids or []
        match = (
            address.upper() == TARGET_MAC.upper()
            or SERVICE_UUID.lower() in [u.lower() for u in uuids]
            or "ekg" in name.lower()
            or "stagg" in name.lower()
        )
        marker = "  <-- likely kettle" if match else ""
        print(f"{address}  rssi={adv.rssi:>4}  name={name!r}{marker}")
        if uuids:
            print(f"    services: {uuids}")


if __name__ == "__main__":
    asyncio.run(main())
