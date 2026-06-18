"""Sensor platform for the Fellow Stagg EKG+ kettle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StaggConfigEntry
from .api import KettleState
from .entity import StaggEntity


@dataclass(frozen=True, kw_only=True)
class StaggSensorDescription(SensorEntityDescription):
    """Describes a Stagg sensor."""

    value_fn: Callable[[KettleState], int | None]
    unit_fn: Callable[[KettleState], str]


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
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StaggConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the kettle sensors."""
    coordinator = entry.runtime_data
    async_add_entities(StaggSensor(coordinator, desc) for desc in SENSORS)


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
        data = self.coordinator.data
        return self.entity_description.unit_fn(data) if data else None
