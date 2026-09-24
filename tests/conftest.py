"""Shared fixtures for the Pelican integration tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pelican.const import DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"

HOST = "dpsol-dethac.officeclimatecontrol.net"
API_URL = f"https://{HOST}/api.cgi"

# One thermostat in Cool, one in Auto with a CO2 sensor and a shared schedule.
THERMOSTAT_LOBBY = {
    "name": "Lobby",
    "serialNo": "41111",
    "nodeName": "thrm1111",
    "modelNo": "TC2-W",
    "version": "3.2.1",
    "system": "Cool",
    "heatSetting": "68",
    "coolSetting": "74",
    "fan": "Auto",
    "temperature": "72.4",
    "humidity": "44",
    "co2Level": "0",
    "runStatus": "Cool-Stage1",
    "statusDisplay": "Cool Running",
    "setBy": "Schedule",
    "schedule": "On",
    "frontKeypad": "On",
    "temperatureFormat": "Fahrenheit",
    "minHeatSetting": "55",
    "maxHeatSetting": "80",
    "minCoolSetting": "65",
    "maxCoolSetting": "90",
}

THERMOSTAT_SHOP = {
    **THERMOSTAT_LOBBY,
    "name": "Shop ",  # trailing space: the site treats it as part of the name
    "serialNo": "41112",
    "nodeName": "thrm1112",
    "system": "Auto",
    "runStatus": "Off",
    "statusDisplay": "Space Satisfied",
    "co2Level": "780",
    "schedule": "Weekday Hours",
    "frontKeypad": "Off",
    "setBy": "Remote",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Make Home Assistant load custom_components/ during tests."""
    return


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry for the fake site."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=HOST,
        unique_id=HOST,
        data={
            "host": HOST,
            "username": "ha@example.com",
            "password": "hunter2",
        },
    )


@pytest.fixture
def mock_api() -> Generator[AsyncMock]:
    """Patch the API so entity tests never touch HTTP."""
    with (
        patch("custom_components.pelican.PelicanApi", autospec=True) as mock_class,
        patch("custom_components.pelican.config_flow.PelicanApi", new=mock_class),
    ):
        api = mock_class.return_value
        api.host = HOST
        api.url = API_URL
        api.async_get_thermostats = AsyncMock(
            return_value=[dict(THERMOSTAT_LOBBY), dict(THERMOSTAT_SHOP)]
        )
        api.async_validate = AsyncMock(
            return_value=[dict(THERMOSTAT_LOBBY), dict(THERMOSTAT_SHOP)]
        )
        api.async_set_thermostat = AsyncMock(return_value=None)
        yield api
