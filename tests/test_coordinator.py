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

"""Tests for the StaggCoordinator connection logic.

The coordinator is constructed directly (no Bluetooth stack) and its scheduling
methods are patched where needed so no real timers linger.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stagg_ekg_plus.api import KettleState
from custom_components.stagg_ekg_plus.const import (
    CONF_CONNECTION_MODE,
    CONF_POLL_INTERVAL,
    CONNECTION_MODE_ON_DEMAND,
    CONNECTION_MODE_PERSISTENT,
    DOMAIN,
)
from custom_components.stagg_ekg_plus.coordinator import StaggCoordinator

ADDRESS = "00:1C:97:16:46:B9"
_BT = "custom_components.stagg_ekg_plus.coordinator.bluetooth"
_CO = "custom_components.stagg_ekg_plus.coordinator"


def _now() -> datetime:
    return datetime(2026, 6, 22, 12, 0, 0)


def _coordinator(
    hass: HomeAssistant,
    *,
    mode: str = CONNECTION_MODE_ON_DEMAND,
    poll: str = "0",
) -> StaggCoordinator:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        data={CONF_ADDRESS: ADDRESS},
        options={CONF_CONNECTION_MODE: mode, CONF_POLL_INTERVAL: poll},
    )
    entry.add_to_hass(hass)
    return StaggCoordinator(hass, entry, ADDRESS)


def test_wants_connection_persistent(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    assert coord._wants_connection() is True


def test_wants_connection_on_demand_follows_power(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND)
    assert coord._wants_connection() is False  # no data yet
    coord.async_set_updated_data(KettleState(power=True))
    assert coord._wants_connection() is True
    coord.async_set_updated_data(KettleState(power=False))
    assert coord._wants_connection() is False


def test_available_persistent_tracks_connection(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = MagicMock(is_connected=False)
    assert coord.available is False
    coord._client = MagicMock(is_connected=True)
    assert coord.available is True


def test_available_on_demand_tracks_data(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND)
    assert coord.available is False
    coord.async_set_updated_data(KettleState())
    assert coord.available is True


def test_is_connected_property(hass: HomeAssistant) -> None:
    coord = _coordinator(hass)
    coord._client = MagicMock(is_connected=True)
    assert coord.is_connected is True


def test_handle_state_clears_probe_when_powered_on(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND)
    coord._probing = True
    coord._probe_started = 1.0
    with (
        patch.object(coord, "_cancel_idle_disconnect_timer") as cancel,
        patch.object(coord, "_reset_keepalive"),
    ):
        coord._handle_state(KettleState(power=True))
    assert coord.data.power is True
    assert coord._probing is False
    cancel.assert_called_once()


def test_handle_state_off_schedules_idle(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND)
    with (
        patch.object(coord, "_schedule_idle_disconnect") as idle,
        patch.object(coord, "_reset_keepalive"),
    ):
        coord._handle_state(KettleState(power=False))
    assert coord.data.power is False
    idle.assert_called_once()


async def test_set_power_sends_command(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = AsyncMock(is_connected=True)
    with patch.object(coord, "_ensure_connected", AsyncMock()):
        await coord.async_set_power(True)
    coord._client.set_power.assert_awaited_once_with(True)


async def test_set_target_temp_sends_command(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = AsyncMock(is_connected=True)
    with patch.object(coord, "_ensure_connected", AsyncMock()):
        await coord.async_set_target_temp(205)
    coord._client.set_target_temp.assert_awaited_once_with(205)


async def test_command_raises_translatable_error(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = MagicMock(is_connected=False)
    with (
        patch.object(coord, "_ensure_connected", AsyncMock()),
        pytest.raises(HomeAssistantError) as err,
    ):
        await coord.async_set_power(True)
    assert err.value.translation_key == "not_reachable"


def test_on_disconnect_intentional_when_off(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND)
    coord._connected_since = 1.0
    coord._probing = True
    with (
        patch.object(coord, "_schedule_poll") as poll,
        patch.object(coord, "_schedule_reconnect") as reconnect,
    ):
        coord._on_disconnect(MagicMock())
    assert coord._probing is False
    poll.assert_called_once()
    reconnect.assert_not_called()


def test_on_disconnect_reconnects_when_wanted(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._connected_since = 1.0
    with (
        patch.object(coord, "_schedule_poll") as poll,
        patch.object(coord, "_schedule_reconnect") as reconnect,
    ):
        coord._on_disconnect(MagicMock())
    reconnect.assert_called_once()
    poll.assert_not_called()


def test_on_disconnect_ignored_before_session(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._connected_since = None
    with patch.object(coord, "_schedule_reconnect") as reconnect:
        coord._on_disconnect(MagicMock())
    reconnect.assert_not_called()


def test_get_ble_device_prefers_live(hass: HomeAssistant) -> None:
    coord = _coordinator(hass)
    device = object()
    with patch(f"{_BT}.async_ble_device_from_address", return_value=device):
        assert coord._get_ble_device() is device


def test_get_ble_device_falls_back_to_service_info(hass: HomeAssistant) -> None:
    coord = _coordinator(hass)
    service_info = MagicMock()
    with (
        patch(f"{_BT}.async_ble_device_from_address", return_value=None),
        patch(f"{_BT}.async_last_service_info", return_value=service_info),
    ):
        assert coord._get_ble_device() is service_info.device


def test_get_ble_device_none(hass: HomeAssistant) -> None:
    coord = _coordinator(hass)
    with (
        patch(f"{_BT}.async_ble_device_from_address", return_value=None),
        patch(f"{_BT}.async_last_service_info", return_value=None),
    ):
        assert coord._get_ble_device() is None


async def test_async_start_on_demand_schedules_poll(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND, poll="120")
    coord._client = MagicMock(is_connected=False)
    with (
        patch(f"{_BT}.async_register_callback", return_value=MagicMock()),
        patch.object(coord, "_ensure_connected", AsyncMock()),
        patch.object(coord, "_schedule_poll") as poll,
    ):
        await coord.async_start()
    poll.assert_called_once()


async def test_async_stop_disconnects(hass: HomeAssistant) -> None:
    coord = _coordinator(hass)
    coord._client = AsyncMock()
    await coord.async_stop()
    assert coord._stopping is True
    coord._client.disconnect.assert_awaited_once()


async def test_ensure_connected_success(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    fake_client = MagicMock()
    with (
        patch.object(coord, "_get_ble_device", return_value=MagicMock()),
        patch(f"{_CO}.establish_connection", AsyncMock(return_value=fake_client)),
        patch.object(coord._client, "start", AsyncMock()) as start,
        patch.object(coord, "_reset_keepalive") as reset,
    ):
        await coord._ensure_connected()
    start.assert_awaited_once_with(fake_client)
    reset.assert_called_once()
    assert coord._connected_since is not None


async def test_ensure_connected_no_device(hass: HomeAssistant) -> None:
    coord = _coordinator(hass)
    with patch.object(coord, "_get_ble_device", return_value=None):
        await coord._ensure_connected()
    assert coord._connected_since is None


async def test_ensure_connected_reload_race(hass: HomeAssistant) -> None:
    coord = _coordinator(hass)
    fake_client = AsyncMock()

    async def _establish(*args, **kwargs):
        coord._stopping = True
        return fake_client

    with (
        patch.object(coord, "_get_ble_device", return_value=MagicMock()),
        patch(f"{_CO}.establish_connection", _establish),
        patch.object(coord._client, "start", AsyncMock()) as start,
    ):
        await coord._ensure_connected()
    fake_client.disconnect.assert_awaited_once()
    start.assert_not_awaited()


async def test_async_reconnect_reschedules_on_failure(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = MagicMock(is_connected=False)
    with (
        patch.object(coord, "_ensure_connected", AsyncMock(side_effect=Exception("x"))),
        patch.object(coord, "_schedule_reconnect") as resched,
    ):
        await coord._async_reconnect()
    resched.assert_called_once()


async def test_async_probe_reschedules_when_unreachable(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND, poll="120")
    coord._client = MagicMock(is_connected=False)
    with (
        patch.object(coord, "_ensure_connected", AsyncMock()),
        patch.object(coord, "_schedule_poll") as poll,
    ):
        await coord._async_probe()
    assert coord._probing is False
    poll.assert_called_once()


def test_keepalive_timer_fired_drops_link(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = MagicMock(is_connected=True)
    with (
        patch.object(coord, "_async_disconnect", MagicMock(return_value=None)),
        patch.object(coord.config_entry, "async_create_background_task") as task,
    ):
        coord._keepalive_timer_fired(_now())
    assert coord._stale_disconnect is True
    task.assert_called_once()


def test_idle_disconnect_fired_drops_when_off(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND)
    coord._client = MagicMock(is_connected=True)
    with (
        patch.object(coord, "_async_disconnect", MagicMock(return_value=None)),
        patch.object(coord.config_entry, "async_create_background_task") as task,
    ):
        coord._idle_disconnect_fired(_now())
    task.assert_called_once()


def test_reconnect_timer_fired_triggers_reconnect(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = MagicMock(is_connected=False)
    with (
        patch.object(coord, "_async_reconnect", MagicMock(return_value=None)),
        patch.object(coord.config_entry, "async_create_background_task") as task,
    ):
        coord._reconnect_timer_fired(_now())
    task.assert_called_once()


def test_poll_timer_fired_triggers_probe(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND, poll="120")
    coord._client = MagicMock(is_connected=False)
    with (
        patch.object(coord, "_async_probe", MagicMock(return_value=None)),
        patch.object(coord.config_entry, "async_create_background_task") as task,
    ):
        coord._poll_timer_fired(_now())
    task.assert_called_once()


def test_schedule_idle_disconnect_arms(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND)
    with patch(f"{_CO}.async_call_later", return_value=MagicMock()) as later:
        coord._schedule_idle_disconnect()
    later.assert_called_once()
    assert coord._cancel_idle_disconnect is not None


def test_schedule_poll_arms_when_enabled(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND, poll="120")
    coord._client = MagicMock(is_connected=False)
    with patch(f"{_CO}.async_call_later", return_value=MagicMock()) as later:
        coord._schedule_poll()
    later.assert_called_once()


def test_schedule_poll_noop_when_disabled(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND, poll="0")
    coord._client = MagicMock(is_connected=False)
    with patch(f"{_CO}.async_call_later", return_value=MagicMock()) as later:
        coord._schedule_poll()
    later.assert_not_called()


def test_reset_keepalive_arms_when_connected(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = MagicMock(is_connected=True)
    with patch(f"{_CO}.async_call_later", return_value=MagicMock()) as later:
        coord._reset_keepalive()
    later.assert_called_once()


def test_arm_idle_after_command_on_demand_off(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND)
    with patch.object(coord, "_schedule_idle_disconnect") as idle:
        coord._arm_idle_disconnect_after_command()
    idle.assert_called_once()


def test_on_bluetooth_event_triggers_reconnect(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = MagicMock(is_connected=False)
    with (
        patch.object(coord, "_async_reconnect", MagicMock(return_value=None)),
        patch.object(coord.config_entry, "async_create_background_task") as task,
    ):
        coord._on_bluetooth_event(MagicMock(), MagicMock())
    task.assert_called_once()


def test_format_duration() -> None:
    from custom_components.stagg_ekg_plus.coordinator import _format_duration

    assert _format_duration(5) == "5s"
    assert _format_duration(61) == "1m 1s"
    assert _format_duration(3661) == "1h 1m 1s"


def test_cancel_timer_helpers(hass: HomeAssistant) -> None:
    coord = _coordinator(hass)
    cancels = {}
    for attr, method in (
        ("_cancel_keepalive", coord._cancel_keepalive_timer),
        ("_cancel_idle_disconnect", coord._cancel_idle_disconnect_timer),
        ("_cancel_poll", coord._cancel_poll_timer),
        ("_cancel_reconnect", coord._cancel_pending_reconnect),
    ):
        cancel = MagicMock()
        setattr(coord, attr, cancel)
        method()
        cancel.assert_called_once()
        assert getattr(coord, attr) is None
        cancels[attr] = cancel


def test_keepalive_timer_fired_noop_when_stopping(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = MagicMock(is_connected=True)
    coord._stopping = True
    with patch.object(coord.config_entry, "async_create_background_task") as task:
        coord._keepalive_timer_fired(_now())
    task.assert_not_called()


def test_idle_disconnect_fired_noop_when_wanted(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)  # always wants
    coord._client = MagicMock(is_connected=True)
    with patch.object(coord.config_entry, "async_create_background_task") as task:
        coord._idle_disconnect_fired(_now())
    task.assert_not_called()


def test_reconnect_timer_fired_noop_when_connected(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = MagicMock(is_connected=True)
    with patch.object(coord.config_entry, "async_create_background_task") as task:
        coord._reconnect_timer_fired(_now())
    task.assert_not_called()


def test_poll_timer_fired_reschedules_when_online(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND, poll="120")
    coord._client = MagicMock(is_connected=True)
    with (
        patch.object(coord, "_schedule_poll") as poll,
        patch.object(coord.config_entry, "async_create_background_task") as task,
    ):
        coord._poll_timer_fired(_now())
    poll.assert_called_once()
    task.assert_not_called()


def test_schedule_reconnect_arms_with_backoff(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    with patch(f"{_CO}.async_call_later", return_value=MagicMock()) as later:
        coord._schedule_reconnect()
    later.assert_called_once()
    assert coord._reconnect_attempt == 1


def test_reset_keepalive_cancels_when_not_wanted(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND)  # off -> not wanted
    coord._client = MagicMock(is_connected=True)
    cancel = MagicMock()
    coord._cancel_keepalive = cancel
    with patch(f"{_CO}.async_call_later", return_value=MagicMock()) as later:
        coord._reset_keepalive()
    cancel.assert_called_once()
    later.assert_not_called()


def test_on_disconnect_stale_branch(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._connected_since = 1.0
    coord._stale_disconnect = True
    with patch.object(coord, "_schedule_reconnect") as reconnect:
        coord._on_disconnect(MagicMock())
    reconnect.assert_called_once()
    assert coord._stale_disconnect is False


async def test_ensure_connected_probe_arms_short_idle(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND, poll="120")
    coord._probing = True
    with (
        patch.object(coord, "_get_ble_device", return_value=MagicMock()),
        patch(f"{_CO}.establish_connection", AsyncMock(return_value=MagicMock())),
        patch.object(coord._client, "start", AsyncMock()),
        patch.object(coord, "_schedule_idle_disconnect") as idle,
    ):
        await coord._ensure_connected()
    idle.assert_called_once()


async def test_async_disconnect_suppresses_errors(hass: HomeAssistant) -> None:
    coord = _coordinator(hass)
    coord._client = AsyncMock()
    coord._client.disconnect.side_effect = RuntimeError("boom")
    await coord._async_disconnect()  # must not raise


async def test_async_start_persistent_schedules_reconnect(
    hass: HomeAssistant,
) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = MagicMock(is_connected=False)
    with (
        patch(f"{_BT}.async_register_callback", return_value=MagicMock()),
        patch.object(coord, "_ensure_connected", AsyncMock()),
        patch.object(coord, "_schedule_reconnect") as reconnect,
    ):
        await coord.async_start()
    reconnect.assert_called_once()


def test_on_bluetooth_event_noop_when_connected(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = MagicMock(is_connected=True)
    with patch.object(coord.config_entry, "async_create_background_task") as task:
        coord._on_bluetooth_event(MagicMock(), MagicMock())
    task.assert_not_called()


def test_on_disconnect_noop_when_stopping_after_session(
    hass: HomeAssistant,
) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._connected_since = 1.0
    coord._stopping = True
    with patch.object(coord, "_schedule_reconnect") as reconnect:
        coord._on_disconnect(MagicMock())
    reconnect.assert_not_called()


def test_on_disconnect_intentional_when_off_not_probe(
    hass: HomeAssistant,
) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND)
    coord._connected_since = 1.0
    coord._probing = False
    with (
        patch.object(coord, "_schedule_poll") as poll,
        patch.object(coord, "_schedule_reconnect") as reconnect,
    ):
        coord._on_disconnect(MagicMock())
    poll.assert_called_once()
    reconnect.assert_not_called()


def test_schedule_idle_disconnect_noop_when_persistent(
    hass: HomeAssistant,
) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    with patch(f"{_CO}.async_call_later") as later:
        coord._schedule_idle_disconnect()
    later.assert_not_called()


def test_schedule_idle_disconnect_reset_rearms(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND)
    old = MagicMock()
    coord._cancel_idle_disconnect = old
    with patch(f"{_CO}.async_call_later", return_value=MagicMock()) as later:
        coord._schedule_idle_disconnect(reset=True)
    old.assert_called_once()
    later.assert_called_once()


def test_schedule_idle_disconnect_no_reset_keeps_existing(
    hass: HomeAssistant,
) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND)
    old = MagicMock()
    coord._cancel_idle_disconnect = old
    with patch(f"{_CO}.async_call_later", return_value=MagicMock()) as later:
        coord._schedule_idle_disconnect(reset=False)
    old.assert_not_called()
    later.assert_not_called()
    assert coord._cancel_idle_disconnect is old


def test_schedule_reconnect_noop_when_pending(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._cancel_reconnect = MagicMock()
    with patch(f"{_CO}.async_call_later") as later:
        coord._schedule_reconnect()
    later.assert_not_called()


async def test_async_probe_connect_failure_reschedules(
    hass: HomeAssistant,
) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND, poll="120")
    coord._client = MagicMock(is_connected=False)
    with (
        patch.object(
            coord, "_ensure_connected", AsyncMock(side_effect=RuntimeError("nope"))
        ),
        patch.object(coord, "_schedule_poll") as poll,
    ):
        await coord._async_probe()
    assert coord._probing is False
    poll.assert_called_once()


async def test_ensure_connected_noop_when_connected(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = MagicMock(is_connected=True)
    with patch.object(coord, "_get_ble_device") as get_dev:
        await coord._ensure_connected()
    get_dev.assert_not_called()


async def test_command_raises_when_connect_fails(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_ON_DEMAND)
    with patch.object(
        coord, "_ensure_connected", AsyncMock(side_effect=RuntimeError("x"))
    ):
        with pytest.raises(HomeAssistantError) as exc:
            await coord._ensure_command_connection()
    assert exc.value.translation_key == "not_reachable"


def test_schedule_reconnect_backoff_escalates_and_caps(
    hass: HomeAssistant,
) -> None:
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    delays: list[float] = []

    def _capture(_hass: HomeAssistant, delay: float, _cb: object) -> MagicMock:
        delays.append(delay)
        return MagicMock()

    with patch(f"{_CO}.async_call_later", side_effect=_capture):
        for _ in range(7):
            coord._cancel_reconnect = None  # simulate the previous timer firing
            coord._schedule_reconnect()
    # 5, 10, 20, 30, 60 then held at the 60s cap.
    assert delays == [5, 10, 20, 30, 60, 60, 60]


def test_keepalive_watchdog_to_reconnect_chain(hass: HomeAssistant) -> None:
    """The watchdog marks the link stale, drops it, and the drop reconnects."""
    coord = _coordinator(hass, mode=CONNECTION_MODE_PERSISTENT)
    coord._client = MagicMock(is_connected=True)
    coord._connected_since = 1.0

    with (
        patch.object(coord, "_async_disconnect", MagicMock(return_value=None)),
        patch.object(coord.config_entry, "async_create_background_task") as task,
    ):
        coord._keepalive_timer_fired(_now())
    assert coord._stale_disconnect is True
    task.assert_called_once()

    # The disconnect callback that follows routes to a reconnect and clears the
    # stale flag.
    with patch.object(coord, "_schedule_reconnect") as reconnect:
        coord._on_disconnect(MagicMock())
    reconnect.assert_called_once()
    assert coord._stale_disconnect is False



