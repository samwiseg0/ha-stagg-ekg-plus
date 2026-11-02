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

"""Unit tests for the pure protocol codec in api.py.

api.py has no Home Assistant imports, so it is loaded standalone (by path) and
tested with plain pytest -- no Home Assistant install required.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import sys
from pathlib import Path

import pytest

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


def _buffer(*frames: tuple[int, str]) -> bytearray:
    """Build a notification buffer from (type, payload_hex) frames.

    A trailing separator is appended so the final frame is complete and gets
    returned by parse_frames (which keeps the trailing partial frame).
    """
    buf = bytearray()
    for frame_type, payload_hex in frames:
        buf += api.FRAME_SEPARATOR + bytes([frame_type]) + bytes.fromhex(payload_hex)
    buf += api.FRAME_SEPARATOR
    return buf


# --- command building -------------------------------------------------------


def test_build_power_command_matches_captured_frames():
    assert api.build_power_command(0, True).hex() == "efdd0a0000010100"
    assert api.build_power_command(4, False).hex() == "efdd0a0400000400"


def test_build_power_command_structure():
    frame = api.build_power_command(7, True)
    assert frame[0:2] == b"\xef\xdd"
    assert frame[2] == api.CMD
    assert frame[3] == 7  # seq
    assert frame[4] == api.TYPE_POWER
    assert frame[5] == 0x01  # on
    assert frame[6] == (7 + 1) & 0xFF  # checksum
    assert frame[7] == api.TYPE_POWER


def test_build_temp_command_structure_and_checksum():
    frame = api.build_temp_command(3, 205)
    assert frame[2] == api.CMD
    assert frame[3] == 3
    assert frame[4] == api.TYPE_TEMP
    assert frame[5] == 205
    assert frame[6] == (3 + 205) & 0xFF
    assert frame[7] == api.TYPE_TEMP


def test_command_seq_wraps_at_256():
    frame = api.build_power_command(256, True)
    assert frame[3] == 0  # seq & 0xFF


def test_temp_command_value_masked_to_byte():
    frame = api.build_temp_command(0, 0x1FF)
    assert frame[5] == 0xFF


# --- parse_frames -----------------------------------------------------------


def test_parse_frames_empty_buffer():
    buf = bytearray()
    assert api.parse_frames(buf) == []


def test_parse_frames_single_separator_keeps_buffer():
    buf = bytearray(b"\xef\xdd\x00\x01")
    assert api.parse_frames(buf) == []
    assert buf == b"\xef\xdd\x00\x01"  # untouched, waiting for next separator


def test_parse_frames_returns_type_and_payload():
    buf = _buffer((0x02, "d001d001"))
    frames = api.parse_frames(buf)
    assert frames == [(0x02, bytes.fromhex("d001d001"))]


def test_parse_frames_multiple_and_retains_trailing():
    buf = bytearray()
    buf += api.FRAME_SEPARATOR + bytes([0x00]) + bytes.fromhex("010100")
    buf += api.FRAME_SEPARATOR + bytes([0x02]) + bytes.fromhex("d001d001")
    # No trailing separator: the last frame is incomplete and kept.
    frames = api.parse_frames(buf)
    assert frames == [(0x00, bytes.fromhex("010100"))]
    # The 0x02 frame remains buffered for the next notification.
    assert buf == api.FRAME_SEPARATOR + bytes([0x02]) + bytes.fromhex("d001d001")


def test_parse_frames_consecutive_separators_skip_empty():
    buf = api.FRAME_SEPARATOR + api.FRAME_SEPARATOR + bytes([0x00]) + b"\x01"
    buf = bytearray(buf) + api.FRAME_SEPARATOR
    frames = api.parse_frames(buf)
    # Empty segment between back-to-back separators is skipped.
    assert frames == [(0x00, b"\x01")]


# --- apply_frame ------------------------------------------------------------


def test_apply_frame_empty_payload_is_noop():
    state = api.KettleState(power=True)
    assert api.apply_frame(state, api.STATE_POWER, b"") == state


def test_apply_frame_power():
    on = api.apply_frame(api.KettleState(), api.STATE_POWER, b"\x01")
    off = api.apply_frame(api.KettleState(), api.STATE_POWER, b"\x00")
    assert on.power is True
    assert off.power is False


def test_apply_frame_hold_button():
    s = api.apply_frame(api.KettleState(), api.STATE_HOLD_BUTTON, b"\x01")
    assert s.hold_button is True


def test_apply_frame_target_temp_fahrenheit():
    s = api.apply_frame(api.KettleState(), api.STATE_TARGET_TEMP, bytes([0xD0, 0x01]))
    assert s.target_temp == 208
    assert s.fahrenheit is True


def test_apply_frame_current_temp_celsius():
    s = api.apply_frame(api.KettleState(), api.STATE_CURRENT_TEMP, bytes([0x53, 0x00]))
    assert s.current_temp == 83
    assert s.fahrenheit is False


def test_apply_frame_current_temp_off_sentinel():
    s = api.apply_frame(
        api.KettleState(),
        api.STATE_CURRENT_TEMP,
        bytes([api.CURRENT_TEMP_OFF_SENTINEL, 0x01]),
    )
    assert s.current_temp is None
    assert s.fahrenheit is True


def test_apply_frame_hold_mode():
    s = api.apply_frame(api.KettleState(), api.STATE_HOLD_MODE, b"\x00\x00\x00")
    assert s.hold is False


def test_apply_frame_lifted_three_byte_on_base():
    s = api.apply_frame(api.KettleState(), api.STATE_LIFTED, bytes([0x01, 0x01, 0x00]))
    assert s.lifted is False  # 0x01 = on base


def test_apply_frame_lifted_three_byte_off_base():
    s = api.apply_frame(api.KettleState(), api.STATE_LIFTED, bytes([0x00, 0x00, 0x00]))
    assert s.lifted is True  # 0x00 = lifted


def test_apply_frame_lifted_oversized_auth_echo_ignored():
    s = api.apply_frame(
        api.KettleState(),
        api.STATE_LIFTED,
        bytes.fromhex("09640202000f0100000c75"),
    )
    assert s.lifted is None  # not the 3-byte state frame


def test_apply_frame_lifted_unexpected_length_ignored():
    # Neither the 3-byte state frame nor the ~11-byte auth echo: left unchanged
    # (and debug-logged so a firmware change is visible).
    s = api.apply_frame(api.KettleState(), api.STATE_LIFTED, bytes([0x01, 0x01]))
    assert s.lifted is None


def test_apply_frame_auto_off_16bit_le():
    s = api.apply_frame(
        api.KettleState(), api.STATE_AUTO_OFF_COUNTDOWN, bytes([0x10, 0x0E, 0x10, 0x0E])
    )
    assert s.auto_off_remaining == 3600  # 0x0E10


def test_apply_frame_auto_off_short_payload_ignored():
    s = api.apply_frame(api.KettleState(), api.STATE_AUTO_OFF_COUNTDOWN, b"\x10")
    assert s.auto_off_remaining is None


@pytest.mark.parametrize("frame_type", [api.STATE_CYCLE_MARKER, api.STATE_RESERVED_07])
def test_apply_frame_constant_markers_do_not_change_state(frame_type):
    state = api.KettleState(power=True, target_temp=208)
    assert api.apply_frame(state, frame_type, b"\xff\xff\xff\xff") == state


# --- end-to-end decode of a real capture ------------------------------------


def test_decode_real_capture_cycle():
    """One full cycle from the 2026-06-22 hardware capture (kettle on, 208F)."""
    buf = _buffer(
        (0x08, "010100"),  # on base
        (0x06, "000000"),  # hold mode
        (0x07, "000000"),  # reserved
        (0x04, "00000000"),  # auto-off 0
        (0x05, "ffffffff"),  # marker
        (0x03, "53015301"),  # current 83F
        (0x02, "d001d001"),  # target 208F
        (0x00, "010100"),  # power on
        (0x01, "010100"),  # hold button on
    )
    state = api.KettleState()
    for frame_type, payload in api.parse_frames(buf):
        state = api.apply_frame(state, frame_type, payload)

    assert state.power is True
    assert state.target_temp == 208
    assert state.current_temp == 83
    assert state.fahrenheit is True
    assert state.lifted is False
    assert state.hold_button is True
    assert state.auto_off_remaining == 0


# --- lost notifications ------------------------------------------------------

# One idle cycle from a 2026-11-02 capture (kettle off, target 93 C), in the
# order the kettle streams it.
IDLE_CYCLE_93C = [
    (0x04, "00000000"),
    (0x05, "ffffffff"),
    (0x03, "00000000"),
    (0x02, "5d005d00"),
    (0x00, "000000"),
    (0x01, "010100"),
    (0x06, "000000"),
    (0x07, "000000"),
    (0x08, "010100"),
]


def _notifications(cycle, cycles=1):
    """The notifications the kettle sends: each frame's header, then its payload."""
    out = []
    for _ in range(cycles):
        for frame_type, payload_hex in cycle:
            out.append(api.FRAME_SEPARATOR + bytes([frame_type]))
            out.append(bytes.fromhex(payload_hex))
    return out


