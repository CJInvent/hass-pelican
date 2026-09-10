"""The cloud-schedule warning, surfaced through Home Assistant Repairs.

A Pelican site schedule reasserts itself at the next set time. When someone
writes an automation that sets a temperature, and the thermostat is on a
schedule, the automation appears to work and then silently unwinds hours later.
That is the single most confusing failure mode of this integration, and it is
not an error anywhere — the API call succeeded.

So it gets said out loud: an issue in Settings > Repairs naming the affected
thermostats, plus a per-thermostat binary sensor for automations to test.
The issue is informational and self-clearing; there is no fix flow, because the
right action depends on whether the schedule or the automation should win.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, ISSUE_CLOUD_SCHEDULE, SCHEDULE_OFF

if TYPE_CHECKING:
    from . import PelicanConfigEntry

_LOGGER = logging.getLogger(__name__)


def thermostat_has_cloud_schedule(
    thermostat: dict[str, str], has_entries: bool
) -> bool:
    """Return True when a Pelican-side schedule can override Home Assistant.

    Both halves have to be true. A thermostat whose `schedule` attribute is Off
    ignores its entries, and a thermostat with the attribute On but no entries
    has nothing to apply.
    """
    setting = str(thermostat.get("schedule") or "").strip()
    return bool(setting) and setting != SCHEDULE_OFF and has_entries


@callback
def async_review_cloud_schedules(
    hass: HomeAssistant, entry: PelicanConfigEntry
) -> None:
    """Raise or clear the cloud-schedule warning for this site."""
    data = entry.runtime_data
    thermostats = data.thermostats.data or {}
    schedules = data.schedules.data or {}

    affected = sorted(
        str(thermostat.get("name") or serial)
        for serial, thermostat in thermostats.items()
        if thermostat_has_cloud_schedule(thermostat, bool(schedules.get(serial)))
    )

    issue_id = f"{ISSUE_CLOUD_SCHEDULE}_{entry.entry_id}"

    if not affected:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_CLOUD_SCHEDULE,
        translation_placeholders={
            "site": data.api.host,
            "count": str(len(affected)),
            "thermostats": ", ".join(affected),
        },
        learn_more_url="https://github.com/CJInvent/hass-pelican#schedules",
    )
    _LOGGER.debug(
        "Cloud schedules are active on %s thermostat(s) at %s: %s",
        len(affected),
        data.api.host,
        ", ".join(affected),
    )
