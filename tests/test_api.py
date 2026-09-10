"""Tests for the raw api.cgi client."""

from __future__ import annotations

import re

import aiohttp
from aioresponses import aioresponses
import pytest

from custom_components.pelican.api import (
    SCHEDULE_ATTRIBUTES,
    THERMOSTAT_ATTRIBUTES,
    PelicanApi,
    normalize_host,
)
from custom_components.pelican.errors import (
    PelicanApiError,
    PelicanAuthError,
    PelicanConnectionError,
    PelicanResponseError,
    PelicanTimeoutError,
)

from .conftest import THERMOSTAT_LOBBY, THERMOSTAT_SHOP

ANY_API = re.compile(r"^https://[^/]+/api\.cgi.*$")


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("site.officeclimatecontrol.net", "site.officeclimatecontrol.net"),
        ("https://site.officeclimatecontrol.net", "site.officeclimatecontrol.net"),
        ("https://site.officeclimatecontrol.net/", "site.officeclimatecontrol.net"),
        (
            "http://site.officeclimatecontrol.net/#_indexPage",
            "site.officeclimatecontrol.net",
        ),
        ("  site.officeclimatecontrol.net  ", "site.officeclimatecontrol.net"),
    ],
)
def test_normalize_host(supplied: str, expected: str) -> None:
    """A hostname, a URL and a pasted address all reduce to the same host."""
    assert normalize_host(supplied) == expected


async def test_get_single_thermostat_is_wrapped_in_a_list(hass) -> None:
    """A site with one thermostat returns an object, not an array."""
    api = PelicanApi(_session(hass), "site.example.com", "u", "p")
    with aioresponses() as mocked:
        mocked.get(
            ANY_API,
            payload={"Thermostat": dict(THERMOSTAT_LOBBY), "success": "1"},
        )
        result = await api.async_get_thermostats()

    assert len(result) == 1
    assert result[0]["serialNo"] == "41111"


async def test_get_multiple_thermostats(hass) -> None:
    """Several thermostats come back as a list and are passed through."""
    api = PelicanApi(_session(hass), "site.example.com", "u", "p")
    with aioresponses() as mocked:
        mocked.get(
            ANY_API,
            payload={
                "Thermostat": [dict(THERMOSTAT_LOBBY), dict(THERMOSTAT_SHOP)],
                "success": "1",
            },
        )
        result = await api.async_get_thermostats()

    assert [item["serialNo"] for item in result] == ["41111", "41112"]


async def test_request_asks_for_every_polled_attribute(hass) -> None:
    """The value list sent to the site matches THERMOSTAT_ATTRIBUTES (rule 3)."""
    api = PelicanApi(_session(hass), "site.example.com", "u", "p")
    with aioresponses() as mocked:
        mocked.get(ANY_API, payload={"Thermostat": [], "success": "1"})
        await api.async_get_thermostats()
        request = next(iter(mocked.requests.values()))[0]

    sent = request.kwargs["params"]["value"].split(";")
    assert sent == list(THERMOSTAT_ATTRIBUTES)


async def test_bad_credentials_raise_auth_error(hass) -> None:
    """An authentication message is distinguished from a generic failure."""
    api = PelicanApi(_session(hass), "site.example.com", "u", "p")
    with aioresponses() as mocked:
        mocked.get(
            ANY_API,
            payload={"success": "0", "message": "Invalid username or password."},
        )
        with pytest.raises(PelicanAuthError):
            await api.async_get_thermostats()


async def test_other_failure_raises_generic_error(hass) -> None:
    """A non-auth failure stays a PelicanError so it retries rather than reauths."""
    api = PelicanApi(_session(hass), "site.example.com", "u", "p")
    with aioresponses() as mocked:
        mocked.get(
            ANY_API,
            payload={
                "success": "0",
                "message": "No thermostats found matching selection criteria.",
            },
        )
        with pytest.raises(PelicanApiError) as err:
            await api.async_get_thermostats()
        assert not isinstance(err.value, PelicanAuthError)


async def test_non_json_response_raises(hass) -> None:
    """A login page instead of JSON is reported as a site problem, not a crash."""
    api = PelicanApi(_session(hass), "site.example.com", "u", "p")
    with aioresponses() as mocked:
        mocked.get(ANY_API, body="<html><body>Sign in</body></html>")
        with pytest.raises(PelicanResponseError, match="non-JSON"):
            await api.async_get_thermostats()


