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
import time

from bleak.backends.device import BLEDevice
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
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import KettleState, StaggClient
from .const import (
    CONF_CONNECTION_MODE,
    CONNECTION_MODE_ON_DEMAND,
    DEFAULT_CONNECTION_MODE,
    DOMAIN,
    KEEP_ALIVE_TIMEOUT,
    ON_DEMAND_DISCONNECT_DELAY,
)

_LOGGER = logging.getLogger(__name__)

# Reconnect backoff schedule (seconds), used when the kettle drops while idle and
# is no longer advertising. An advertisement callback reconnects instantly when
# the kettle reappears, resetting this backoff. Capped at 60s.
_RECONNECT_BACKOFF = (5, 10, 20, 30, 60)


def _format_duration(seconds: float) -> str:
    """Format a number of seconds as e.g. '1h 23m 4s'."""
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


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
        self._ble_device: BLEDevice | None = None
        self._reconnect_attempt = 0
        self._cancel_reconnect: CALLBACK_TYPE | None = None
        self._connected_since: float | None = None
        self._on_demand = (
            entry.options.get(CONF_CONNECTION_MODE, DEFAULT_CONNECTION_MODE)
            == CONNECTION_MODE_ON_DEMAND
        )
        self._cancel_keepalive: CALLBACK_TYPE | None = None
        self._cancel_idle_disconnect: CALLBACK_TYPE | None = None
        self._expected_disconnect = False

    @callback
    def _handle_state(self, state: KettleState) -> None:
        self.async_set_updated_data(state)
        # Every notification proves the link is alive; restart the watchdog.
        self._reset_keepalive()

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    @property
    def available(self) -> bool:
        """Whether entities should report as available.

        In on-demand mode the link is intentionally dropped between commands, so
        availability follows whether we have any state rather than the live
        connection. In persistent mode availability tracks the connection.
        """
        if self._on_demand:
            return self.data is not None
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
        self.entry.async_on_unload(self._cancel_pending_reconnect)
        self.entry.async_on_unload(self._cancel_keepalive_timer)
        self.entry.async_on_unload(self._cancel_idle_disconnect_timer)
        await self._ensure_connected()
        if not self._client.is_connected and not self._on_demand:
            # Not reachable yet; keep retrying in the background. In on-demand
            # mode we instead wait for the next command to trigger a connect.
            self._schedule_reconnect()

    async def async_stop(self) -> None:
        """Disconnect and stop reconnecting."""
        self._stopping = True
        self._cancel_pending_reconnect()
        self._cancel_keepalive_timer()
        self._cancel_idle_disconnect_timer()
        await self._client.disconnect()

    @callback
    def _on_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Track the device and reconnect instantly when it advertises."""
        self._ble_device = service_info.device
        if self._stopping or self._on_demand or self._client.is_connected:
            return
        # A fresh advertisement is the best moment to (re)connect.
        self._cancel_pending_reconnect()
        self._reconnect_attempt = 0
        self.hass.async_create_task(self._async_reconnect())

    @callback
    def _on_disconnect(self, _client: BleakClientWithServiceCache) -> None:
        self._cancel_keepalive_timer()
        if self._connected_since is not None:
            held = _format_duration(time.monotonic() - self._connected_since)
            self._connected_since = None
            _LOGGER.info(
                "Kettle %s disconnected after being connected for %s",
                self.address,
                held,
            )
        else:
            _LOGGER.info("Kettle %s disconnected", self.address)
        # An intentional disconnect (idle timeout, keep-alive reset, or stop)
        # must not trigger the auto-reconnect path.
        if self._stopping or self._expected_disconnect:
            self._expected_disconnect = False
            return
        if self._on_demand:
            # Stay disconnected; the next command reconnects on demand.
            self.async_update_listeners()
            return
        self._schedule_reconnect()

    @callback
    def _reset_keepalive(self) -> None:
        """(Re)arm the persistent-mode keep-alive watchdog."""
        self._cancel_keepalive_timer()
        if self._stopping or self._on_demand or not self._client.is_connected:
            return
        self._cancel_keepalive = async_call_later(
            self.hass, KEEP_ALIVE_TIMEOUT, self._keepalive_timer_fired
        )

    @callback
    def _cancel_keepalive_timer(self) -> None:
        if self._cancel_keepalive is not None:
            self._cancel_keepalive()
            self._cancel_keepalive = None

    @callback
    def _keepalive_timer_fired(self, _now) -> None:
        self._cancel_keepalive = None
        if self._stopping or self._on_demand or not self._client.is_connected:
            return
        _LOGGER.info(
            "No data from kettle %s in %ss; forcing a reconnect",
            self.address,
            int(KEEP_ALIVE_TIMEOUT),
        )
        # Drop the stale link; _on_disconnect then schedules the reconnect.
        self.hass.async_create_task(self._client.disconnect())

    @callback
    def _schedule_idle_disconnect(self) -> None:
        """On-demand mode: disconnect after a short idle window."""
        self._cancel_idle_disconnect_timer()
        if self._stopping or not self._on_demand:
            return
        self._cancel_idle_disconnect = async_call_later(
            self.hass, ON_DEMAND_DISCONNECT_DELAY, self._idle_disconnect_fired
        )

    @callback
    def _cancel_idle_disconnect_timer(self) -> None:
        if self._cancel_idle_disconnect is not None:
            self._cancel_idle_disconnect()
            self._cancel_idle_disconnect = None

    @callback
    def _idle_disconnect_fired(self, _now) -> None:
        self._cancel_idle_disconnect = None
        if self._stopping or not self._client.is_connected:
            return
        _LOGGER.debug("Idle disconnect from kettle %s", self.address)
        self._expected_disconnect = True
        self.hass.async_create_task(self._client.disconnect())

    @callback
    def _schedule_reconnect(self) -> None:
        """Schedule a reconnect attempt with exponential backoff."""
        if self._stopping or self._cancel_reconnect is not None:
            return
        delay = _RECONNECT_BACKOFF[
            min(self._reconnect_attempt, len(_RECONNECT_BACKOFF) - 1)
        ]
        self._reconnect_attempt += 1
        _LOGGER.debug("Scheduling reconnect to %s in %ss", self.address, delay)
        self._cancel_reconnect = async_call_later(
            self.hass, delay, self._reconnect_timer_fired
        )

    @callback
    def _reconnect_timer_fired(self, _now) -> None:
        self._cancel_reconnect = None
        if self._stopping or self._client.is_connected:
            return
        self.hass.async_create_task(self._async_reconnect())

    @callback
    def _cancel_pending_reconnect(self) -> None:
        if self._cancel_reconnect is not None:
            self._cancel_reconnect()
            self._cancel_reconnect = None

    async def _async_reconnect(self) -> None:
        try:
            await self._ensure_connected()
        except Exception as err:  # noqa: BLE001 - keep retrying on any failure
            _LOGGER.debug("Reconnect to %s failed: %s", self.address, err)
        if not self._client.is_connected and not self._stopping:
            self._schedule_reconnect()

    def _get_ble_device(self) -> BLEDevice | None:
        """Best available BLEDevice, falling back to the last one we saw.

        `async_ble_device_from_address` returns None once the kettle stops
        advertising (~3 min idle). Falling back to the last known device lets
        bleak-retry-connector attempt a directed connection (e.g. through an
        ESPHome proxy) even when no current advertisement is cached.
        """
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is not None:
            self._ble_device = device
            return device
        service_info = bluetooth.async_last_service_info(
            self.hass, self.address, connectable=True
        )
        if service_info is not None:
            self._ble_device = service_info.device
        return self._ble_device

    async def _ensure_connected(self) -> None:
        async with self._connect_lock:
            if self._stopping or self._client.is_connected:
                return
            ble_device = self._get_ble_device()
            if ble_device is None:
                _LOGGER.debug("Kettle %s not currently available", self.address)
                return
            _LOGGER.info("Connecting to kettle %s", self.address)
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self.address,
                disconnected_callback=self._on_disconnect,
            )
            await self._client.start(client)
            self._connected_since = time.monotonic()
            self._reconnect_attempt = 0
            if self._on_demand:
                self._schedule_idle_disconnect()
            else:
                self._reset_keepalive()

    async def async_set_power(self, on: bool) -> None:
        await self._ensure_connected()
        await self._client.set_power(on)
        if self._on_demand:
            self._schedule_idle_disconnect()

    async def async_set_target_temp(self, temp: int) -> None:
        await self._ensure_connected()
        await self._client.set_target_temp(temp)
        if self._on_demand:
            self._schedule_idle_disconnect()
