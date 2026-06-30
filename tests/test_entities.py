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

"""Tests for the climate and switch entity behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.climate.const import HVACAction, HVACMode
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_ADDRESS,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stagg_ekg_plus.api import KettleState
from custom_components.stagg_ekg_plus.binary_sensor import (
    BINARY_SENSORS,
    StaggBinarySensor,
)
from custom_components.stagg_ekg_plus.climate import StaggClimate
from custom_components.stagg_ekg_plus.const import DOMAIN
from custom_components.stagg_ekg_plus.coordinator import StaggCoordinator
from custom_components.stagg_ekg_plus.sensor import (
    SENSORS,
    StaggRssiSensor,
    StaggSensor,
)
from custom_components.stagg_ekg_plus.switch import StaggPowerSwitch

ADDRESS = "00:1C:97:16:46:B9"


def _coordinator(hass: HomeAssistant, state: KettleState | None) -> StaggCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS})
    entry.add_to_hass(hass)
    coord = StaggCoordinator(hass, entry, ADDRESS)
    if state is not None:
        coord.async_set_updated_data(state)
    return coord


def _sensor_desc(key: str):
    return next(d for d in SENSORS if d.key == key)


def _binary_desc(key: str):
    return next(d for d in BINARY_SENSORS if d.key == key)


def test_switch_is_on(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(power=True))
    assert StaggPowerSwitch(coord).is_on is True


def test_switch_is_on_none_without_data(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, None)
    assert StaggPowerSwitch(coord).is_on is None


def test_switch_assumed_state_tracks_connection(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(power=True))
    switch = StaggPowerSwitch(coord)
    coord._client = MagicMock(is_connected=False)
    assert switch.assumed_state is True  # disconnected -> last-known, maybe stale
    coord._client = MagicMock(is_connected=True)
    assert switch.assumed_state is False  # live session -> real state


def test_switch_assumed_state_during_background_probe(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(power=True))
    switch = StaggPowerSwitch(coord)
    coord._client = MagicMock(is_connected=True)
    coord._probing = True  # transient poll connection, not a live session
    assert switch.assumed_state is True


async def test_switch_turn_on_off(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(power=False))
    switch = StaggPowerSwitch(coord)
    with patch.object(coord, "async_set_power", AsyncMock()) as set_power:
        await switch.async_turn_on()
        await switch.async_turn_off()
    assert [c.args[0] for c in set_power.await_args_list] == [True, False]


def test_climate_modes_and_temps(hass: HomeAssistant) -> None:
    coord = _coordinator(
        hass,
        KettleState(power=True, target_temp=208, current_temp=180, fahrenheit=True),
    )
    climate = StaggClimate(coord)
    assert climate.hvac_mode is HVACMode.HEAT
    assert climate.hvac_action is HVACAction.HEATING
    assert climate.target_temperature == 208
    assert climate.current_temperature == 180
    assert climate.temperature_unit == UnitOfTemperature.FAHRENHEIT
    assert climate.max_temp == 212


def test_climate_off_hides_current_temp(hass: HomeAssistant) -> None:
    coord = _coordinator(
        hass, KettleState(power=False, target_temp=208, current_temp=180, fahrenheit=True)
    )
    climate = StaggClimate(coord)
    assert climate.hvac_mode is HVACMode.OFF
    assert climate.hvac_action is HVACAction.OFF
    # Current temp is only meaningful while powered on.
    assert climate.current_temperature is None


def test_climate_celsius_limits(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(power=False, fahrenheit=False))
    climate = StaggClimate(coord)
    assert climate.temperature_unit == UnitOfTemperature.CELSIUS
    assert climate.min_temp == 40
    assert climate.max_temp == 100


async def test_climate_set_temperature(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(power=True, fahrenheit=True))
    climate = StaggClimate(coord)
    with patch.object(coord, "async_set_target_temp", AsyncMock()) as set_temp:
        await climate.async_set_temperature(**{ATTR_TEMPERATURE: 205})
    set_temp.assert_awaited_once_with(205)


async def test_climate_set_temperature_truncates_float(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(power=True, fahrenheit=True))
    climate = StaggClimate(coord)
    with patch.object(coord, "async_set_target_temp", AsyncMock()) as set_temp:
        await climate.async_set_temperature(**{ATTR_TEMPERATURE: 199.8})
    set_temp.assert_awaited_once_with(199)


async def test_climate_set_temperature_noop_without_value(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(power=True))
    climate = StaggClimate(coord)
    with patch.object(coord, "async_set_target_temp", AsyncMock()) as set_temp:
        await climate.async_set_temperature()
    set_temp.assert_not_awaited()


async def test_climate_set_hvac_mode(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(power=False))
    climate = StaggClimate(coord)
    with patch.object(coord, "async_set_power", AsyncMock()) as set_power:
        await climate.async_set_hvac_mode(HVACMode.HEAT)
        await climate.async_set_hvac_mode(HVACMode.OFF)
    assert [c.args[0] for c in set_power.await_args_list] == [True, False]


async def test_climate_turn_on_off(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(power=False))
    climate = StaggClimate(coord)
    with patch.object(coord, "async_set_power", AsyncMock()) as set_power:
        await climate.async_turn_on()
        await climate.async_turn_off()
    assert [c.args[0] for c in set_power.await_args_list] == [True, False]


def test_climate_unknown_power_and_unit(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(power=None, fahrenheit=None))
    climate = StaggClimate(coord)
    assert climate.hvac_mode is None
    assert climate.hvac_action is None
    # Unknown unit defaults to Celsius until the first state arrives.
    assert climate.temperature_unit == UnitOfTemperature.CELSIUS


def test_rssi_sensor_value(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState())
    sensor = StaggRssiSensor(coord)
    with patch(
        "custom_components.stagg_ekg_plus.sensor.bluetooth.async_last_service_info",
        return_value=type("Info", (), {"rssi": -50})(),
    ):
        assert sensor.native_value == -50
    with patch(
        "custom_components.stagg_ekg_plus.sensor.bluetooth.async_last_service_info",
        return_value=None,
    ):
        assert sensor.native_value is None


# --- climate hvac_action accuracy (powered on != always heating) ------------


def test_climate_hvac_action_idle_when_holding(hass: HomeAssistant) -> None:
    # At setpoint, keep-warm engaged: on but not actively heating -> IDLE.
    coord = _coordinator(hass, KettleState(power=True, hold=True, fahrenheit=True))
    assert StaggClimate(coord).hvac_action is HVACAction.IDLE


def test_climate_hvac_action_idle_when_lifted(hass: HomeAssistant) -> None:
    # Lifted off the base: the element cannot heat -> IDLE.
    coord = _coordinator(hass, KettleState(power=True, lifted=True, fahrenheit=True))
    assert StaggClimate(coord).hvac_action is HVACAction.IDLE


def test_climate_hvac_action_heating_when_warming(hass: HomeAssistant) -> None:
    coord = _coordinator(
        hass,
        KettleState(
            power=True, hold=False, lifted=False, current_temp=120,
            target_temp=205, fahrenheit=True,
        ),
    )
    assert StaggClimate(coord).hvac_action is HVACAction.HEATING


def test_climate_hvac_action_off_when_powered_off(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(power=False))
    assert StaggClimate(coord).hvac_action is HVACAction.OFF


def test_climate_unknown_unit_follows_system_fahrenheit(hass: HomeAssistant) -> None:
    # Before the first temperature frame the unit is unknown; fall back to the
    # HA system unit rather than always assuming Celsius.
    hass.config.units = US_CUSTOMARY_SYSTEM
    coord = _coordinator(hass, KettleState(power=None, fahrenheit=None))
    climate = StaggClimate(coord)
    assert climate.temperature_unit == UnitOfTemperature.FAHRENHEIT
    assert climate.min_temp == 104
    assert climate.max_temp == 212


# --- StaggSensor (temperature + countdown descriptions) ---------------------


def test_sensor_current_temp_value_and_unit_fahrenheit(hass: HomeAssistant) -> None:
    coord = _coordinator(
        hass, KettleState(current_temp=180, fahrenheit=True, power=True)
    )
    sensor = StaggSensor(coord, _sensor_desc("current_temperature"))
    assert sensor.native_value == 180
    assert sensor.native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT


def test_sensor_target_temp_value_and_unit_celsius(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(target_temp=90, fahrenheit=False))
    sensor = StaggSensor(coord, _sensor_desc("target_temperature"))
    assert sensor.native_value == 90
    assert sensor.native_unit_of_measurement == UnitOfTemperature.CELSIUS


def test_sensor_countdown_static_unit(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(auto_off_remaining=3600))
    sensor = StaggSensor(coord, _sensor_desc("countdown"))
    assert sensor.native_value == 3600
    # No unit_fn: the static native unit from the description is used.
    assert sensor.native_unit_of_measurement == UnitOfTime.SECONDS


def test_sensor_no_data_returns_none(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, None)
    sensor = StaggSensor(coord, _sensor_desc("current_temperature"))
    assert sensor.native_value is None
    assert sensor.native_unit_of_measurement is None


# --- StaggBinarySensor (hold / hold_enabled / on_base) ----------------------


def test_binary_sensor_hold(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(hold=True))
    assert StaggBinarySensor(coord, _binary_desc("hold")).is_on is True


def test_binary_sensor_hold_enabled(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(hold_button=True))
    assert StaggBinarySensor(coord, _binary_desc("hold_enabled")).is_on is True


def test_binary_sensor_on_base_seated(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(lifted=False))
    assert StaggBinarySensor(coord, _binary_desc("on_base")).is_on is True


def test_binary_sensor_on_base_lifted(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, KettleState(lifted=True))
    assert StaggBinarySensor(coord, _binary_desc("on_base")).is_on is False


def test_binary_sensor_on_base_unknown_when_lifted_none(hass: HomeAssistant) -> None:
    # Regression: unknown base state must stay None, not collapse to True.
    coord = _coordinator(hass, KettleState(lifted=None))
    assert StaggBinarySensor(coord, _binary_desc("on_base")).is_on is None


def test_binary_sensor_no_data_returns_none(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, None)
    assert StaggBinarySensor(coord, _binary_desc("hold")).is_on is None
