"""Binary sensors for Pelican thermostats."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PelicanConfigEntry
from .coordinator import PelicanData
from .entity import PelicanEntity
from .repairs import thermostat_has_cloud_schedule

# The coordinator owns all I/O; entities never fetch. Nothing to serialize.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PelicanConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the cloud-schedule binary sensor for every thermostat."""
    data = entry.runtime_data
    async_add_entities(
        PelicanCloudScheduleSensor(data, serial)
        for serial in (data.thermostats.data or {})
    )


class PelicanCloudScheduleSensor(PelicanEntity, BinarySensorEntity):
    """On while a Pelican-side schedule can override Home Assistant.

    This is the entity to gate an automation on. A temperature set while this is
    on holds only until the schedule's next set time and then reverts, with no
    error anywhere.

    It cannot tell you *when* that will happen: the site refuses to serve
    schedule contents (both ThermostatSchedule and SharedSchedule return
    "currently unsupported"), and the thermostat exposes nothing about its own
    schedule beyond this flag. `set_by` on the climate entity is the confirmed
    after-the-fact signal: it reads "Schedule" once a schedule has applied a set
    time (observed live alongside "Station" for manual changes at the unit).
    """

    _attr_translation_key = "cloud_schedule"

    def __init__(self, data: PelicanData, serial: str) -> None:
        """Initialize the cloud-schedule sensor."""
        super().__init__(data, serial)
        self._attr_unique_id = f"{serial}_cloud_schedule"

    @property
    def is_on(self) -> bool:
        """Return True when a schedule is driving the thermostat."""
        return thermostat_has_cloud_schedule(self.thermostat)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Publish which schedule is assigned, when the site names one."""
        return {"schedule_name": self.attr("schedule")}
