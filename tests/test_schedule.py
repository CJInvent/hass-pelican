"""Tests for the cloud-schedule surface."""

from __future__ import annotations

from datetime import datetime, time

from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
import pytest

from custom_components.pelican.const import DOMAIN, ISSUE_CLOUD_SCHEDULE
from custom_components.pelican.schedule import (
    ScheduleEntry,
    next_change,
    parse_entries,
    parse_start_time,
)

from .conftest import SCHEDULE_ROWS

LOBBY_BINARY = "binary_sensor.lobby_cloud_schedule"
SHOP_BINARY = "binary_sensor.shop_cloud_schedule"
SHOP_NEXT = "sensor.shop_next_schedule_change"


async def _setup(hass, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("07:00", time(7, 0)),
        ("7:00", time(7, 0)),
        ("0700", time(7, 0)),
        ("18:30:15", time(18, 30, 15)),
        ("  22:15  ", time(22, 15)),
        ("25:00", None),
        ("not a time", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_start_time(raw, expected) -> None:
    """Tolerate the formats seen in the field; reject the rest without raising."""
    assert parse_start_time(raw) == expected


def test_parse_entries_skips_unusable_rows_without_raising() -> None:
    """One malformed row degrades the warning; it must not break the poll."""
    rows = [
        *SCHEDULE_ROWS,
        {"serialNo": "41112", "dayOfWeek": "Monday", "startTime": "nonsense"},
        {"dayOfWeek": "Monday", "startTime": "08:00"},
        {"serialNo": "41112", "dayOfWeek": "Someday", "startTime": "08:00"},
    ]
    parsed = parse_entries(rows)

    assert set(parsed) == {"41112"}
    assert len(parsed["41112"]) == len(SCHEDULE_ROWS)


def test_next_change_finds_the_next_set_time() -> None:
    """The next change is the next future set time, in Home Assistant's timezone."""
    entries = [
        ScheduleEntry("Monday", time(7, 0), "Auto", 68, 74, "Auto"),
        ScheduleEntry("Monday", time(18, 0), "Auto", 60, 85, "Auto"),
    ]
    # A Monday at 09:00.
    now = datetime(2026, 9, 14, 9, 0, tzinfo=dt_util.UTC)

    result = next_change(entries, now=now)
    assert result is not None
    moment, entry = result
    assert moment == datetime(2026, 9, 14, 18, 0, tzinfo=dt_util.UTC)
    assert entry.heat_setting == 60


def test_next_change_wraps_to_next_week() -> None:
    """After the last set time of the week it rolls forward, not off the end."""
    entries = [ScheduleEntry("Monday", time(7, 0), "Auto", 68, 74, "Auto")]
    now = datetime(2026, 9, 14, 9, 0, tzinfo=dt_util.UTC)

    result = next_change(entries, now=now)
    assert result is not None
    assert result[0] == datetime(2026, 9, 21, 7, 0, tzinfo=dt_util.UTC)


def test_next_change_ignores_vacation_entries() -> None:
    """Vacation entries only apply in site vacation mode, which we cannot see."""
    entries = [ScheduleEntry("Vacation", time(0, 0), "Off", 55, 90, "Auto")]
    assert (
        next_change(entries, now=datetime(2026, 9, 14, 9, 0, tzinfo=dt_util.UTC))
        is None
    )


async def test_binary_sensor_requires_both_halves(hass, mock_api, config_entry) -> None:
    """Schedule assigned AND entries present. Lobby has the first but not the second."""
    await _setup(hass, config_entry)

    assert hass.states.get(SHOP_BINARY).state == "on"
    assert hass.states.get(LOBBY_BINARY).state == "off"


async def test_binary_sensor_publishes_the_schedule(
    hass, mock_api, config_entry
) -> None:
    """The weekly schedule is visible as an attribute, vacation entries included."""
    await _setup(hass, config_entry)
    attributes = hass.states.get(SHOP_BINARY).attributes

    assert attributes["entry_count"] == len(SCHEDULE_ROWS)
    assert attributes["schedule_name"] == "Weekday Hours"
    assert {row["day"] for row in attributes["schedule"]} == {"Monday", "Vacation"}
    assert attributes["next_change"] is not None


async def test_next_change_sensor_exists_and_is_a_timestamp(
    hass, mock_api, config_entry
) -> None:
    """The next set time is exposed as a real timestamp, not a formatted string."""
    await _setup(hass, config_entry)
    state = hass.states.get(SHOP_NEXT)

    assert state is not None
    assert state.attributes["device_class"] == "timestamp"
    assert dt_util.parse_datetime(state.state) is not None


async def test_repair_issue_raised_and_cleared(hass, mock_api, config_entry) -> None:
    """The warning appears while a schedule is live and clears when it is not."""
    await _setup(hass, config_entry)

    registry = ir.async_get(hass)
    issue_id = f"{ISSUE_CLOUD_SCHEDULE}_{config_entry.entry_id}"
    issue = registry.async_get_issue(DOMAIN, issue_id)

    assert issue is not None
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_placeholders["thermostats"] == "Shop"
    assert issue.translation_placeholders["count"] == "1"

    # Turning the schedule off at the site clears the warning on the next poll.
    mock_api.async_get_schedules.return_value = []
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_schedule_failure_does_not_break_climate(
    hass, mock_api, config_entry
) -> None:
    """A site that refuses schedule reads still gets working thermostats."""
    from custom_components.pelican.errors import PelicanApiError

    mock_api.async_get_schedules.side_effect = PelicanApiError("not supported")

    await _setup(hass, config_entry)

    assert hass.states.get("climate.shop") is not None
    assert hass.states.get(SHOP_BINARY).state == "off"