async def test_set_builds_semicolon_delimited_pairs(hass) -> None:
    """Set requests select by serial and send colon/semicolon delimited pairs."""
    api = PelicanApi(_session(hass), "site.example.com", "u", "p")
    with aioresponses() as mocked:
        mocked.get(ANY_API, payload={"success": "1", "message": "Updated 1"})
        await api.async_set_thermostat("41111", {"system": "Cool", "coolSetting": 72})
        request = next(iter(mocked.requests.values()))[0]

    params = request.kwargs["params"]
    assert params["request"] == "set"
    assert params["selection"] == "serialNo:41111;"
    assert params["value"] == "system:Cool;coolSetting:72"


async def test_set_with_no_values_makes_no_request(hass) -> None:
    """An empty change is a no-op, not an empty write."""
    api = PelicanApi(_session(hass), "site.example.com", "u", "p")
    with aioresponses() as mocked:
        await api.async_set_thermostat("41111", {})
        assert not mocked.requests


def _session(hass):
    """Return the shared Home Assistant aiohttp session."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    return async_get_clientsession(hass)


async def test_http_401_is_an_auth_error(hass) -> None:
    """An HTTP 401 becomes reauth, not a retry loop."""
    api = PelicanApi(_session(hass), "site.example.com", "u", "p")
    with aioresponses() as mocked:
        mocked.get(ANY_API, status=401, body="Unauthorized")
        with pytest.raises(PelicanAuthError, match="401"):
            await api.async_get_thermostats()


async def test_http_500_is_a_response_error(hass) -> None:
    """A server error is reported as a response problem, not bad credentials."""
    api = PelicanApi(_session(hass), "site.example.com", "u", "p")
    with aioresponses() as mocked:
        mocked.get(ANY_API, status=500, body="boom")
        with pytest.raises(PelicanResponseError, match="500"):
            await api.async_get_thermostats()


async def test_connection_failure_is_distinct(hass) -> None:
    """An unreachable host is a connection error, distinguishable from the rest."""
    api = PelicanApi(_session(hass), "site.example.com", "u", "p")
    with aioresponses() as mocked:
        mocked.get(
            ANY_API, exception=aiohttp.ClientConnectorError(None, OSError("no route"))
        )
        with pytest.raises(PelicanConnectionError) as err:
            await api.async_get_thermostats()
    assert not isinstance(err.value, PelicanAuthError)


async def test_timeout_is_distinct(hass) -> None:
    """A hung site is a timeout, not a generic network error."""
    api = PelicanApi(_session(hass), "site.example.com", "u", "p")
    with aioresponses() as mocked:
        mocked.get(ANY_API, exception=TimeoutError())
        with pytest.raises(PelicanTimeoutError):
            await api.async_get_thermostats()


async def test_permission_message_is_treated_as_auth(hass) -> None:
    """A permission refusal routes to reauth rather than being retried forever."""
    api = PelicanApi(_session(hass), "site.example.com", "u", "p")
    with aioresponses() as mocked:
        mocked.get(
            ANY_API,
            payload={"success": "0", "message": "User does not have permission."},
        )
        with pytest.raises(PelicanAuthError):
            await api.async_get_thermostats()


async def test_no_credential_reaches_the_log(hass, caplog) -> None:
    """Rule 11: the request URL carries credentials and must never be logged."""
    import logging

    api = PelicanApi(_session(hass), "site.example.com", "user@example.com", "sekrit")
    with (
        caplog.at_level(logging.DEBUG, logger="custom_components.pelican.api"),
        aioresponses() as mocked,
    ):
        mocked.get(ANY_API, payload={"Thermostat": [], "success": "1"})
        await api.async_get_thermostats()

    assert "sekrit" not in caplog.text
    assert "user@example.com" not in caplog.text


async def test_schedule_request_asks_for_every_polled_attribute(hass) -> None:
    """The schedule value list matches SCHEDULE_ATTRIBUTES (rule 3)."""
    api = PelicanApi(_session(hass), "site.example.com", "u", "p")
    with aioresponses() as mocked:
        mocked.get(ANY_API, payload={"ThermostatSchedule": [], "success": "1"})
        await api.async_get_schedules()
        request = next(iter(mocked.requests.values()))[0]

    params = request.kwargs["params"]
    assert params["object"] == "ThermostatSchedule"
    assert params["value"].split(";") == list(SCHEDULE_ATTRIBUTES)
