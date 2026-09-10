"""Polling coordinator for a Pelican site."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PelicanApi, PelicanAuthError, PelicanError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class PelicanCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Fetch every thermostat at the site in one request, keyed by serial number."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: PelicanApi,
        update_interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} {api.host}",
            update_interval=update_interval,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Pull the whole site in a single api.cgi call."""
        try:
            thermostats = await self.api.async_get_thermostats()
        except PelicanAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PelicanError as err:
            raise UpdateFailed(str(err)) from err

        return {
            str(thermostat["serialNo"]): thermostat
            for thermostat in thermostats
            if thermostat.get("serialNo")
        }

    async def async_apply(self, serial: str, values: dict[str, Any]) -> None:
        """Write attributes, update local state optimistically, then re-poll."""
        try:
            await self.api.async_set_thermostat(serial, values)
        except PelicanAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err

        if self.data and serial in self.data:
            self.data[serial].update({key: str(val) for key, val in values.items()})
            self.async_update_listeners()

        await self.async_request_refresh()
