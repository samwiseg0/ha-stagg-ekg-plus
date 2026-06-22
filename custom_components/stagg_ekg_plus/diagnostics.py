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

"""Diagnostics support for the Fellow Stagg EKG+ integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import StaggConfigEntry
from .const import (
    CONF_CONNECTION_MODE,
    CONF_POLL_INTERVAL,
    DEFAULT_CONNECTION_MODE,
    DEFAULT_POLL_INTERVAL,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: StaggConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    state = coordinator.data
    return {
        "address": coordinator.address,
        "connection_mode": entry.options.get(
            CONF_CONNECTION_MODE, DEFAULT_CONNECTION_MODE
        ),
        "poll_interval": entry.options.get(
            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
        ),
        "is_connected": coordinator.is_connected,
        "available": coordinator.available,
        "state": asdict(state) if state is not None else None,
    }
