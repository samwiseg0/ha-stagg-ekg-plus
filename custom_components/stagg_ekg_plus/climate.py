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

"""Climate platform for the Fellow Stagg EKG+ kettle."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StaggConfigEntry
from .api import TEMP_MAX_C, TEMP_MAX_F, TEMP_MIN_C, TEMP_MIN_F
from .entity import StaggEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StaggConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the kettle climate entity."""
    async_add_entities([StaggClimate(entry.runtime_data)])


class StaggClimate(StaggEntity, ClimateEntity):
    """Represents the kettle as a heater with a target temperature."""

    _attr_name = None
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_target_temperature_step = 1

    @property
    def unique_id(self) -> str:
        return self.coordinator.address

    @property
    def _is_fahrenheit(self) -> bool:
        data = self.coordinator.data
        # Default to Fahrenheit only briefly until the first state arrives.
        return bool(data.fahrenheit) if data and data.fahrenheit is not None else False

    @property
    def temperature_unit(self) -> str:
        return (
            UnitOfTemperature.FAHRENHEIT
            if self._is_fahrenheit
            else UnitOfTemperature.CELSIUS
        )

    @property
    def min_temp(self) -> float:
        return TEMP_MIN_F if self._is_fahrenheit else TEMP_MIN_C

    @property
    def max_temp(self) -> float:
        return TEMP_MAX_F if self._is_fahrenheit else TEMP_MAX_C

    @property
    def current_temperature(self) -> float | None:
        data = self.coordinator.data
        if data is None or not data.power:
            # The kettle only reports a real reading while powered on.
            return None
        return data.current_temp

    @property
    def target_temperature(self) -> float | None:
        data = self.coordinator.data
        return data.target_temp if data else None

    @property
    def hvac_mode(self) -> HVACMode | None:
        data = self.coordinator.data
        if data is None or data.power is None:
            return None
        return HVACMode.HEAT if data.power else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        data = self.coordinator.data
        if data is None or data.power is None:
            return None
        return HVACAction.HEATING if data.power else HVACAction.OFF

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.async_set_target_temp(int(temperature))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.coordinator.async_set_power(hvac_mode == HVACMode.HEAT)

    async def async_turn_on(self) -> None:
        await self.coordinator.async_set_power(True)

    async def async_turn_off(self) -> None:
        await self.coordinator.async_set_power(False)
