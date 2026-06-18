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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: StaggConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_stop()
    return unload_ok
