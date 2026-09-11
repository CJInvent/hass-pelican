"""Polling coordinators for a Pelican site."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, tzinfo
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import PelicanApi
from .const import DOMAIN
from .errors import ErrorLog, PelicanAuthError, PelicanError
from .schedule import SiteSchedules, parse_entries, site_timezone_name

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

    async def async_apply(self, serial: str, values: dict[str, Any]) -> None:
        """Write attributes, update local state optimistically, then re-poll.

        Failures here are always logged at ERROR rather than throttled: a write
        is user-initiated and rare, so there is no spam risk and every one
        matters.
        """
        try:
            await self.api.async_set_thermostat(serial, values)
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


class PelicanScheduleCoordinator(DataUpdateCoordinator[SiteSchedules]):
    """Fetch the site's recurring schedules, keyed by serial number.

    Separate from the thermostat coordinator and much slower, because schedules
    change when a person edits them in Site Manager, not minute to minute. A
    failure here degrades the schedule warning; it must never take climate
    control down with it, so it is not part of config entry setup.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: PelicanApi,
        update_interval: timedelta,
    ) -> None:
        """Initialize the schedule coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} schedules {api.host}",
            update_interval=update_interval,
        )
        self.api = api
        self._errors = ErrorLog(_LOGGER, f"Schedule poll of {api.host}")
        self._warned_timezone: str | None = None

    async def _async_resolve_timezone(self, name: str | None) -> tuple[tzinfo, str]:
        """Turn the site's time zone name into a tzinfo, falling back loudly.

        ZoneInfo construction reads the tz database off disk, so it goes through
        Home Assistant's cached async helper rather than being built inline
        (rule 10).
        """
        if name:
            zone = await dt_util.async_get_time_zone(name)
            if zone is not None:
                self._warned_timezone = None
                return zone, name

        fallback = dt_util.DEFAULT_TIME_ZONE
        fallback_name = str(fallback)
        # Warn once per distinct problem: this is on a 30 minute timer and the
        # answer will not change until someone edits the site.
        if self._warned_timezone != (name or ""):
            self._warned_timezone = name or ""
            if name:
                _LOGGER.warning(
                    "Site %s reports time zone %r, which this system cannot "
                    "resolve. Falling back to Home Assistant's zone (%s); "
                    "predicted schedule times will be wrong if the two differ",
                    self.api.host,
                    name,
                    fallback_name,
                )
            else:
                _LOGGER.warning(
                    "Site %s did not report a time zone. Falling back to Home "
                    "Assistant's zone (%s); predicted schedule times will be "
                    "wrong if the site is in a different zone",
                    self.api.host,
                    fallback_name,
                )
        return fallback, fallback_name

    async def _async_update_data(self) -> SiteSchedules:
        """Read the site time zone and every recurring schedule entry."""
        try:
            site = await self.api.async_get_site()
            rows = await self.api.async_get_schedules()
        except PelicanAuthError as err:
            self._errors.failure(err)
            raise ConfigEntryAuthFailed(str(err)) from err
        except PelicanError as err:
            self._errors.failure(err)
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            self._errors.failure(err)
            raise UpdateFailed(
                f"Unexpected error reading schedules from {self.api.host}: {err}"
            ) from err

        self._errors.success()
        zone, zone_name = await self._async_resolve_timezone(site_timezone_name(site))
        return SiteSchedules(
            timezone=zone, timezone_name=zone_name, entries=parse_entries(rows)
        )


@dataclass
class PelicanData:
    """Everything a config entry owns at runtime."""

    api: PelicanApi
    thermostats: PelicanCoordinator
    schedules: PelicanScheduleCoordinator
