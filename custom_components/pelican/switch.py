"""Switches for Pelican thermostat schedule and keypad control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PelicanConfigEntry
from .const import DOMAIN, SCHEDULE_OFF, SCHEDULE_ON
from .coordinator import PelicanData
from .entity import PelicanEntity
from .errors import PelicanError

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PelicanConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the schedule and keypad switches for every thermostat."""
    data = entry.runtime_data
    entities: list[PelicanEntity] = []
    for serial in data.thermostats.data or {}:
        entities.append(PelicanScheduleSwitch(data, serial))
        entities.append(PelicanKeypadSwitch(data, serial))
    async_add_entities(entities)


class PelicanSwitchBase(PelicanEntity, SwitchEntity):
    """Shared set-and-report plumbing for Pelican switches."""

    _attribute: str

    async def _apply(self, value: str) -> None:
        """Write one attribute, converting API failures into HA errors."""
        try:
            await self.data.thermostats.async_apply(
                self._serial, {self._attribute: value}
            )
        except PelicanError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={
                    "name": str(self.name or self._serial),
                    "error": str(err),
                },
            ) from err


class PelicanScheduleSwitch(PelicanSwitchBase):
    """Turns the thermostat's Pelican cloud schedule on or off.

    Off is the intended state: schedules belong in Home Assistant automations,
    and a Pelican schedule running underneath them overwrites their setpoints at
    every set time. The Repairs fix turns every one off at once; this switch is
    the per-thermostat equivalent. Off pauses the schedule without deleting it
    (verified live), so On restores the same set times.
    """

    _attribute = "schedule"
    _attr_translation_key = "schedule"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, data: PelicanData, serial: str) -> None:
        """Initialize the schedule switch."""
        super().__init__(data, serial)
        self._attr_unique_id = f"{serial}_schedule"

    @property
    def is_on(self) -> bool | None:
        """Return True when a Pelican schedule is driving the thermostat."""
        value = self.attr("schedule")
        if value is None:
            return None
        return value != SCHEDULE_OFF

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Re-enable the thermostat's Pelican schedule."""
        await self._apply(SCHEDULE_ON)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the Pelican schedule so Home Assistant owns the setpoints."""
        await self._apply(SCHEDULE_OFF)


class PelicanKeypadSwitch(PelicanSwitchBase):
    """Locks or unlocks the physical keypad on the thermostat."""

    _attribute = "frontKeypad"
    _attr_translation_key = "keypad"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, data: PelicanData, serial: str) -> None:
        """Initialize the keypad switch."""
        super().__init__(data, serial)
        self._attr_unique_id = f"{serial}_keypad"

    @property
    def is_on(self) -> bool | None:
        """Return True when the keypad is unlocked."""
        value = self.attr("frontKeypad")
        if value is None:
            return None
        return value == "On"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Unlock the keypad."""
        await self._apply("On")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Lock the keypad."""
        await self._apply("Off")
