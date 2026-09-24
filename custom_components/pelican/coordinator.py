"""Polling coordinator for a Pelican site."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PelicanApi
from .const import DOMAIN
from .errors import ErrorLog, PelicanApiError, PelicanAuthError, PelicanError

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
        self._errors = ErrorLog(_LOGGER, f"Thermostat poll of {api.host}")

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Pull the whole site in a single api.cgi call."""
        try:
            thermostats = await self.api.async_get_thermostats()
        except PelicanAuthError as err:
            # Every auth failure is logged before it becomes a reauth prompt, so
            # the log shows why the prompt appeared.
            self._errors.failure(err)
            raise ConfigEntryAuthFailed(str(err)) from err
        except PelicanError as err:
            self._errors.failure(err)
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            self._errors.failure(err)
            raise UpdateFailed(
                f"Unexpected error polling {self.api.host}: {err}"
            ) from err

        self._errors.success()

        keyed = {
            str(thermostat["serialNo"]): thermostat
            for thermostat in thermostats
            if thermostat.get("serialNo")
        }
        dropped = len(thermostats) - len(keyed)
        if dropped:
            _LOGGER.warning(
                "%s thermostat record(s) from %s had no serial number and were "
                "ignored; those thermostats will not appear in Home Assistant",
                dropped,
                self.api.host,
            )
        return keyed

    def selector_for(self, serial: str) -> str:
        """Return the nodeName to select this thermostat by, or raise.

        Entities are keyed by serialNo (rule 6), but the site refuses
        `serialNo:` selection, so the serial is resolved to a nodeName at write
        time.

        Everything below guards one verified behavior: the site does not reject
        a selection it cannot parse. It matches every thermostat and reports
        success -- a malformed selector on a live site returned "Updated 7
        thermostats". So a missing or malformed nodeName must never reach the
        wire.
        """
        thermostat = (self.data or {}).get(serial)
        if thermostat is None:
            raise PelicanApiError(
                f"Thermostat {serial} is not in the latest poll from "
                f"{self.api.host}; refusing to write"
            )

        node_name = thermostat.get("nodeName")
        if not isinstance(node_name, str) or not node_name.strip():
            raise PelicanApiError(
                f"Thermostat {serial} reported no nodeName at {self.api.host}. "
                "Writes select by nodeName, and an empty selector would change "
                "every thermostat at the site"
            )
        node_name = node_name.strip()

        duplicates = [
            other
            for other, record in (self.data or {}).items()
            if str(record.get("nodeName") or "").strip() == node_name
        ]
        if len(duplicates) > 1:
            raise PelicanApiError(
                f"{len(duplicates)} thermostats at {self.api.host} report the "
                f"node name {node_name!r}. A write would hit all of them, so it "
                "is refused. Report this to Pelican -- node names are supposed "
                "to be unique"
            )

        return node_name

    async def async_apply(self, serial: str, values: dict[str, Any]) -> None:
        """Write attributes, update local state optimistically, then re-poll.

        Failures here are always logged at ERROR rather than throttled: a write
        is user-initiated and rare, so there is no spam risk and every one
        matters.
        """
        try:
            node_name = self.selector_for(serial)
            await self.api.async_set_thermostat(node_name, values)
        except PelicanAuthError as err:
            _LOGGER.error(
                "Rejected credentials writing to thermostat %s: %s", serial, err
            )
            raise ConfigEntryAuthFailed(str(err)) from err
        except PelicanError as err:
            _LOGGER.error(
                "Failed to apply %s to thermostat %s: %s",
                ", ".join(f"{key}={value}" for key, value in values.items()),
                serial,
                err,
            )
            raise

        _LOGGER.debug("Applied %s to thermostat %s", values, serial)

        if self.data and serial in self.data:
            self.data[serial].update({key: str(val) for key, val in values.items()})
            self.async_update_listeners()

        await self.async_request_refresh()


@dataclass
class PelicanData:
    """Everything a config entry owns at runtime."""

    api: PelicanApi
    thermostats: PelicanCoordinator
