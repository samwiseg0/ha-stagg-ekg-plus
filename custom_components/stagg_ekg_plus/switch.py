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

"""Switch platform for the Fellow Stagg EKG+ kettle."""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StaggConfigEntry
from .entity import StaggEntity

# Commands write to a single shared BLE connection; serialize them.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StaggConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the kettle power switch."""
    async_add_entities([StaggPowerSwitch(entry.runtime_data)])


class StaggPowerSwitch(StaggEntity, SwitchEntity):
    """Power switch for the kettle."""

    _attr_translation_key = "power"

    @property
    @override
    def unique_id(self) -> str:
        return f"{self.coordinator.address}_power"

    @property
    @override
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return data.power if data else None

    @property
    @override
    def assumed_state(self) -> bool:
        # The shown power is the last known value unless we hold a genuine live
        # session. While disconnected (on-demand idle) or only momentarily
        # connected for a background poll, it may be stale if the kettle was
        # toggled physically, so mark it as assumed.
        return not self.coordinator.is_live

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(False)
