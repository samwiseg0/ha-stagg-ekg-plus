"""Base entity for the Fellow Stagg EKG+ integration."""

from __future__ import annotations

from homeassistant.helpers.device_info import DeviceInfo
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import StaggCoordinator


class StaggEntity(CoordinatorEntity[StaggCoordinator]):
    """Common base for all kettle entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: StaggCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            identifiers={(DOMAIN, coordinator.address)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=MODEL,
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.is_connected
