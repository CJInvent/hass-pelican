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
from .schedule import next_change

# The coordinators own all I/O; entities never fetch. Nothing to serialize.
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

    This is the entity to gate an automation on. Setting a temperature while
    this is on will hold only until the next set time, which is published as the
    `next_change` attribute.
    """

    _attr_translation_key = "cloud_schedule"
    # The weekly schedule is a list of up to a few dozen rows and never worth
    # writing to the recorder database every state change.
    _unrecorded_attributes = frozenset({"schedule", "next_change_settings"})

    def __init__(self, data: PelicanData, serial: str) -> None:
        """Initialize the cloud-schedule sensor."""
        super().__init__(data, serial)
        self._attr_unique_id = f"{serial}_cloud_schedule"

    @property
    def _entries(self) -> list[Any]:
        """Return this thermostat's parsed schedule entries."""
        schedules = self.data.schedules.data
        return schedules.for_serial(self._serial) if schedules else []

    @property
    def is_on(self) -> bool:
        """Return True when a schedule is both assigned and populated."""
        return thermostat_has_cloud_schedule(self.thermostat, bool(self._entries))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Publish the schedule itself, and when it next acts."""
        entries = self._entries
        schedules = self.data.schedules.data
        upcoming = (
            next_change(entries, schedules.timezone) if schedules and entries else None
        )

        attributes: dict[str, Any] = {
            "schedule_name": self.attr("schedule"),
            "entry_count": len(entries),
            "schedule": [entry.as_dict() for entry in entries],
            # Set times are wall-clock at the site; this names the zone they
            # were resolved against so a wrong answer is diagnosable.
            "site_timezone": schedules.timezone_name if schedules else None,
            "next_change": None,
            "next_change_settings": None,
        }

        if upcoming is not None:
            moment, entry = upcoming
            # Always UTC, so it is an absolute instant rather than a wall
            # clock reading that depends on who is looking at it.
            attributes["next_change"] = moment.isoformat()
            attributes["next_change_settings"] = entry.as_dict()

        return attributes
