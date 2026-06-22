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

"""Tests for setup/unload and diagnostics."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stagg_ekg_plus.api import KettleState
from custom_components.stagg_ekg_plus.const import DOMAIN
from custom_components.stagg_ekg_plus.coordinator import StaggCoordinator
from custom_components.stagg_ekg_plus.diagnostics import (
    async_get_config_entry_diagnostics,
)

ADDRESS = "00:1C:97:16:46:B9"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}
    )


async def _fake_start(self: StaggCoordinator) -> None:
    """Stand in for async_start: publish a state without touching Bluetooth."""
    self.async_set_updated_data(
        KettleState(power=False, target_temp=200, current_temp=None, fahrenheit=True)
    )


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    """The entry sets up its coordinator and platforms and unloads cleanly."""
    entry = _entry()
    entry.add_to_hass(hass)

    with (
        patch.object(StaggCoordinator, "async_start", _fake_start),
        patch.object(StaggCoordinator, "async_stop", AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        assert isinstance(entry.runtime_data, StaggCoordinator)

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_not_ready_when_start_fails(hass: HomeAssistant) -> None:
    """A failed initial connect surfaces as ConfigEntryNotReady (setup retry)."""
    entry = _entry()
    entry.add_to_hass(hass)

    async def _boom(self: StaggCoordinator) -> None:
        raise RuntimeError("no bluetooth")

    with patch.object(StaggCoordinator, "async_start", _boom):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics(hass: HomeAssistant) -> None:
    """Diagnostics expose the connection settings and decoded state."""
    entry = _entry()
    entry.add_to_hass(hass)

    with (
        patch.object(StaggCoordinator, "async_start", _fake_start),
        patch.object(StaggCoordinator, "async_stop", AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["address"] == ADDRESS
    assert diag["connection_mode"] == "on_demand"
    assert diag["poll_interval"] == 0
    assert diag["state"]["target_temp"] == 200
    assert diag["state"]["power"] is False