def _notify(client, cycle, cycles=1, drop=()):
    """Feed cycles to the client, dropping the notifications at the given indexes."""
    for i, data in enumerate(_notifications(cycle, cycles)):
        if i not in drop:
            client._handle_notify(None, bytearray(data))


def _index(cycle, frame_type, payload=False, cycle_no=1):
    """Notification index of a frame's header (or payload) in the given cycle."""
    pos = [t for t, _ in cycle].index(frame_type)
    return (cycle_no * len(cycle) + pos) * 2 + int(payload)


def _decoded(drop):
    """States decoded after a first, intact cycle, with the given notifications lost.

    Indexes in `drop` count from the start of the first cycle; the first cycle
    only fills in the state, so aim them at the second (see _index).
    """
    seen: list = []
    client = api.StaggClient(on_state=seen.append)
    first = len(IDLE_CYCLE_93C) * 2
    for i, data in enumerate(_notifications(IDLE_CYCLE_93C, cycles=3)):
        if i == first:
            # The first cycle's last frame is applied by the next header.
            client._handle_notify(None, bytearray(data))
            warm = len(seen)
            continue
        if i not in drop:
            client._handle_notify(None, bytearray(data))
    return seen[warm:], client.state


def test_intact_stream_decodes():
    seen, state = _decoded(drop=())
    assert seen == []
    assert state.target_temp == 93
    assert state.current_temp == 0
    assert state.fahrenheit is False
    assert state.power is False
    assert state.lifted is False


