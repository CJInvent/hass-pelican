"""Constants for the Pelican Wireless integration."""

from __future__ import annotations

DOMAIN = "pelican"

MANUFACTURER = "Pelican Wireless Systems"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 15
MAX_SCAN_INTERVAL = 900

# Schedules are edited by people in Site Manager, not by machines, so a slow
# poll is plenty. Deliberately not user-configurable: nothing is gained by
# reading them more often and it would be one more knob to explain.
SCHEDULE_SCAN_INTERVAL = 1800

# statusDisplay value the site reports when a thermostat has lost its uplink.
STATUS_UNREACHABLE = "Unreachable"

# Thermostat `schedule` value meaning no schedule is driving the thermostat.
SCHEDULE_OFF = "Off"

# Repairs issue raised while any thermostat still has a cloud schedule running.
ISSUE_CLOUD_SCHEDULE = "cloud_schedule_active"
