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
import contextlib
import logging
import time
from datetime import datetime

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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import KettleState, StaggClient
from .const import (
    CONF_CONNECTION_MODE,
    CONF_POLL_INTERVAL,
    CONNECTION_MODE_ON_DEMAND,
    DEFAULT_CONNECTION_MODE,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    KEEP_ALIVE_TIMEOUT,
    ON_DEMAND_DISCONNECT_DELAY,
    PROBE_DISCONNECT_DELAY,
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

    config_entry: ConfigEntry[StaggCoordinator]

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, address: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
            config_entry=entry,
        )
        self.address = address
        self._client = StaggClient(on_state=self._handle_state)
        self._connect_lock = asyncio.Lock()
        self._stopping = False
        self._reconnect_attempt = 0
        self._cancel_reconnect: CALLBACK_TYPE | None = None
        self._connected_since: float | None = None
        self._on_demand = (
            entry.options.get(CONF_CONNECTION_MODE, DEFAULT_CONNECTION_MODE)
            == CONNECTION_MODE_ON_DEMAND
        )
        self._poll_interval = int(
            entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        )
        self._cancel_keepalive: CALLBACK_TYPE | None = None
        self._cancel_idle_disconnect: CALLBACK_TYPE | None = None
        self._cancel_poll: CALLBACK_TYPE | None = None
        self._stale_disconnect = False
        self._probing = False
        self._probe_started: float | None = None

    @callback
    def _handle_state(self, state: KettleState) -> None:
        self.async_set_updated_data(state)
        if self._on_demand:
            # On demand: hold the link while the kettle is doing something
            # (powered on), and let it go once it is off/idle.
            if state.power:
                if self._probing and self._probe_started is not None:
                    _LOGGER.info(
                        "Poll of kettle %s found it on after %.1fs; keeping "
                        "the connection",
                        self.address,
                        time.monotonic() - self._probe_started,
                    )
                    self._probe_started = None
                # A probe that found the kettle on becomes a normal live
                # session; clear the probe flag so the full grace window
                # applies when it later turns off.
                self._probing = False
                self._cancel_idle_disconnect_timer()
            else:
                # Drop quickly after a probe (we only needed one frame), or
                # after the normal grace window for a user-driven session. The
                # off-poll outcome is logged in _on_disconnect: the kettle's
                # off state often matches the last session unchanged, so this
                # branch (state-change driven) does not reliably run on a poll.
                delay = (
                    PROBE_DISCONNECT_DELAY
                    if self._probing
                    else ON_DEMAND_DISCONNECT_DELAY
                )
                self._schedule_idle_disconnect(reset=False, delay=delay)
        # Every notification proves the link is alive; restart the watchdog.
        self._reset_keepalive()

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    def _wants_connection(self) -> bool:
        """Whether we want to hold an open connection right now.

        Persistent mode always wants the link. On-demand mode wants it only
        while the kettle is powered on, so live temperature streams while it is
        heating/holding and the adapter is freed once it turns off.
        """
        if not self._on_demand:
            return True
        return bool(self.data and self.data.power)

    @property
    def available(self) -> bool:
        """Whether entities should report as available.

        In on-demand mode the link is intentionally dropped while the kettle is
        off, so availability follows whether we have any state rather than the
        live connection. In persistent mode availability tracks the connection.
        """
        if self._on_demand:
            return self.data is not None
        return self._client.is_connected

    async def async_start(self) -> None:
        """Register for advertisements and open the initial connection."""
        self.config_entry.async_on_unload(
            bluetooth.async_register_callback(
                self.hass,
                self._on_bluetooth_event,
                BluetoothCallbackMatcher(address=self.address),
                BluetoothScanningMode.ACTIVE,
            )
        )
        self.config_entry.async_on_unload(self._cancel_pending_reconnect)
        self.config_entry.async_on_unload(self._cancel_keepalive_timer)
        self.config_entry.async_on_unload(self._cancel_idle_disconnect_timer)
        self.config_entry.async_on_unload(self._cancel_poll_timer)
        await self._ensure_connected()
        if not self._client.is_connected and not self._on_demand:
            # Not reachable yet; keep retrying in the background. In on-demand
            # mode we instead wait for the next command to trigger a connect.
            self._schedule_reconnect()
        elif not self._client.is_connected and self._on_demand:
            # On demand and idle (kettle off): start the optional background
            # probe loop if the user enabled it.
            self._schedule_poll()

    async def async_stop(self) -> None:
        """Disconnect and stop reconnecting."""
        self._stopping = True
        self._cancel_pending_reconnect()
        self._cancel_keepalive_timer()
        self._cancel_idle_disconnect_timer()
        self._cancel_poll_timer()
        await self._client.disconnect()

    @callback
    def _on_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Reconnect instantly when the kettle advertises."""
        if (
            self._stopping
            or self._client.is_connected
            or not self._wants_connection()
        ):
            return
        # A fresh advertisement is the best moment to (re)connect.
        self._cancel_pending_reconnect()
        self._reconnect_attempt = 0
        self.config_entry.async_create_background_task(
            self.hass, self._async_reconnect(), name=f"{DOMAIN}_reconnect"
        )

    @callback
    def _on_disconnect(self, _client: BleakClientWithServiceCache) -> None:
        self._cancel_keepalive_timer()
        if self._connected_since is None:
            # A disconnect callback for a connection that never became an active
            # session: an intermediate establish_connection retry, or a drop
            # during the auth/subscribe handshake (common when the host adapter
            # is under stress). The in-flight connect path owns this outcome --
            # acting here would emit spurious "disconnected" logs, reschedule
            # polls, and clear the probe flag mid-probe. Ignore it.
            if not self._stopping:
                _LOGGER.debug(
                    "Ignoring disconnect for %s before the session was active",
                    self.address,
                )
            return
        held = _format_duration(time.monotonic() - self._connected_since)
        self._connected_since = None
        if self._stopping:
            return
        stale = self._stale_disconnect
        self._stale_disconnect = False
        suffix = f" after being connected for {held}"
        # Whether to reconnect is decided solely by whether we still want the
        # link. This also covers the race where an idle disconnect (armed while
        # the kettle was off) fires just as the kettle comes on: we now want the
        # connection, so we reconnect instead of staying dark.
        if not self._wants_connection():
            # Intentional: on-demand idle disconnect while the kettle is off.
            # Stay disconnected until the next command or power-on.
            was_probe = self._probing
            self._probing = False
            self._probe_started = None
            if was_probe:
                _LOGGER.info(
                    "Poll of kettle %s found it off; disconnected%s",
                    self.address,
                    suffix,
                )
            else:
                _LOGGER.info("Kettle %s disconnected%s", self.address, suffix)
            self.async_update_listeners()
            # Resume the optional background probe loop, if enabled.
            self._schedule_poll()
            return
        # We want to stay connected but the link dropped on its own.
        if stale:
            # The keep-alive watchdog already logged why at INFO.
            _LOGGER.info(
                "Kettle %s disconnected%s; reconnecting", self.address, suffix
            )
        else:
            _LOGGER.warning(
                "Kettle %s unexpectedly disconnected%s; reconnecting",
                self.address,
                suffix,
            )
        self._schedule_reconnect()

    @callback
    def _reset_keepalive(self) -> None:
        """(Re)arm the keep-alive watchdog while we want an open link."""
        self._cancel_keepalive_timer()
        if (
            self._stopping
            or not self._client.is_connected
            or not self._wants_connection()
        ):
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
    def _keepalive_timer_fired(self, _now: datetime) -> None:
        self._cancel_keepalive = None
        if (
            self._stopping
            or not self._client.is_connected
            or not self._wants_connection()
        ):
            return
        _LOGGER.info(
            "No data from kettle %s in %ss; forcing a reconnect",
            self.address,
            int(KEEP_ALIVE_TIMEOUT),
        )
        # Drop the stale link; _on_disconnect then schedules the reconnect.
        self._stale_disconnect = True
        self.config_entry.async_create_background_task(
            self.hass, self._async_disconnect(), name=f"{DOMAIN}_disconnect"
        )

    @callback
    def _schedule_idle_disconnect(
        self, reset: bool = True, delay: float = ON_DEMAND_DISCONNECT_DELAY
    ) -> None:
        """On-demand mode: disconnect after a short idle window.

        With reset=False an already-pending timer is left running, so a stream
        of "kettle off" frames does not keep pushing the disconnect out.
        """
        if self._stopping or not self._on_demand:
            return
        if self._cancel_idle_disconnect is not None:
            if not reset:
                return
            self._cancel_idle_disconnect()
            self._cancel_idle_disconnect = None
        self._cancel_idle_disconnect = async_call_later(
            self.hass, delay, self._idle_disconnect_fired
        )

    @callback
    def _cancel_idle_disconnect_timer(self) -> None:
        if self._cancel_idle_disconnect is not None:
            self._cancel_idle_disconnect()
            self._cancel_idle_disconnect = None

    @callback
    def _idle_disconnect_fired(self, _now: datetime) -> None:
        self._cancel_idle_disconnect = None
        # If the kettle came on between arming and firing, keep the link.
        if (
            self._stopping
            or not self._client.is_connected
            or self._wants_connection()
        ):
            return
        _LOGGER.debug("Idle disconnect from kettle %s", self.address)
        self.config_entry.async_create_background_task(
            self.hass, self._async_disconnect(), name=f"{DOMAIN}_disconnect"
        )

    async def _async_disconnect(self) -> None:
        """Disconnect the client, suppressing benign teardown errors.

        Used by the fire-and-forget timer callbacks (keep-alive watchdog and
        idle disconnect); a failure here is not actionable and routes through
        the disconnected callback anyway, so it should not surface as an
        unhandled task exception.
        """
        with contextlib.suppress(Exception):
            await self._client.disconnect()

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
    def _reconnect_timer_fired(self, _now: datetime) -> None:
        self._cancel_reconnect = None
        if (
            self._stopping
            or self._client.is_connected
            or not self._wants_connection()
        ):
            return
        self.config_entry.async_create_background_task(
            self.hass, self._async_reconnect(), name=f"{DOMAIN}_reconnect"
        )

    @callback
    def _cancel_pending_reconnect(self) -> None:
        if self._cancel_reconnect is not None:
            self._cancel_reconnect()
            self._cancel_reconnect = None

    @callback
    def _schedule_poll(self) -> None:
        """On-demand mode: schedule the next background state probe.

        Runs only while disconnected and idle (kettle believed off). A probe
        briefly connects, reads the state, and disconnects again if the kettle
        is still off, so a physical power-on is noticed within one interval.
        Disabled (no-op) unless the user set a poll interval.
        """
        if (
            self._stopping
            or not self._on_demand
            or self._poll_interval <= 0
            or self._cancel_poll is not None
            or self._client.is_connected
            or self._wants_connection()
        ):
            return
        self._cancel_poll = async_call_later(
            self.hass, self._poll_interval, self._poll_timer_fired
        )

    @callback
    def _cancel_poll_timer(self) -> None:
        if self._cancel_poll is not None:
            self._cancel_poll()
            self._cancel_poll = None

    @callback
    def _poll_timer_fired(self, _now: datetime) -> None:
        self._cancel_poll = None
        if (
            self._stopping
            or self._client.is_connected
            or self._wants_connection()
        ):
            # Already online; nothing to probe. Try again next interval if we
            # fall back to the idle/disconnected state.
            self._schedule_poll()
            return
        self.config_entry.async_create_background_task(
            self.hass, self._async_probe(), name=f"{DOMAIN}_poll"
        )

    async def _async_probe(self) -> None:
        """Briefly connect to read state, then disconnect if still off.

        On a successful connect the normal state handler decides what happens:
        a powered-on kettle keeps the link, an off kettle is dropped quickly
        (PROBE_DISCONNECT_DELAY). Probe failures are expected (the kettle is
        off and may not be advertising) and only logged at debug.
        """
        self._probing = True
        self._probe_started = time.monotonic()
        _LOGGER.info(
            "Polling kettle %s (background check for a physical power-on)",
            self.address,
        )
        try:
            await self._ensure_connected()
        except Exception as err:  # noqa: BLE001 - probe failures are expected
            _LOGGER.debug("Probe of %s failed: %s", self.address, err)
        if not self._client.is_connected:
            # Could not reach the kettle; the link never opened, so the
            # _on_disconnect reschedule will not fire. Try again next interval.
            _LOGGER.info(
                "Poll of kettle %s could not connect after %.1fs (kettle "
                "likely off); will retry",
                self.address,
                time.monotonic() - self._probe_started,
            )
            self._probing = False
            self._probe_started = None
            self._schedule_poll()

    async def _async_reconnect(self) -> None:
        try:
            await self._ensure_connected()
        except Exception as err:  # noqa: BLE001 - keep retrying on any failure
            _LOGGER.debug("Reconnect to %s failed: %s", self.address, err)
        if (
            not self._client.is_connected
            and not self._stopping
            and self._wants_connection()
        ):
            self._schedule_reconnect()

    def _get_ble_device(self) -> BLEDevice | None:
        """Best available BLEDevice for a connect attempt.

        Prefers a currently-advertising device, then the last service info HA
        cached (which still works for a directed connect to an idle kettle that
        stopped advertising, e.g. through an ESPHome proxy). Returns None when HA
        has no record at all, rather than a stale device from a previous
        session -- the advertisement callback will trigger a connect once the
        kettle reappears.
        """
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is not None:
            return device
        service_info = bluetooth.async_last_service_info(
            self.hass, self.address, connectable=True
        )
        if service_info is not None:
            return service_info.device
        return None

    async def _ensure_connected(self) -> None:
        async with self._connect_lock:
            if self._stopping or self._client.is_connected:
                return
            ble_device = self._get_ble_device()
            if ble_device is None:
                _LOGGER.debug("Kettle %s not currently available", self.address)
                return
            if self._probing:
                # The poll start line already announced this connect; keep the
                # generic connect log at debug to avoid double messaging.
                _LOGGER.debug("Connecting to kettle %s (poll)", self.address)
            else:
                _LOGGER.info("Connecting to kettle %s", self.address)
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self.address,
                disconnected_callback=self._on_disconnect,
            )
            if self._stopping:
                # The entry was unloaded/reloaded while this connect was in
                # flight (async_stop does not hold the connect lock). Tear the
                # fresh client down instead of leaving a live session that would
                # hold the kettle's single connection slot.
                with contextlib.suppress(Exception):
                    await client.disconnect()
                return
            await self._client.start(client)
            self._cancel_poll_timer()
            self._connected_since = time.monotonic()
            self._reconnect_attempt = 0
            if self._on_demand:
                self._schedule_idle_disconnect(
                    delay=(
                        PROBE_DISCONNECT_DELAY
                        if self._probing
                        else ON_DEMAND_DISCONNECT_DELAY
                    )
                )
            else:
                self._reset_keepalive()

    async def async_set_power(self, on: bool) -> None:
        await self._ensure_command_connection()
        await self._client.set_power(on)
        self._arm_idle_disconnect_after_command()

    async def async_set_target_temp(self, temp: int) -> None:
        await self._ensure_command_connection()
        await self._client.set_target_temp(temp)
        self._arm_idle_disconnect_after_command()

    @callback
    def _arm_idle_disconnect_after_command(self) -> None:
        """On-demand: after a command, drop the link only if the kettle is off.

        If the kettle is on we keep the connection (the keep-alive watchdog
        covers a dead link); arming an idle timer here would race the live
        state stream and could drop an active connection. A power-on command
        still arms it transiently (last-known power is off), but the resulting
        power-on state cancels it.
        """
        if self._on_demand and not self._wants_connection():
            self._schedule_idle_disconnect()

    async def _ensure_command_connection(self) -> None:
        """Connect for a command, raising a clear error if unreachable."""
        # A user command means this is no longer a passive background probe:
        # clear the probe flag so a resulting power-on is not logged as a poll
        # catch and the normal session/idle handling applies (this also covers
        # a command that reuses a probe connection still being established).
        self._probing = False
        self._probe_started = None
        try:
            await self._ensure_connected()
        except Exception as err:  # noqa: BLE001 - boundary: surface as HA error
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_reachable",
                translation_placeholders={"address": self.address},
            ) from err
        if not self._client.is_connected:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_reachable",
                translation_placeholders={"address": self.address},
            )
