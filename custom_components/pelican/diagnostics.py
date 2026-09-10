"""Diagnostics for the Pelican Wireless integration.

Downloadable from the integration page. This is what to attach to a bug report:
it shows the coordinator health, the raw thermostat payloads and the parsed
schedules, with credentials removed.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import PelicanConfigEntry

# The host is kept: it is the single most useful field for diagnosing a
# reachability problem and is not a secret on its own.
REDACT_CONFIG = {CONF_USERNAME, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PelicanConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data
    schedules = data.schedules.data or {}

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), REDACT_CONFIG),
            "options": dict(entry.options),
        },
        "coordinators": {
            "thermostats": {
                "last_update_success": data.thermostats.last_update_success,
                "last_exception": _describe(data.thermostats.last_exception),
                "update_interval": str(data.thermostats.update_interval),
                "count": len(data.thermostats.data or {}),
            },
            "schedules": {
                "last_update_success": data.schedules.last_update_success,
                "last_exception": _describe(data.schedules.last_exception),
                "update_interval": str(data.schedules.update_interval),
                "thermostats_with_entries": len(schedules),
            },
        },
        # Thermostat payloads contain no personal data: names, setpoints,
        # temperatures and serials.
        "thermostats": data.thermostats.data or {},
        "schedules": {
            serial: [entry.as_dict() for entry in entries]
            for serial, entries in schedules.items()
        },
    }


def _describe(err: BaseException | None) -> str | None:
    """Render an exception as type and message, without a traceback."""
    if err is None:
        return None
    return f"{type(err).__name__}: {err}"
