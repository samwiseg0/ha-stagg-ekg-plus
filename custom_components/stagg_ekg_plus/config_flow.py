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

"""Config flow for the Fellow Stagg EKG+ integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_CONNECTION_MODE,
    CONNECTION_MODE_ON_DEMAND,
    CONNECTION_MODE_PERSISTENT,
    DEFAULT_CONNECTION_MODE,
    DOMAIN,
    MODEL,
)


class StaggConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fellow Stagg EKG+."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> StaggOptionsFlow:
        """Return the options flow handler."""
        return StaggOptionsFlow()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a flow initialized by Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": self._title(discovery_info)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a single discovered device."""
        assert self._discovery is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._title(self._discovery),
                data={CONF_ADDRESS: self._discovery.address},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._title(self._discovery)},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user-initiated step: pick from discovered kettles."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            discovery = self._discovered[address]
            return self.async_create_entry(
                title=self._title(discovery),
                data={CONF_ADDRESS: address},
            )

        current_addresses = self._async_current_ids()
        for info in async_discovered_service_info(self.hass):
            if info.address in current_addresses or info.address in self._discovered:
                continue
            if self._is_kettle(info):
                self._discovered[info.address] = info

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: self._title(info)
                            for address, info in self._discovered.items()
                        }
                    )
                }
            ),
        )

    @staticmethod
    def _is_kettle(info: BluetoothServiceInfoBleak) -> bool:
        name = (info.name or "").upper()
        service_uuids = [u.lower() for u in info.service_uuids]
        return (
            name.startswith("FELLOW")
            or "00001820-0000-1000-8000-00805f9b34fb" in service_uuids
        )

    @staticmethod
    def _title(info: BluetoothServiceInfoBleak) -> str:
        return f"{MODEL} ({info.address})"


class StaggOptionsFlow(OptionsFlow):
    """Handle options for the Fellow Stagg EKG+ integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick the connection mode."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            CONF_CONNECTION_MODE, DEFAULT_CONNECTION_MODE
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONNECTION_MODE, default=current
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                CONNECTION_MODE_PERSISTENT,
                                CONNECTION_MODE_ON_DEMAND,
                            ],
                            translation_key="connection_mode",
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )
