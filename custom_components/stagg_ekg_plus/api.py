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

"""Bluetooth LE client and protocol codec for the Fellow Stagg EKG+ kettle.

This module is intentionally free of any Home Assistant imports so it can be
exercised standalone (see tools/probe.py) and reused unchanged inside the HA
integration.

Protocol summary (reverse engineered by philscott-dev and tlyakhov):
- GATT service:        00001820-0000-1000-8000-00805f9b34fb
- GATT characteristic: 00002A80-0000-1000-8000-00805f9b34fb (write + notify)
- Every rx (state) and tx (command) frame starts with the separator 0xefdd.
- On connect the client must send a fixed "magic" init/auth frame before the
  kettle accepts commands or streams state.

Command frame (8 bytes): ef dd 0a <seq> <type> <value> <checksum> <type>
- seq:      rolling counter, incremented per command (wraps at 256)
- type:     0x00 = power, 0x01 = temperature
- value:    power -> 0x01 on / 0x00 off; temperature -> value in display units
- checksum: (seq + value) & 0xff

State frame: ef dd <type> <payload...> where type is one of STATE_* below.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace

from bleak import BleakClient
from bleak.backends.device import BLEDevice

_LOGGER = logging.getLogger(__name__)

SERVICE_UUID = "00001820-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "00002a80-0000-1000-8000-00805f9b34fb"

# Advertised local name prefix, e.g. "FELLOW46B9".
NAME_PREFIX = "FELLOW"

# Fixed init/authentication frame sent immediately after connecting.
INIT_SEQUENCE = bytes.fromhex("efdd0b3031323334353637383930313233349a6d")

FRAME_SEPARATOR = b"\xef\xdd"

# Command bytes.
CMD = 0x0A
TYPE_POWER = 0x00
TYPE_TEMP = 0x01

# State frame types (first byte after the separator).
STATE_POWER = 0x00
STATE_HOLD_BUTTON = 0x01
STATE_TARGET_TEMP = 0x02
STATE_CURRENT_TEMP = 0x03
STATE_AUTO_OFF_COUNTDOWN = 0x04
# 0x05 is always the bytes ffffffff and 0x07 is always 000000 across every EKG+
# state (power, heating, hold, units, lift); verified constant, nothing to
# decode. Likely fields used by other Fellow models (e.g. the EKG Pro schedule)
# that are inert here. 0x05 doubles as the per-cycle delimiter.
STATE_CYCLE_MARKER = 0x05
STATE_HOLD_MODE = 0x06
STATE_RESERVED_07 = 0x07
STATE_LIFTED = 0x08

# Temperature limits. The EKG+ accepts 40-100 C / 104-212 F; values below the
# minimum are clamped up by the kettle (verified live: 95->104, 100->104 F).
TEMP_MIN_C = 40
TEMP_MAX_C = 100
TEMP_MIN_F = 104
TEMP_MAX_F = 212

# The current-temperature byte reads 0x20 (32) whenever the kettle is not
# actively measuring: powered off, or powered on but lifted off its base. It is
# not a real reading (32 is also out of the operational range), so it is decoded
# as "no reading" (None).
CURRENT_TEMP_OFF_SENTINEL = 0x20


@dataclass(frozen=True)
class KettleState:
    """Decoded snapshot of the kettle's reported state."""

    power: bool | None = None
    # hold (0x06): keep-warm actively engaged (power AND hold slider on). Stable.
    hold: bool | None = None
    # hold_button (0x01): physical hold slider position. Pulses when the element
    # cycles right at setpoint, so it is decoded but not surfaced as an entity.
    hold_button: bool | None = None
    lifted: bool | None = None
    target_temp: int | None = None
    current_temp: int | None = None
    # True = Fahrenheit, False = Celsius, None = unknown.
    fahrenheit: bool | None = None
    # Auto-off countdown in seconds (0x04). Starts at 3600 (60 min) with the hold
    # slider on, or 300 (5 min) without it, and counts down to 0, then the kettle
    # powers off. 0 when not in a hold/auto-off window.
    auto_off_remaining: int | None = None


def build_power_command(seq: int, on: bool) -> bytes:
    """Build a power on/off command frame."""
    value = 0x01 if on else 0x00
    return _build_command(seq, TYPE_POWER, value)


def build_temp_command(seq: int, temp: int) -> bytes:
    """Build a set-target-temperature command frame.

    `temp` is the value in the kettle's current display units.
    """
    return _build_command(seq, TYPE_TEMP, temp & 0xFF)


def _build_command(seq: int, type_: int, value: int) -> bytes:
    seq &= 0xFF
    checksum = (seq + value) & 0xFF
    return bytes([0xEF, 0xDD, CMD, seq, type_, value, checksum, type_])


