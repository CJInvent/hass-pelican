"""Tests for the Pelican switches."""

from __future__ import annotations

from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
import pytest

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
    """The switch is the thermostat's `schedule` attribute, nothing more."""
    await _setup(hass, config_entry)

    assert hass.states.get(SHOP_SCHEDULE).state == STATE_ON
    assert hass.states.get(LOBBY_SCHEDULE).state == STATE_OFF


async def test_turning_on_sends_on(hass, mock_api, config_entry) -> None:
    """Re-enabling sends "On", the value the site accepts."""
    await _setup(hass, config_entry)

    await _call(hass, "turn_on", LOBBY_SCHEDULE)

    mock_api.async_set_thermostat.assert_awaited_once_with(
        "thrm1111", {"schedule": "On"}
    )


async def test_turning_off_sends_off(hass, mock_api, config_entry) -> None:
    """Disabling the schedule is what makes a manual setpoint hold."""
    await _setup(hass, config_entry)

    await _call(hass, "turn_off", SHOP_SCHEDULE)

    mock_api.async_set_thermostat.assert_awaited_once_with(
        "thrm1112", {"schedule": "Off"}
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


async def test_write_refused_when_the_thermostat_is_offline(
    hass, mock_api, config_entry
) -> None:
    """An unplugged thermostat accepts writes and reports success. Refuse them.

    Verified on a live site: a write to a physically unplugged unit returned
    "Updated 1 thermostats". The entity is already unavailable, but that is
    incidental -- the coordinator refuses on its own, so no path that bypasses
    entity availability can report a change that was never delivered.
    """
    from custom_components.pelican.errors import PelicanApiError

    from .conftest import THERMOSTAT_LOBBY, THERMOSTAT_SHOP

    mock_api.async_get_thermostats.return_value = [
        dict(THERMOSTAT_LOBBY),
        {**THERMOSTAT_SHOP, "statusDisplay": "Unreachable"},
    ]
    await _setup(hass, config_entry)

    assert hass.states.get(SHOP_SCHEDULE).state == "unavailable"

    with pytest.raises(PelicanApiError, match="offline"):
        await config_entry.runtime_data.thermostats.async_apply(
            "41112", {"frontKeypad": "Off"}
        )

    mock_api.async_set_thermostat.assert_not_awaited()
