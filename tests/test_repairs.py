"""Tests for the Pelican cloud-schedule Repairs warning.

This is the integration's one piece of opinion: schedules belong in Home
Assistant automations, so a thermostat running a Pelican cloud schedule is
reported as something to fix.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.pelican.const import DOMAIN, ISSUE_CLOUD_SCHEDULE

from .conftest import THERMOSTAT_LOBBY, THERMOSTAT_SHOP


async def _setup(hass, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


def _issue(hass, config_entry):
    return ir.async_get(hass).async_get_issue(
        DOMAIN, f"{ISSUE_CLOUD_SCHEDULE}_{config_entry.entry_id}"
    )


async def test_raised_for_thermostats_running_a_schedule(
    hass, mock_api, config_entry
) -> None:
    """Only thermostats with a schedule on are named, with names cleaned up."""
    await _setup(hass, config_entry)

    issue = _issue(hass, config_entry)
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.WARNING
    # "Shop " on the site; displayed without the trailing space. Lobby is off.
    assert issue.translation_placeholders["thermostats"] == "Shop"
    assert issue.translation_placeholders["count"] == "1"
    assert issue.is_fixable
    assert issue.data == {"entry_id": config_entry.entry_id}


async def test_not_raised_when_no_schedules_run(hass, mock_api, config_entry) -> None:
    """A site where every schedule is off has nothing to warn about."""
    mock_api.async_get_thermostats.return_value = [
        dict(THERMOSTAT_LOBBY),
        {**THERMOSTAT_SHOP, "schedule": "Off"},
    ]

    await _setup(hass, config_entry)

    assert _issue(hass, config_entry) is None


async def test_clears_once_the_schedule_is_turned_off(
    hass, mock_api, config_entry, freezer
) -> None:
    """The warning goes away on the next poll after the schedule is turned off."""
    await _setup(hass, config_entry)
    assert _issue(hass, config_entry) is not None

    mock_api.async_get_thermostats.return_value = [
        dict(THERMOSTAT_LOBBY),
        {**THERMOSTAT_SHOP, "schedule": "Off"},
    ]
    freezer.tick(timedelta(seconds=90))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert _issue(hass, config_entry) is None


async def test_reappears_if_a_schedule_is_turned_back_on(
    hass, mock_api, config_entry, freezer
) -> None:
    """Someone re-enabling a schedule in Site Manager is caught on the next poll."""
    mock_api.async_get_thermostats.return_value = [
        dict(THERMOSTAT_LOBBY),
        {**THERMOSTAT_SHOP, "schedule": "Off"},
    ]
    await _setup(hass, config_entry)
    assert _issue(hass, config_entry) is None

    mock_api.async_get_thermostats.return_value = [
        {**THERMOSTAT_LOBBY, "schedule": "On"},
        {**THERMOSTAT_SHOP, "schedule": "Off"},
    ]
    freezer.tick(timedelta(seconds=90))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    issue = _issue(hass, config_entry)
    assert issue is not None
    assert issue.translation_placeholders["thermostats"] == "Lobby"


def _fix_flow(hass, config_entry):
    """Build the fix flow the way the Repairs manager would.

    Driven directly rather than through the repairs websocket API, which
    pytest-homeassistant-custom-component does not ship helpers for.
    """
    from custom_components.pelican.repairs import async_create_fix_flow

    issue = _issue(hass, config_entry)
    assert issue is not None
    assert issue.is_fixable

    async def build():
        flow = await async_create_fix_flow(hass, issue.issue_id, issue.data)
        flow.hass = hass
        flow.handler = DOMAIN
        flow.flow_id = "test"
        flow.context = {}
        return flow

    return build()


async def test_fix_turns_every_running_schedule_off(
    hass, mock_api, config_entry
) -> None:
    """Confirming the fix writes schedule:Off to each affected thermostat."""
    from homeassistant.data_entry_flow import FlowResultType

    mock_api.async_get_thermostats.return_value = [
        {**THERMOSTAT_LOBBY, "schedule": "On"},
        dict(THERMOSTAT_SHOP),
    ]
    await _setup(hass, config_entry)

    flow = await _fix_flow(hass, config_entry)
    result = await flow.async_step_init()
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"]["thermostats"] == "Lobby, Shop"

    result = await flow.async_step_confirm({})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    written = {call.args for call in mock_api.async_set_thermostat.await_args_list}
    assert written == {
        ("thrm1111", {"schedule": "Off"}),
        ("thrm1112", {"schedule": "Off"}),
    }


async def test_fix_continues_past_an_offline_thermostat(
    hass, mock_api, config_entry
) -> None:
    """An offline thermostat is refused; the others still get turned off.

    The coordinator refuses writes to an offline unit because the site would
    report success without delivering it. That refusal must not abort the rest
    of the fix, and the user is told exactly which one is left.
    """
    from homeassistant.data_entry_flow import FlowResultType

    mock_api.async_get_thermostats.return_value = [
        {**THERMOSTAT_LOBBY, "schedule": "On"},
        {**THERMOSTAT_SHOP, "statusDisplay": "Unreachable"},
    ]
    await _setup(hass, config_entry)

    flow = await _fix_flow(hass, config_entry)
    await flow.async_step_init()
    result = await flow.async_step_confirm({})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "partial"
    assert result["description_placeholders"]["failed"] == "Shop"
    # Lobby was written; offline Shop never reached the wire.
    mock_api.async_set_thermostat.assert_awaited_once_with(
        "thrm1111", {"schedule": "Off"}
    )


async def test_fix_uses_the_live_list_not_the_issue_snapshot(
    hass, mock_api, config_entry
) -> None:
    """If schedules were already turned off since the issue was raised, finish."""
    from homeassistant.data_entry_flow import FlowResultType

    await _setup(hass, config_entry)
    flow = await _fix_flow(hass, config_entry)

    # Someone turned Shop's schedule off in Site Manager after the issue appeared.
    config_entry.runtime_data.thermostats.data["41112"]["schedule"] = "Off"

    result = await flow.async_step_init()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    mock_api.async_set_thermostat.assert_not_awaited()