def test_lost_notifications_never_change_state():
    """Every run of one to four lost notifications leaves the decoded state alone.

    Those are what produced bogus readings live: the target's 5d005d00 under
    the current temperature header (93), the hold button's 010100 under the
    target header (1 F, which also flipped both readings to Fahrenheit), the
    marker's ffffffff as a 255 F target, and a power-off during a boil.
    """
    _, intact = _decoded(drop=())
    total = len(IDLE_CYCLE_93C) * 2
    for length in range(1, 5):
        for start in range(total + 1, 2 * total):
            seen, state = _decoded(drop=range(start, start + length))
            assert seen == [] and state == intact, (start, length, seen)


def test_current_temp_not_taken_from_target_payload():
    # Lose the current temperature's payload and the target's header: the
    # target payload then follows the current temperature header.
    drop = (
        _index(IDLE_CYCLE_93C, 0x03, payload=True),
        _index(IDLE_CYCLE_93C, 0x02),
    )
    seen, state = _decoded(drop)
    assert seen == [] and state.current_temp == 0


def test_target_not_taken_from_hold_button_payload():
    drop = range(
        _index(IDLE_CYCLE_93C, 0x02, payload=True),
        _index(IDLE_CYCLE_93C, 0x01, payload=True),
    )
    seen, state = _decoded(drop)
    assert seen == [] and state.fahrenheit is False and state.target_temp == 93


def test_frame_waits_for_next_header():
    seen: list = []
    client = api.StaggClient(on_state=seen.append)
    client._handle_notify(None, bytearray.fromhex("efdd00"))
    client._handle_notify(None, bytearray.fromhex("010100"))
    # A separator without the next frame's type yet: the frame is held back.
    client._handle_notify(None, bytearray(api.FRAME_SEPARATOR))
    assert seen == []
    client._handle_notify(None, bytearray(b"\x01"))
    assert seen[-1].power is True


