"""Constants for the Pelican Wireless integration."""

from __future__ import annotations

DOMAIN = "pelican"

MANUFACTURER = "Pelican Wireless Systems"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 15
MAX_SCAN_INTERVAL = 900

# statusDisplay value the site reports for an offline thermostat. Verified: an
# unplugged unit reports this, with its other values frozen at last-known.
STATUS_UNREACHABLE = "Unreachable"

# Thermostat `schedule` values. "On" and "Off" are the only ones observed live,
# and writing "On" back is accepted. Pelican's docs say a shared schedule's name
# can appear here too; unconfirmed.
SCHEDULE_OFF = "Off"
SCHEDULE_ON = "On"

# Attribute the schedule switch publishes and restores across restarts: the
# last schedule value seen while active, sent back when re-enabled.
ATTR_SCHEDULE_NAME = "schedule_name"

# Repairs issue raised while any thermostat still has a cloud schedule running.
ISSUE_CLOUD_SCHEDULE = "cloud_schedule_active"
