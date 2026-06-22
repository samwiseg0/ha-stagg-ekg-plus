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


# --- StaggClient internals (no BLE connection) ------------------------------


def test_next_seq_wraps():
    client = api.StaggClient()
    client._seq = 0xFF
    assert client._next_seq() == 0x00


def test_handle_notify_decodes_fragmented_frames():
    seen: list = []
    client = api.StaggClient(on_state=seen.append)
    # Frame split across two notifications: header then payload (as the kettle
    # actually sends it), followed by a separator that closes the frame.
    client._handle_notify(None, bytearray.fromhex("efdd00"))
    client._handle_notify(None, bytearray.fromhex("010100"))
    client._handle_notify(None, bytearray(api.FRAME_SEPARATOR))
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
    with pytest.raises(Exception):
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


async def test_client_disconnect_clears_client():
    from unittest.mock import AsyncMock

    client = api.StaggClient()
    client._client = AsyncMock()
    await client.disconnect()
    assert client._client is None