@pytest.mark.parametrize(
    ("frame_type", "payload", "next_type", "intact"),
    [
        (0x02, "5d005d00", 0x00, True),
        (0x03, "53015301", 0x02, True),
        (0x02, "5d005d00", 0x01, False),  # next frame missing
        (0x03, "5d005d00", 0x00, False),  # target payload under current header
        (0x02, "010100", 0x00, False),  # wrong length
        (0x02, "5d005e00", 0x00, False),  # value not repeated
        (0x02, "ffffffff", 0x00, False),  # not a unit
        (0x04, "100e100e", 0x05, True),
        (0x08, "010100", 0x04, True),
        (0x08, "09640202000f0100000c75", 0x04, False),  # auth echo
        (0x0B, "00", 0x04, False),  # unknown frame type
    ],
)
def test_frame_is_intact(frame_type, payload, next_type, intact):
    assert api.frame_is_intact(frame_type, bytes.fromhex(payload), next_type) is intact


# --- StaggClient internals (no BLE connection) ------------------------------


def test_next_seq_wraps():
    client = api.StaggClient()
    client._seq = 0xFF
    assert client._next_seq() == 0x00


def test_handle_notify_decodes_fragmented_frames():
    seen: list = []
    client = api.StaggClient(on_state=seen.append)
    # Frame split across two notifications: header then payload (as the kettle
    # actually sends it), closed by the next frame's header.
    client._handle_notify(None, bytearray.fromhex("efdd00"))
    client._handle_notify(None, bytearray.fromhex("010100"))
    client._handle_notify(None, bytearray.fromhex("efdd01"))
    assert seen and seen[-1].power is True


def test_handle_notify_buffer_is_bounded_on_garbage():
    client = api.StaggClient()
    # Feed a long separatorless garbage stream; the buffer must not grow without
    # bound.
    client._handle_notify(None, bytearray(b"\x11" * (api._MAX_BUFFER * 3)))
    assert len(client._buffer) <= api._MAX_BUFFER


def test_handle_notify_trims_to_last_separator():
    client = api.StaggClient()
    # An oversized buffer that does contain a separator (but not two complete
    # frames) is trimmed back to that separator rather than fully cleared, so a
    # partial frame straddling notifications survives.
    data = bytearray(b"\x11" * (api._MAX_BUFFER + 50))
    data += bytearray(api.FRAME_SEPARATOR)
    data += b"\x22" * 4
    client._handle_notify(None, data)
    assert bytes(client._buffer).startswith(bytes(api.FRAME_SEPARATOR))
    assert len(client._buffer) <= api._MAX_BUFFER


def test_kettlestate_is_frozen():
    state = api.KettleState()
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.power = True  # type: ignore[misc]


# --- StaggClient connection wrapper -----------------------------------------


async def test_client_connect_requires_device():
    client = api.StaggClient()
    with pytest.raises(RuntimeError):
        await client.connect()


async def test_client_connect_uses_bleak_client():
    from unittest.mock import AsyncMock, MagicMock, patch

    fake = AsyncMock()
    fake.is_connected = True
    client = api.StaggClient(device="AA:BB:CC:DD:EE:FF")
    with patch.object(api, "BleakClient", MagicMock(return_value=fake)):
        await client.connect()
    fake.connect.assert_awaited_once()
    fake.start_notify.assert_awaited_once()  # start() ran on the new client
    assert client.is_connected


async def test_client_start_subscribes_and_authenticates():
    from unittest.mock import AsyncMock

    client = api.StaggClient()
    fake = AsyncMock()
    fake.is_connected = True
    await client.start(fake)
    fake.start_notify.assert_awaited_once()
    fake.write_gatt_char.assert_awaited()  # the auth/init write
    assert client.is_connected


async def test_client_start_cleans_up_on_failure():
    from unittest.mock import AsyncMock

    client = api.StaggClient()
    fake = AsyncMock()
    fake.start_notify.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        await client.start(fake)
    assert client._client is None
    fake.disconnect.assert_awaited_once()


async def test_client_set_power_writes_command():
    from unittest.mock import AsyncMock

    client = api.StaggClient()
    client._client = AsyncMock()
    await client.set_power(True)
    client._client.write_gatt_char.assert_awaited()


async def test_client_set_target_temp_writes_command():
    from unittest.mock import AsyncMock

    client = api.StaggClient()
    client._client = AsyncMock()
    await client.set_target_temp(205)
    client._client.write_gatt_char.assert_awaited()


