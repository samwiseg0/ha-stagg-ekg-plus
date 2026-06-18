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

"""Connection coordinator for the Fellow Stagg EKG+ kettle."""

from __future__ import annotations

import asyncio
import logging

from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import KettleState, StaggClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class StaggCoordinator(DataUpdateCoordinator[KettleState]):
    """Maintains a persistent BLE connection and pushes kettle state to entities."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, address: str
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self.address = address
        self._client = StaggClient(on_state=self._handle_state)
        self._connect_lock = asyncio.Lock()
        self._stopping = False

    @callback
    def _handle_state(self, state: KettleState) -> None:
        self.async_set_updated_data(state)

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    async def async_start(self) -> None:
        """Register for advertisements and open the initial connection."""
        self.entry.async_on_unload(
            bluetooth.async_register_callback(
                self.hass,
                self._on_bluetooth_event,
                BluetoothCallbackMatcher(address=self.address),
                BluetoothScanningMode.ACTIVE,
            )
        )
        await self._ensure_connected()

    async def async_stop(self) -> None:
        """Disconnect and stop reconnecting."""
        self._stopping = True
        await self._client.disconnect()

    @callback
    def _on_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Reconnect when the kettle advertises again after a drop."""
        if self._stopping or self._client.is_connected:
            return
        self.hass.async_create_task(self._ensure_connected())

    @callback
    def _on_disconnect(self, _client: BleakClientWithServiceCache) -> None:
        if self._stopping:
            return
        _LOGGER.debug("Kettle %s disconnected", self.address)
        # Reconnection is driven by the bluetooth advertisement callback.

    async def _ensure_connected(self) -> None:
        async with self._connect_lock:
            if self._stopping or self._client.is_connected:
                return
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )
            if ble_device is None:
                _LOGGER.debug("Kettle %s not currently available", self.address)
                return
            _LOGGER.debug("Connecting to kettle %s", self.address)
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self.address,
                disconnected_callback=self._on_disconnect,
            )
            await self._client.start(client)

    async def async_set_power(self, on: bool) -> None:
        await self._ensure_connected()
        await self._client.set_power(on)

    async def async_set_target_temp(self, temp: int) -> None:
        await self._ensure_connected()
        await self._client.set_target_temp(temp)
