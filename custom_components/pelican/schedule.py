"""Reading Pelican recurring schedules and working out what they will do next.

Pelican schedules are the single most common reason a setpoint pushed from a
Home Assistant automation quietly reverts: the site reasserts its own schedule
at the next set time and nothing in Home Assistant says so. This module turns
the raw ThermostatSchedule rows into something the integration can show and warn
about.

Nothing here writes a schedule. Editing schedules belongs in Site Manager, where
the other people who share the site can see the change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
import logging
from typing import Any

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Pelican's dayOfWeek values, indexed to match datetime.weekday() where Monday
# is 0. "Vacation" is also a valid dayOfWeek but is not a weekday — entries on
# it only apply while the site is in vacation mode, which the API does not
# expose, so they are excluded from next-change math rather than guessed at.
WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
VACATION = "Vacation"


def field(entry: dict[str, Any], key: str) -> str | None:
    """Read one schedule attribute as a trimmed string, or None when blank.

    Every schedule attribute is read through this helper so
    scripts/check-consistency.py can verify that what we read is what we poll
    (dev rule 3).
    """
    value = entry.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def field_int(entry: dict[str, Any], key: str) -> int | None:
    """Read one schedule attribute as an int, or None when it isn't numeric."""
    value = field(entry, key)
    if value is None:
        return None
    try:
        return round(float(value))
    except ValueError:
        return None


def parse_start_time(raw: str | None) -> time | None:
    """Parse Pelican's 24-hour startTime into a time.

    The documented format is a 24-hour string. Sites in the field have been seen
    to render it with and without a leading zero and with or without seconds, so
    all three are accepted; anything else returns None rather than raising, so
    one malformed row cannot take down the whole poll.
    """
    if not raw:
        return None
    text = raw.strip()
    if ":" not in text and text.isdigit() and len(text) in (3, 4):
        text = f"{text[:-2]}:{text[-2:]}"
    parts = text.split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        return None
    return time(hour, minute, second)


@dataclass(frozen=True, slots=True)
class ScheduleEntry:
    """One set time in a thermostat's recurring weekly schedule."""

    day: str
    start: time
    system: str | None
    heat_setting: int | None
    cool_setting: int | None
    fan: str | None

    @property
    def is_vacation(self) -> bool:
        """Return True for entries that only apply in site vacation mode."""
        return self.day == VACATION

    def as_dict(self) -> dict[str, Any]:
        """Render for display as an entity attribute."""
        return {
            "day": self.day,
            "time": self.start.strftime("%H:%M"),
            "system": self.system,
            "heat_setting": self.heat_setting,
            "cool_setting": self.cool_setting,
            "fan": self.fan,
        }


def parse_entries(rows: list[dict[str, Any]]) -> dict[str, list[ScheduleEntry]]:
    """Group raw ThermostatSchedule rows into per-serial weekly schedules.

    Rows that cannot be parsed are counted and logged once rather than raised:
    an unreadable schedule row should degrade the warning, not break climate
    control.
    """
    schedules: dict[str, list[ScheduleEntry]] = {}
    skipped = 0

    for row in rows:
        serial = field(row, "serialNo")
        day = field(row, "dayOfWeek")
        start = parse_start_time(field(row, "startTime"))
        if not serial or not day or start is None:
            skipped += 1
            continue
        if day not in WEEKDAYS and day != VACATION:
            skipped += 1
            continue
        schedules.setdefault(serial, []).append(
            ScheduleEntry(
                day=day,
                start=start,
                system=field(row, "system"),
                heat_setting=field_int(row, "heatSetting"),
                cool_setting=field_int(row, "coolSetting"),
                fan=field(row, "fan"),
            )
        )

    if skipped:
        _LOGGER.warning(
            "Ignored %s schedule row(s) that could not be parsed; the schedule "
            "warning for the affected thermostats may be incomplete",
            skipped,
        )

    for entries in schedules.values():
        entries.sort(key=lambda entry: (entry.day, entry.start))

    return schedules


def next_change(
    entries: list[ScheduleEntry], now: datetime | None = None
) -> tuple[datetime, ScheduleEntry] | None:
    """Return when the schedule next changes the thermostat, and to what.

    Walks forward from now through the next seven days. Times are interpreted in
    Home Assistant's configured timezone; if Home Assistant and the Pelican site
    are set to different timezones this will be off by the difference, which is
    why the timezone is stated on the entity rather than assumed to be obvious.
    """
    weekly = [entry for entry in entries if not entry.is_vacation]
    if not weekly:
        return None

    now = now or dt_util.now()
    by_day: dict[str, list[ScheduleEntry]] = {}
    for entry in weekly:
        by_day.setdefault(entry.day, []).append(entry)

    for offset in range(8):
        candidate_date = (now + timedelta(days=offset)).date()
        day_name = WEEKDAYS[candidate_date.weekday()]
        for entry in sorted(by_day.get(day_name, []), key=lambda item: item.start):
            moment = datetime.combine(candidate_date, entry.start, tzinfo=now.tzinfo)
            if moment > now:
                return moment, entry

    return None
