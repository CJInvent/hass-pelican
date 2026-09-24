"""Constants for the Pelican Wireless integration."""

from __future__ import annotations

DOMAIN = "pelican"

MANUFACTURER = "Pelican Wireless Systems"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 15
MAX_SCAN_INTERVAL = 900

# statusDisplay value the site reports when a thermostat has lost its uplink.
STATUS_UNREACHABLE = "Unreachable"

# Thermostat `schedule` values. Anything other than Off is either "On" (the
# thermostat's own schedule) or the name of a shared schedule.
SCHEDULE_OFF = "Off"
SCHEDULE_ON = "On"

# Attribute the schedule switch publishes and restores across restarts, so that
# re-enabling a schedule restores a shared schedule by name rather than
# detaching the thermostat onto its own.
ATTR_SCHEDULE_NAME = "schedule_name"

# Repairs issue raised while any thermostat still has a cloud schedule running.
ISSUE_CLOUD_SCHEDULE = "cloud_schedule_active"
