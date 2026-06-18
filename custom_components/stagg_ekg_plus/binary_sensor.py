"""Binary sensor platform for the Fellow Stagg EKG+ kettle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StaggConfigEntry
from .api import KettleState
from .entity import StaggEntity


@dataclass(frozen=True, kw_only=True)
class StaggBinaryDescription(BinarySensorEntityDescription):
    """Describes a Stagg binary sensor."""

    value_fn: Callable[[KettleState], bool | None]


BINARY_SENSORS: tuple[StaggBinaryDescription, ...] = (
    StaggBinaryDescription(
        key="hold",
        translation_key="hold",
        value_fn=lambda state: state.hold,
    ),
    StaggBinaryDescription(
        key="off_base",
        translation_key="off_base",
        value_fn=lambda state: state.lifted,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StaggConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the kettle binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        StaggBinarySensor(coordinator, desc) for desc in BINARY_SENSORS
    )


class StaggBinarySensor(StaggEntity, BinarySensorEntity):
    """A binary state on the kettle."""

    entity_description: StaggBinaryDescription

    def __init__(self, coordinator, description: StaggBinaryDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return self.entity_description.value_fn(data) if data else None
