"""The cloud-schedule warning and its one-click fix, via Home Assistant Repairs.

Schedules belong in Home Assistant automations. A Pelican cloud schedule running
underneath them overwrites their setpoints at every set time, and every write
succeeds, so nothing ever reports a failure. The integration therefore treats a
running Pelican schedule as a misconfiguration: an issue in Settings > Repairs
names every thermostat running one, and fixing it turns those schedules off.

Turning a schedule off is safe, verified against a live site: `schedule:Off`
keeps the current setpoints, and it pauses the schedule rather than deleting it.
Every set time survives and `schedule:On` brings it back. While off, Site Manager
shows the thermostat's schedule as "None".
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, ISSUE_CLOUD_SCHEDULE, SCHEDULE_OFF
from .errors import PelicanError

if TYPE_CHECKING:
    from . import PelicanConfigEntry
    from .coordinator import PelicanData

_LOGGER = logging.getLogger(__name__)


def thermostat_has_cloud_schedule(thermostat: dict[str, Any]) -> bool:
    """Return True when a Pelican cloud schedule is running on this thermostat."""
    setting = str(thermostat.get("schedule") or "").strip()
    return bool(setting) and setting != SCHEDULE_OFF


def _display_name(serial: str, thermostat: dict[str, Any]) -> str:
    """Return a thermostat's name for display.

    Names are only shown here -- writes select by nodeName -- so the trailing
    spaces sites routinely carry ("Sales ") are stripped.
    """
    return str(thermostat.get("name") or "").strip() or serial


def scheduled_thermostats(data: PelicanData) -> list[tuple[str, str]]:
    """Return (serial, display name) for every thermostat running a schedule."""
    return sorted(
        (
            (serial, _display_name(serial, thermostat))
            for serial, thermostat in (data.thermostats.data or {}).items()
            if thermostat_has_cloud_schedule(thermostat)
        ),
        key=lambda item: item[1],
    )


def _issue_id(entry: PelicanConfigEntry) -> str:
    return f"{ISSUE_CLOUD_SCHEDULE}_{entry.entry_id}"


@callback
def async_review_cloud_schedules(
    hass: HomeAssistant, entry: PelicanConfigEntry
) -> None:
    """Raise or clear the cloud-schedule issue for this site."""
    data = entry.runtime_data
    affected = scheduled_thermostats(data)

    if not affected:
        ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))
        return

    names = ", ".join(name for _, name in affected)
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(entry),
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_CLOUD_SCHEDULE,
        translation_placeholders={
            "site": data.api.host,
            "count": str(len(affected)),
            "thermostats": names,
        },
        data={"entry_id": entry.entry_id},
        learn_more_url="https://github.com/CJInvent/hass-pelican#schedules",
    )
    _LOGGER.debug(
        "Pelican cloud schedules running on %s thermostat(s) at %s: %s",
        len(affected),
        data.api.host,
        names,
    )


class CloudScheduleFixFlow(RepairsFlow):
    """Turn off every Pelican cloud schedule at a site, after confirmation."""

    def __init__(self, entry_id: str) -> None:
        """Remember which site this issue belongs to."""
        self._entry_id = entry_id

    def _data(self) -> PelicanData | None:
        """Return the site's runtime data, or None if it is not loaded."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            return None
        data: PelicanData = entry.runtime_data
        return data

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Start at the confirmation step."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """List the affected thermostats; on submit, turn their schedules off."""
        data = self._data()
        if data is None:
            return self.async_abort(reason="not_loaded")

        # Re-read the live list rather than trusting the issue's placeholders,
        # which were written at the last poll and may be minutes old.
        affected = scheduled_thermostats(data)
        if not affected:
            return self.async_create_entry(title="", data={})

        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                description_placeholders={
                    "site": data.api.host,
                    "count": str(len(affected)),
                    "thermostats": ", ".join(name for _, name in affected),
                },
            )

        failed = await self._turn_off(data, affected)
        if not failed:
            return self.async_create_entry(title="", data={})
        return self._show_partial(failed)

    async def async_step_partial(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Retry the thermostats a previous attempt could not reach."""
        data = self._data()
        if data is None:
            return self.async_abort(reason="not_loaded")

        affected = scheduled_thermostats(data)
        if not affected:
            return self.async_create_entry(title="", data={})

        failed = await self._turn_off(data, affected)
        if not failed:
            return self.async_create_entry(title="", data={})
        return self._show_partial(failed)

    def _show_partial(self, failed: list[str]) -> FlowResult:
        return self.async_show_form(
            step_id="partial",
            description_placeholders={"failed": ", ".join(failed)},
        )

    @staticmethod
    async def _turn_off(
        data: PelicanData, affected: list[tuple[str, str]]
    ) -> list[str]:
        """Turn each schedule off, returning the names that could not be.

        One thermostat failing -- typically because it is offline, which the
        coordinator refuses to write to -- does not stop the rest. Each failure
        is already logged at ERROR by the coordinator with its reason.
        """
        failed: list[str] = []
        for serial, name in affected:
            try:
                await data.thermostats.async_apply(serial, {"schedule": SCHEDULE_OFF})
            except (PelicanError, HomeAssistantError):
                failed.append(name)
        return failed


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """Create the fix flow for a cloud-schedule issue."""
    if not data or "entry_id" not in data:
        raise ValueError(f"Issue {issue_id} carries no config entry")
    return CloudScheduleFixFlow(str(data["entry_id"]))
