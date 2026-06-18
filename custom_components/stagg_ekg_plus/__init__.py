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

"""The Fellow Stagg EKG+ integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import StaggCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
]

type StaggConfigEntry = ConfigEntry[StaggCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: StaggConfigEntry) -> bool:
    """Set up Fellow Stagg EKG+ from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    coordinator = StaggCoordinator(hass, entry, address)
    try:
        await coordinator.async_start()
    except Exception as err:  # noqa: BLE001 - surface any connect failure as not-ready
        raise ConfigEntryNotReady(
            f"Could not connect to kettle {address}"
        ) from err

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: StaggConfigEntry
) -> None:
    """Reload the entry when its options change (e.g. connection mode)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: StaggConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_stop()
    return unload_ok
