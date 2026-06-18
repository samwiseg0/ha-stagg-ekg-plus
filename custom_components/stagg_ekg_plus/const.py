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

"""Constants for the Fellow Stagg EKG+ integration."""

from __future__ import annotations

DOMAIN = "stagg_ekg_plus"

MANUFACTURER = "Fellow"
MODEL = "Stagg EKG+"

# How long to wait for the first state notification before giving up at setup.
INITIAL_STATE_TIMEOUT = 20.0

# Connection mode option (set via the integration's Configure dialog).
CONF_CONNECTION_MODE = "connection_mode"
# Persistent: hold one BLE connection open and stream live state.
CONNECTION_MODE_PERSISTENT = "persistent"
# On demand: connect only while the kettle is powered on, then disconnect to
# free the Bluetooth adapter (default).
CONNECTION_MODE_ON_DEMAND = "on_demand"
DEFAULT_CONNECTION_MODE = CONNECTION_MODE_ON_DEMAND

# Persistent-mode keep-alive watchdog: the kettle streams state frames roughly
# every second while connected, so if no notification arrives within this many
# seconds we assume the link is stale and force a reconnect.
KEEP_ALIVE_TIMEOUT = 60.0

# On-demand mode: after connecting (for setup or a command) stay connected this
# long to catch the resulting state push, then disconnect to free the adapter.
ON_DEMAND_DISCONNECT_DELAY = 10.0
