"""The Pelican Wireless integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PelicanApi
from .const import DEFAULT_SCAN_INTERVAL, SCHEDULE_SCAN_INTERVAL
from .coordinator import PelicanCoordinator, PelicanData, PelicanScheduleCoordinator
from .repairs import async_review_cloud_schedules

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
]

type PelicanConfigEntry = ConfigEntry[PelicanData]


async def async_setup_entry(hass: HomeAssistant, entry: PelicanConfigEntry) -> bool:
    """Set up a Pelican site from a config entry."""
    api = PelicanApi(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    interval = timedelta(
        seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    thermostats = PelicanCoordinator(hass, entry, api, interval)
    await thermostats.async_config_entry_first_refresh()

    schedules = PelicanScheduleCoordinator(
        hass, entry, api, timedelta(seconds=SCHEDULE_SCAN_INTERVAL)
    )
    # Deliberately NOT async_config_entry_first_refresh: a site that refuses
    # ThermostatSchedule reads must still get working climate entities. The
    # coordinator logs the failure and the schedule entities report unknown.
    await schedules.async_refresh()

    entry.runtime_data = PelicanData(
        api=api, thermostats=thermostats, schedules=schedules
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Re-evaluate the "a cloud schedule will override your automations" warning
    # whenever either side changes: a schedule can be added in Site Manager, and
    # a thermostat's schedule can be switched on or off from here.
    entry.async_on_unload(
        thermostats.async_add_listener(
            lambda: async_review_cloud_schedules(hass, entry)
        )
    )
    entry.async_on_unload(
        schedules.async_add_listener(lambda: async_review_cloud_schedules(hass, entry))
    )
    async_review_cloud_schedules(hass, entry)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: PelicanConfigEntry
) -> None:
    """Reload the entry so a new poll interval takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: PelicanConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
