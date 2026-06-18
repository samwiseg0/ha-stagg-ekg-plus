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

"""Sensor platform for the Fellow Stagg EKG+ kettle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components import bluetooth
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StaggConfigEntry
from .api import KettleState
from .entity import StaggEntity


@dataclass(frozen=True, kw_only=True)
class StaggSensorDescription(SensorEntityDescription):
    """Describes a Stagg sensor."""

    value_fn: Callable[[KettleState], int | None]
    # Dynamic native unit (e.g. F/C that follows the kettle). When None, the
    # static native_unit_of_measurement from the description is used instead.
    unit_fn: Callable[[KettleState], str] | None = None


def _temp_unit(state: KettleState) -> str:
    return (
        UnitOfTemperature.FAHRENHEIT
        if state.fahrenheit
        else UnitOfTemperature.CELSIUS
    )


def _current_temp(state: KettleState) -> int | None:
    # The kettle only reports a real reading while powered on.
    return state.current_temp if state.power else None


SENSORS: tuple[StaggSensorDescription, ...] = (
    StaggSensorDescription(
        key="current_temperature",
        translation_key="current_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current_temp,
        unit_fn=_temp_unit,
    ),
    StaggSensorDescription(
        key="target_temperature",
        translation_key="target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        value_fn=lambda state: state.target_temp,
        unit_fn=_temp_unit,
    ),
    StaggSensorDescription(
        key="countdown",
        translation_key="countdown",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda state: state.auto_off_remaining,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StaggConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the kettle sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [StaggSensor(coordinator, desc) for desc in SENSORS]
    entities.append(StaggRssiSensor(coordinator))
    async_add_entities(entities)


class StaggSensor(StaggEntity, SensorEntity):
    """A temperature sensor on the kettle."""

    entity_description: StaggSensorDescription

    def __init__(self, coordinator, description: StaggSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        return self.entity_description.value_fn(data) if data else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.unit_fn is None:
            return self.entity_description.native_unit_of_measurement
        data = self.coordinator.data
        return self.entity_description.unit_fn(data) if data else None


class StaggRssiSensor(StaggEntity, SensorEntity):
    """Signal strength of the kettle's last Bluetooth advertisement.

    While the integration holds a connection the kettle does not advertise, so
    this reflects the most recent advertised RSSI (updated on reconnects).
    """

    _attr_translation_key = "rssi"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_rssi"

    @property
    def native_value(self) -> int | None:
        info = bluetooth.async_last_service_info(
            self.coordinator.hass, self.coordinator.address, connectable=True
        )
        return info.rssi if info else None
