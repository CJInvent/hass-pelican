"""Tests for the Pelican climate entity."""

from __future__ import annotations

from homeassistant.components.climate import (
    ATTR_HVAC_ACTION,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM
import pytest

LOBBY = "climate.lobby"
SHOP = "climate.shop"


async def _setup(hass, config_entry):
    """Load the integration against the mocked API, in the site's own units.

    The fixture thermostats report Fahrenheit and the Home Assistant test
    harness defaults to metric, so without this every assertion below would be
    against a Celsius value Home Assistant converted for display, and every
    setpoint written would be converted back the other way. Pinning the harness
    to US customary keeps these tests about our logic rather than about unit
    conversion; conversion gets its own test at the bottom of this file.
    """
    hass.config.units = US_CUSTOMARY_SYSTEM
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_entities_created_per_thermostat(hass, mock_api, config_entry) -> None:
    """Each thermostat at the site becomes one climate entity."""
    await _setup(hass, config_entry)

    assert hass.states.get(LOBBY) is not None
    assert hass.states.get(SHOP) is not None


async def test_cool_mode_reports_single_setpoint(hass, mock_api, config_entry) -> None:
    """In Cool, the cool setting is the target and the heat setting is hidden."""
    await _setup(hass, config_entry)
    state = hass.states.get(LOBBY)

    assert state.state == HVACMode.COOL
    assert state.attributes[ATTR_TEMPERATURE] == 74
    assert state.attributes["current_temperature"] == 72.4
    assert state.attributes["current_humidity"] == 44
    assert state.attributes[ATTR_HVAC_ACTION] == HVACAction.COOLING
    assert ATTR_TARGET_TEMP_LOW not in state.attributes


async def test_auto_mode_reports_a_range(hass, mock_api, config_entry) -> None:
    """In Auto, the setpoints are exposed as a low/high pair."""
    await _setup(hass, config_entry)
    state = hass.states.get(SHOP)

    assert state.state == HVACMode.HEAT_COOL
    assert state.attributes[ATTR_TARGET_TEMP_LOW] == 68
    assert state.attributes[ATTR_TARGET_TEMP_HIGH] == 74
    assert state.attributes[ATTR_HVAC_ACTION] == HVACAction.IDLE


async def test_set_temperature_in_cool_writes_cool_setting(
    hass, mock_api, config_entry
) -> None:
    """A single setpoint in Cool maps to coolSetting, not heatSetting."""
    await _setup(hass, config_entry)

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: LOBBY, ATTR_TEMPERATURE: 71},
        blocking=True,
    )

    mock_api.async_set_thermostat.assert_awaited_once_with("41111", {"coolSetting": 71})


async def test_set_range_in_auto_writes_both(hass, mock_api, config_entry) -> None:
    """A range in Auto writes both setpoints in one request."""
    await _setup(hass, config_entry)

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: SHOP,
            ATTR_TARGET_TEMP_LOW: 62,
            ATTR_TARGET_TEMP_HIGH: 80,
        },
        blocking=True,
    )

    mock_api.async_set_thermostat.assert_awaited_once_with(
        "41112", {"heatSetting": 62, "coolSetting": 80}
    )


async def test_single_setpoint_in_auto_is_rejected_upstream(
    hass, mock_api, config_entry
) -> None:
    """Auto advertises a range, so Home Assistant rejects a bare temperature.

    Our own guard never fires here: because supported_features drops
    TARGET_TEMPERATURE while in Auto, the service layer refuses the call before
    the entity is touched. That is the better outcome — the point of this test
    is that the request cannot reach the site, not which layer stopped it.
    """
    await _setup(hass, config_entry)

    with pytest.raises(ServiceValidationError, match="does not support it"):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: SHOP, ATTR_TEMPERATURE: 70},
            blocking=True,
        )

    mock_api.async_set_thermostat.assert_not_awaited()


async def test_single_setpoint_while_switching_into_auto_is_rejected(
    hass, mock_api, config_entry
) -> None:
    """The case our own guard exists for, and the only way to reach it.

    Lobby is in Cool, so it advertises TARGET_TEMPERATURE and the service layer
    lets the call through. Only once we apply the requested hvac_mode does the
    single setpoint become meaningless — so the entity has to catch it.
    """
    await _setup(hass, config_entry)

    with pytest.raises(ServiceValidationError, match="target_temp_low"):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {
                ATTR_ENTITY_ID: LOBBY,
                "hvac_mode": HVACMode.HEAT_COOL,
                ATTR_TEMPERATURE: 70,
            },
            blocking=True,
        )

    mock_api.async_set_thermostat.assert_not_awaited()


async def test_set_hvac_mode_uses_pelican_vocabulary(
    hass, mock_api, config_entry
) -> None:
    """heat_cool maps to Pelican's 'Auto', not to a literal 'heat_cool'."""
    await _setup(hass, config_entry)

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: LOBBY, "hvac_mode": HVACMode.HEAT_COOL},
        blocking=True,
    )

    mock_api.async_set_thermostat.assert_awaited_once_with("41111", {"system": "Auto"})


async def test_api_failure_surfaces_as_home_assistant_error(
    hass, mock_api, config_entry
) -> None:
    """A rejected write raises rather than silently reporting success (rule 9)."""
    from custom_components.pelican.errors import PelicanError

    await _setup(hass, config_entry)
    mock_api.async_set_thermostat.side_effect = PelicanError("Setting out of range")

    with pytest.raises(HomeAssistantError, match="Setting out of range"):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: LOBBY, ATTR_TEMPERATURE: 71},
            blocking=True,
        )


async def test_unreachable_thermostat_goes_unavailable(
    hass, mock_api, config_entry, freezer
) -> None:
    """A thermostat that loses its uplink stops reporting stale values."""
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    from .conftest import THERMOSTAT_LOBBY, THERMOSTAT_SHOP

    await _setup(hass, config_entry)
    assert hass.states.get(LOBBY).state == HVACMode.COOL

    offline = {**THERMOSTAT_LOBBY, "statusDisplay": "Unreachable"}
    mock_api.async_get_thermostats.return_value = [offline, dict(THERMOSTAT_SHOP)]

    freezer.tick(timedelta(seconds=90))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(LOBBY).state == STATE_UNAVAILABLE
    assert hass.states.get(SHOP).state == HVACMode.HEAT_COOL


async def test_metric_home_assistant_converts_from_the_site_unit(
    hass, mock_api, config_entry
) -> None:
    """A Fahrenheit site shown in a metric Home Assistant converts for display.

    The thermostat's own temperatureFormat is authoritative for what the API
    returns; Home Assistant converts from there to whatever the user's system
    is set to. This is the path every other test in this file deliberately
    avoids, so it is worth pinning down once.
    """
    hass.config.units = METRIC_SYSTEM
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(LOBBY)

    # 74 F and 72.4 F, rendered in Celsius.
    assert state.attributes[ATTR_TEMPERATURE] == pytest.approx(23.3, abs=0.2)
    assert state.attributes["current_temperature"] == pytest.approx(22.4, abs=0.2)
