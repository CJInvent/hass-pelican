"""Switches for Pelican thermostat schedule and keypad control."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import PelicanConfigEntry
from .const import ATTR_SCHEDULE_NAME, DOMAIN, SCHEDULE_OFF, SCHEDULE_ON
from .coordinator import PelicanData
from .entity import PelicanEntity
from .errors import PelicanError

_LOGGER = logging.getLogger(__name__)

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


class PelicanScheduleSwitch(PelicanSwitchBase, RestoreEntity):
    """Enables or disables the thermostat's schedule.

    Turning this off is what makes a manual setpoint hold indefinitely instead of
    being overwritten at the next scheduled period.

    Turning it back on has to restore the *same* schedule. Pelican's `schedule`
    attribute holds either "On" (the thermostat's own schedule) or the name of a
    shared schedule, and once it is set to Off the name is gone from the API —
    there is nothing left to read it back from. So the name is remembered here
    and persisted across restarts via RestoreEntity. Without that, a restart
    between the off and the on would send the literal "On" and quietly detach
    the thermostat from a shared schedule that other people at the site rely on.
    """

    _attribute = "schedule"
    _attr_translation_key = "schedule"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, data: PelicanData, serial: str) -> None:
        """Initialize the schedule switch."""
        super().__init__(data, serial)
        self._attr_unique_id = f"{serial}_schedule"
        self._last_active_schedule = SCHEDULE_ON

    async def async_added_to_hass(self) -> None:
        """Restore the remembered schedule name, then track the live one."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            remembered = last_state.attributes.get(ATTR_SCHEDULE_NAME)
            if isinstance(remembered, str) and remembered not in ("", SCHEDULE_OFF):
                self._last_active_schedule = remembered
                _LOGGER.debug(
                    "Restored schedule name %r for thermostat %s",
                    remembered,
                    self._serial,
                )

        # A live value from the site always beats a restored one.
        self._remember_active_schedule()

    def _remember_active_schedule(self) -> None:
        """Capture the schedule name while it is still visible in the API."""
        value = self.attr("schedule")
        if value is not None and value != SCHEDULE_OFF:
            self._last_active_schedule = value

    @callback
    def _handle_coordinator_update(self) -> None:
        """Track the active schedule name on every poll."""
        self._remember_active_schedule()
        super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool | None:
        """Return True when a schedule (own or shared) is driving the thermostat."""
        value = self.attr("schedule")
        if value is None:
            return None
        return value != SCHEDULE_OFF

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the remembered name, which is also what RestoreEntity saves."""
        return {ATTR_SCHEDULE_NAME: self._last_active_schedule}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Re-enable the last known schedule."""
        await self._apply(self._last_active_schedule)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the schedule so manual setpoints hold."""
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
