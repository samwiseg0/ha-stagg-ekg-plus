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

"""Binary sensor platform for the Fellow Stagg EKG+ kettle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StaggConfigEntry
from .api import KettleState
from .coordinator import StaggCoordinator
from .entity import StaggEntity

# Read-only push entities; no command serialization needed.
PARALLEL_UPDATES = 0


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
        key="hold_enabled",
        translation_key="hold_enabled",
        entity_registry_enabled_default=False,
        value_fn=lambda state: state.hold_button,
    ),
    StaggBinaryDescription(
        key="on_base",
        translation_key="on_base",
        value_fn=lambda state: not state.lifted,
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

    def __init__(self, coordinator: StaggCoordinator, description: StaggBinaryDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"

    @property
    @override
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return self.entity_description.value_fn(data) if data else None