def parse_frames(buffer: bytearray) -> list[tuple[int, bytes]]:
    """Split a notification buffer into (type, payload) frames.

    Consumes complete frames from `buffer` in place and returns them. A frame is
    everything between two 0xefdd separators; the trailing partial frame (no
    following separator yet) is left in the buffer for the next notification.
    """
    frames: list[tuple[int, bytes]] = []
    # Find separator positions.
    positions = []
    start = 0
    while (idx := buffer.find(FRAME_SEPARATOR, start)) != -1:
        positions.append(idx)
        start = idx + 2
    if len(positions) < 2:
        return frames

    # Each frame spans from one separator up to (not including) the next.
    last_complete = positions[-1]
    for i in range(len(positions) - 1):
        seg = bytes(buffer[positions[i] + 2 : positions[i + 1]])
        if seg:
            frames.append((seg[0], seg[1:]))
    # Keep the trailing (possibly incomplete) frame in the buffer.
    del buffer[:last_complete]
    return frames


def apply_frame(state: KettleState, frame_type: int, payload: bytes) -> KettleState:
    """Return a new KettleState with the given frame applied."""
    if not payload:
        return state
    if frame_type == STATE_POWER:
        return replace(state, power=bool(payload[0]))
    if frame_type == STATE_HOLD_BUTTON:
        return replace(state, hold_button=bool(payload[0]))
    if frame_type == STATE_TARGET_TEMP and len(payload) >= 2:
        return replace(state, target_temp=payload[0], fahrenheit=bool(payload[1]))
    if frame_type == STATE_CURRENT_TEMP and len(payload) >= 2:
        raw = payload[0]
        temp = None if raw == CURRENT_TEMP_OFF_SENTINEL else raw
        return replace(state, current_temp=temp, fahrenheit=bool(payload[1]))
    if frame_type == STATE_HOLD_MODE:
        return replace(state, hold=bool(payload[0]))
    if frame_type == STATE_LIFTED:
        # The one-time init/auth echo also uses type 0x08 but with a longer
        # payload; the periodic state frame is exactly 3 bytes (e.g. 01 01 00).
        # Byte 0x01 = kettle on base, 0x00 = lifted off base (verified live).
        if len(payload) == 3:
            return replace(state, lifted=not bool(payload[0]))
        return state
    if frame_type == STATE_AUTO_OFF_COUNTDOWN:
        # 16-bit little-endian seconds, sent as [lo, hi] (repeated). The kettle's
        # auto-off countdown: 3600 (60 min) with hold on, 300 (5 min) without.
        if len(payload) >= 2:
            return replace(state, auto_off_remaining=payload[0] | (payload[1] << 8))
        return replace(state, auto_off_remaining=payload[0])
    return state


class StaggClient:
    """Manages a BLE connection to the kettle and decodes its state."""

    def __init__(
        self,
        device: BLEDevice | str | None = None,
        on_state: Callable[[KettleState], None] | None = None,
    ) -> None:
        self._device = device
        self._on_state = on_state
        self._client: BleakClient | None = None
        self._buffer = bytearray()
        self._seq = 0
        self.state = KettleState()

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def connect(self) -> None:
        """Connect to `device`, then authenticate and subscribe.

        Convenience path for standalone use. Inside Home Assistant the
        coordinator establishes the connection itself and calls `start()`.
        """
        if self._device is None:
            raise RuntimeError("No device provided")
        client = BleakClient(self._device)
        await client.connect()
        await self.start(client)

    async def start(self, client: BleakClient) -> None:
        """Authenticate and subscribe on an already-connected client."""
        self._client = client
        self._buffer.clear()
        self._seq = 0
        await client.start_notify(CHAR_UUID, self._handle_notify)
        await self._write(INIT_SEQUENCE)
        _LOGGER.info("Authenticated and subscribed to kettle notifications")

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            finally:
                self._client = None

    async def set_power(self, on: bool) -> None:
        await self._write(build_power_command(self._next_seq(), on))

    async def set_target_temp(self, temp: int) -> None:
        await self._write(build_temp_command(self._next_seq(), temp))

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFF
        return self._seq

    async def _write(self, data: bytes) -> None:
        if self._client is None:
            raise RuntimeError("Not connected")
        await self._client.write_gatt_char(CHAR_UUID, data, response=False)

    def _handle_notify(self, _sender: object, data: bytearray) -> None:
        # Raw frames are logged at debug level so the protocol can be inspected
        # live from within Home Assistant (enable debug logging on the
        # integration). Useful for decoding still-unknown bytes.
        _LOGGER.debug("rx %s", data.hex())
        self._buffer.extend(data)
        changed = False
        for frame_type, payload in parse_frames(self._buffer):
            _LOGGER.debug("frame 0x%02x %s", frame_type, payload.hex())
            new_state = apply_frame(self.state, frame_type, payload)
            if new_state != self.state:
                self.state = new_state
                changed = True
        if changed:
            _LOGGER.debug("state %s", self.state)
            if self._on_state is not None:
                self._on_state(self.state)
