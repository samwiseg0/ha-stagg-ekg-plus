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

"""Tests for the Fellow Stagg EKG+ config and options flows."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stagg_ekg_plus.const import (
    CONF_CONNECTION_MODE,
    CONF_POLL_INTERVAL,
    CONNECTION_MODE_ON_DEMAND,
    CONNECTION_MODE_PERSISTENT,
    DOMAIN,
)

ADDRESS = "00:1C:97:16:46:B9"


def _service_info(address: str = ADDRESS, name: str = "FELLOW46B9"):
    """A minimal stand-in for BluetoothServiceInfoBleak used by the flow."""
    return SimpleNamespace(address=address, name=name, service_uuids=[])


async def test_bluetooth_discovery_creates_entry(hass: HomeAssistant) -> None:
    """A discovered kettle can be confirmed and creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=_service_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    with patch(
        "custom_components.stagg_ekg_plus.async_setup_entry", return_value=True
    ) as mock_setup:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["data"] == {CONF_ADDRESS: ADDRESS}
    assert mock_setup.call_count == 1


async def test_bluetooth_discovery_already_configured_aborts(
    hass: HomeAssistant,
) -> None:
    """A second discovery of an existing kettle aborts."""
    MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}).add_to_hass(
        hass
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=_service_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_step_no_devices_aborts(hass: HomeAssistant) -> None:
    """The user step aborts when nothing is discovered."""
    with patch(
        "custom_components.stagg_ekg_plus.config_flow.async_discovered_service_info",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_user_step_creates_entry(hass: HomeAssistant) -> None:
    """The user step lists discovered kettles and creates an entry."""
    with patch(
        "custom_components.stagg_ekg_plus.config_flow.async_discovered_service_info",
        return_value=[_service_info()],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        with patch(
            "custom_components.stagg_ekg_plus.async_setup_entry", return_value=True
        ):
            result2 = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input={CONF_ADDRESS: ADDRESS}
            )
            await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["data"] == {CONF_ADDRESS: ADDRESS}


async def test_user_step_skips_already_configured(hass: HomeAssistant) -> None:
    """A discovered kettle that is already set up is skipped in the user step."""
    MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}
    ).add_to_hass(hass)
    with patch(
        "custom_components.stagg_ekg_plus.config_flow.async_discovered_service_info",
        return_value=[_service_info()],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_options_flow_persistent_skips_poll_step(hass: HomeAssistant) -> None:
    """Choosing persistent finishes in one step (no poll question)."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_CONNECTION_MODE: CONNECTION_MODE_PERSISTENT},
    )
    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_CONNECTION_MODE] == CONNECTION_MODE_PERSISTENT


async def test_options_flow_on_demand_asks_poll_interval(
    hass: HomeAssistant,
) -> None:
    """Choosing on demand shows the background poll step."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_CONNECTION_MODE: CONNECTION_MODE_ON_DEMAND},
    )
    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "poll"

    result3 = await hass.config_entries.options.async_configure(
        result2["flow_id"], user_input={CONF_POLL_INTERVAL: "120"}
    )
    assert result3["type"] is FlowResultType.CREATE_ENTRY
    assert result3["data"][CONF_CONNECTION_MODE] == CONNECTION_MODE_ON_DEMAND
    assert result3["data"][CONF_POLL_INTERVAL] == "120"
