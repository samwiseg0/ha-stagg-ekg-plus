"""Switch platform for the Fellow Stagg EKG+ kettle."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StaggConfigEntry
from .entity import StaggEntity


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
    def unique_id(self) -> str:
        return f"{self.coordinator.address}_power"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return data.power if data else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(False)
