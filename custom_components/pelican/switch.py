"""Switches for Pelican thermostat schedule and keypad control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PelicanConfigEntry
from .api import PelicanError
from .coordinator import PelicanCoordinator
from .entity import PelicanEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PelicanConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the schedule and keypad switches for every thermostat."""
    coordinator = entry.runtime_data
    entities: list[PelicanEntity] = []
    for serial in coordinator.data:
        entities.append(PelicanScheduleSwitch(coordinator, serial))
        entities.append(PelicanKeypadSwitch(coordinator, serial))
    async_add_entities(entities)


class PelicanSwitchBase(PelicanEntity, SwitchEntity):
    """Shared set-and-report plumbing for Pelican switches."""

    _attribute: str

    async def _apply(self, value: str) -> None:
        """Write one attribute, converting API failures into HA errors."""
        try:
            await self.coordinator.async_apply(self._serial, {self._attribute: value})
        except PelicanError as err:
            raise HomeAssistantError(
                f"Pelican rejected the change for {self._serial}: {err}"
            ) from err


class PelicanScheduleSwitch(PelicanSwitchBase):
    """Enables or disables the thermostat's schedule.

    Turning this off is what makes a manual setpoint hold indefinitely instead of
    being overwritten at the next scheduled period.
    """

    _attribute = "schedule"
    _attr_translation_key = "schedule"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: PelicanCoordinator, serial: str) -> None:
        """Initialize the schedule switch."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_schedule"
        self._last_active_schedule = "On"

    @property
    def is_on(self) -> bool | None:
        """Return True when a schedule (own or shared) is driving the thermostat."""
        value = self.attr("schedule")
        if value is None:
            return None
        if value != "Off":
            # Remember shared schedule names so turning the switch back on
            # restores the same schedule rather than falling back to "On".
            self._last_active_schedule = value
            return True
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Re-enable the last known schedule."""
        await self._apply(self._last_active_schedule)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the schedule so manual setpoints hold."""
        await self._apply("Off")


class PelicanKeypadSwitch(PelicanSwitchBase):
    """Locks or unlocks the physical keypad on the thermostat."""

    _attribute = "frontKeypad"
    _attr_translation_key = "keypad"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: PelicanCoordinator, serial: str) -> None:
        """Initialize the keypad switch."""
        super().__init__(coordinator, serial)
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
