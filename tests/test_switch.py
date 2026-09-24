"""Tests for the Pelican switches."""

from __future__ import annotations

from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import State
import pytest
from pytest_homeassistant_custom_component.common import mock_restore_cache

SHOP_SCHEDULE = "switch.shop_schedule"
LOBBY_SCHEDULE = "switch.lobby_schedule"
SHOP_KEYPAD = "switch.shop_keypad_unlocked"


async def _setup(hass, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def _call(hass, service, entity_id):
    await hass.services.async_call(
        "switch", service, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


async def test_schedule_switch_reflects_the_site(hass, mock_api, config_entry) -> None:
    """A named shared schedule reads as on; the name is published."""
    await _setup(hass, config_entry)
    state = hass.states.get(SHOP_SCHEDULE)

    assert state.state == STATE_ON
    assert state.attributes["schedule_name"] == "Weekday Hours"


async def test_turning_off_sends_off(hass, mock_api, config_entry) -> None:
    """Disabling the schedule is what makes a manual setpoint hold."""
    await _setup(hass, config_entry)

    await _call(hass, "turn_off", SHOP_SCHEDULE)

    mock_api.async_set_thermostat.assert_awaited_once_with(
        "thrm1112", {"schedule": "Off"}
    )


async def test_turning_on_restores_the_shared_schedule_name(
    hass, mock_api, config_entry
) -> None:
    """Re-enabling must reattach the same shared schedule, not send a bare On."""
    await _setup(hass, config_entry)

    await _call(hass, "turn_on", SHOP_SCHEDULE)

    mock_api.async_set_thermostat.assert_awaited_once_with(
        "thrm1112", {"schedule": "Weekday Hours"}
    )


async def test_name_survives_a_restart(hass, mock_api, config_entry) -> None:
    """The whole point: a restart between off and on must not lose the name.

    Once `schedule` is Off the shared schedule's name is gone from the API, so
    without RestoreEntity this would send a literal "On" and silently detach the
    thermostat from a schedule other people at the site depend on.
    """
    # The thermostat comes back already switched off at the site, so the live
    # payload carries no name to recover from.
    mock_api.async_get_thermostats.return_value = [
        {**thermostat, "schedule": "Off"}
        for thermostat in mock_api.async_get_thermostats.return_value
    ]
    mock_restore_cache(
        hass,
        [State(SHOP_SCHEDULE, STATE_ON, {"schedule_name": "Weekday Hours"})],
    )

    await _setup(hass, config_entry)
    assert hass.states.get(SHOP_SCHEDULE).state == STATE_OFF

    await _call(hass, "turn_on", SHOP_SCHEDULE)

    mock_api.async_set_thermostat.assert_awaited_once_with(
        "thrm1112", {"schedule": "Weekday Hours"}
    )


async def test_restored_off_is_ignored(hass, mock_api, config_entry) -> None:
    """A restored value of Off is not a schedule name and must not be reused."""
    mock_api.async_get_thermostats.return_value = [
        {**thermostat, "schedule": "Off"}
        for thermostat in mock_api.async_get_thermostats.return_value
    ]
    mock_restore_cache(
        hass, [State(SHOP_SCHEDULE, STATE_OFF, {"schedule_name": "Off"})]
    )

    await _setup(hass, config_entry)
    await _call(hass, "turn_on", SHOP_SCHEDULE)

    mock_api.async_set_thermostat.assert_awaited_once_with(
        "thrm1112", {"schedule": "On"}
    )


async def test_live_value_beats_a_restored_one(hass, mock_api, config_entry) -> None:
    """If the site still reports a name, that wins over whatever was cached."""
    mock_restore_cache(
        hass, [State(SHOP_SCHEDULE, STATE_ON, {"schedule_name": "Stale Name"})]
    )

    await _setup(hass, config_entry)
    await _call(hass, "turn_on", SHOP_SCHEDULE)

    mock_api.async_set_thermostat.assert_awaited_once_with(
        "thrm1112", {"schedule": "Weekday Hours"}
    )


async def test_keypad_switch_maps_to_front_keypad(hass, mock_api, config_entry) -> None:
    """Keypad unlocked reads frontKeypad and writes it back."""
    await _setup(hass, config_entry)
    assert hass.states.get(SHOP_KEYPAD).state == STATE_OFF

    await _call(hass, "turn_on", SHOP_KEYPAD)

    mock_api.async_set_thermostat.assert_awaited_once_with(
        "thrm1112", {"frontKeypad": "On"}
    )


async def test_write_refused_when_two_thermostats_share_a_name(
    hass, mock_api, config_entry
) -> None:
    """Node names are supposed to be unique; if they collide, refuse.

    A selector matching two thermostats writes to both, so the coordinator
    refuses rather than guessing which one was meant.
    """
    from homeassistant.exceptions import HomeAssistantError

    from .conftest import THERMOSTAT_LOBBY, THERMOSTAT_SHOP

    collision = {**THERMOSTAT_SHOP, "nodeName": THERMOSTAT_LOBBY["nodeName"]}
    mock_api.async_get_thermostats.return_value = [
        dict(THERMOSTAT_LOBBY),
        collision,
    ]

    await _setup(hass, config_entry)

    with pytest.raises(HomeAssistantError, match="node name"):
        await _call(hass, "turn_off", SHOP_SCHEDULE)

    mock_api.async_set_thermostat.assert_not_awaited()


async def test_write_refused_when_the_name_is_blank(
    hass, mock_api, config_entry
) -> None:
    """A blank selector changes every thermostat at the site, so nothing is sent."""
    from homeassistant.exceptions import HomeAssistantError

    from .conftest import THERMOSTAT_LOBBY, THERMOSTAT_SHOP

    mock_api.async_get_thermostats.return_value = [
        dict(THERMOSTAT_LOBBY),
        {**THERMOSTAT_SHOP, "nodeName": "   "},
    ]

    await _setup(hass, config_entry)

    with pytest.raises(HomeAssistantError, match="every thermostat"):
        await _call(hass, "turn_off", SHOP_SCHEDULE)

    mock_api.async_set_thermostat.assert_not_awaited()