async def test_client_write_requires_connection():
    client = api.StaggClient()
    with pytest.raises(RuntimeError):
        await client.set_power(True)


async def test_client_write_serializes_concurrent_commands():
    """The write lock prevents switch and climate commands from interleaving."""
    from unittest.mock import AsyncMock

    client = api.StaggClient()
    client._client = AsyncMock(is_connected=True)
    phases: list[str] = []

    async def _slow_write(_uuid, _data, response=False):
        phases.append("start")
        await asyncio.sleep(0)  # yield: an unlocked write would interleave here
        phases.append("end")

    client._client.write_gatt_char.side_effect = _slow_write
    await asyncio.gather(client.set_power(True), client.set_target_temp(200))
    # Serialized: each start is immediately followed by its own end.
    assert phases == ["start", "end", "start", "end"]


async def test_client_write_retries_transient_dbus_error():
    from unittest.mock import AsyncMock

    from bleak.exc import BleakDBusError

    client = api.StaggClient()
    client._client = AsyncMock(is_connected=True)
    client._client.write_gatt_char.side_effect = [
        BleakDBusError("org.bluez.Error.InProgress", []),
        None,  # succeeds on the second attempt (first backoff is 0.0s)
    ]
    await client.set_power(True)
    assert client._client.write_gatt_char.await_count == 2


async def test_client_write_raises_on_non_retryable_dbus_error():
    from unittest.mock import AsyncMock

    from bleak.exc import BleakDBusError

    client = api.StaggClient()
    client._client = AsyncMock(is_connected=True)
    client._client.write_gatt_char.side_effect = BleakDBusError(
        "org.bluez.Error.NotConnected", []
    )
    with pytest.raises(BleakDBusError):
        await client.set_power(True)
    client._client.write_gatt_char.assert_awaited_once()


async def test_client_write_rereads_client_each_retry():
    """A reconnect that swaps self._client mid-retry is targeted, not the stale one."""
    from unittest.mock import AsyncMock, patch

    from bleak.exc import BleakDBusError

    client = api.StaggClient()
    old = AsyncMock(is_connected=True)
    new = AsyncMock(is_connected=True)
    client._client = old

    async def _fail_then_swap(_uuid, _data, response=False):
        # Simulate a keep-alive drop + reconnect replacing the client during the
        # backoff: the first (stale) handle fails transiently, then is swapped.
        client._client = new
        raise BleakDBusError("org.bluez.Error.InProgress", [])

    old.write_gatt_char.side_effect = _fail_then_swap
    with patch.object(api.asyncio, "sleep", AsyncMock()):
        await client.set_power(True)
    # The retry went to the fresh client, not the dead one.
    old.write_gatt_char.assert_awaited_once()
    new.write_gatt_char.assert_awaited_once()


async def test_client_write_aborts_if_client_dropped_mid_retry():
    """A disconnect that nulls the client during the backoff aborts the retry."""
    from unittest.mock import AsyncMock, patch

    from bleak.exc import BleakDBusError

    client = api.StaggClient()
    first = AsyncMock(is_connected=True)
    client._client = first

    async def _fail_then_drop(_uuid, _data, response=False):
        client._client = None  # simulate a disconnect during the write
        raise BleakDBusError("org.bluez.Error.InProgress", [])

    first.write_gatt_char.side_effect = _fail_then_drop
    with (
        patch.object(api.asyncio, "sleep", AsyncMock()),
        pytest.raises(RuntimeError),
    ):
        await client.set_power(True)


async def test_client_write_retry_exhausted_raises():
    from unittest.mock import AsyncMock, patch

    from bleak.exc import BleakDBusError

    client = api.StaggClient()
    client._client = AsyncMock(is_connected=True)
    client._client.write_gatt_char.side_effect = BleakDBusError(
        "org.bluez.Error.Failed", []
    )
    with (
        patch.object(api.asyncio, "sleep", AsyncMock()),
        pytest.raises(BleakDBusError),
    ):
        await client.set_power(True)
    # One attempt per backoff entry, then it gives up.
    assert client._client.write_gatt_char.await_count == len(api._WRITE_RETRY_BACKOFF)


async def test_client_disconnect_clears_client():
    from unittest.mock import AsyncMock

    client = api.StaggClient()
    client._client = AsyncMock()
    await client.disconnect()
    assert client._client is None
