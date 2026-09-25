"""Tests for the raw api.cgi client.

These use Home Assistant's own `aioclient_mock` fixture rather than a
third-party HTTP mock. The third-party one broke against the aiohttp that
Home Assistant ships (`ClientResponse.__init__() missing 'stream_writer'`),
which is the standard failure mode for anything that reimplements aiohttp
internals. `aioclient_mock` is maintained against the exact aiohttp in use, so
it cannot drift out from under us, and it removes a dev dependency.
"""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest

from custom_components.pelican.api import (
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

HOST = "site.example.com"
API_URL = f"https://{HOST}/api.cgi"


def _api(hass) -> PelicanApi:
    """Build a client bound to the Home Assistant session the mocker patches."""
    return PelicanApi(async_get_clientsession(hass), HOST, "u", "p")


def _query(aioclient_mock, index: int = 0):
    """Return the query string of a recorded request.

    The mocker records the URL with params already merged in, so this is what
    the site would actually have received.
    """
    return aioclient_mock.mock_calls[index][1].query


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


async def test_get_single_thermostat_is_wrapped_in_a_list(hass, aioclient_mock) -> None:
    """A site with one thermostat returns an object, not an array."""
    aioclient_mock.get(
        API_URL, json={"result": {"Thermostat": dict(THERMOSTAT_LOBBY), "success": 1}}
    )

    result = await _api(hass).async_get_thermostats()

    assert len(result) == 1
    assert result[0]["serialNo"] == "41111"


async def test_get_multiple_thermostats(hass, aioclient_mock) -> None:
    """Several thermostats come back as a list and are passed through."""
    aioclient_mock.get(
        API_URL,
        json={
            "result": {
                "Thermostat": [dict(THERMOSTAT_LOBBY), dict(THERMOSTAT_SHOP)],
                "success": 1,
            }
        },
    )

    result = await _api(hass).async_get_thermostats()

    assert [item["serialNo"] for item in result] == ["41111", "41112"]


async def test_request_asks_for_every_polled_attribute(hass, aioclient_mock) -> None:
    """The value list sent to the site matches THERMOSTAT_ATTRIBUTES (rule 3)."""
    aioclient_mock.get(API_URL, json={"result": {"Thermostat": [], "success": 1}})

    await _api(hass).async_get_thermostats()

    query = _query(aioclient_mock)
    assert query["object"] == "Thermostat"
    assert query["value"].split(";") == list(THERMOSTAT_ATTRIBUTES)


async def test_bad_credentials_raise_auth_error(hass, aioclient_mock) -> None:
    """An authentication message is distinguished from a generic failure."""
    aioclient_mock.get(
        API_URL,
        json={"result": {"success": 0, "message": "Invalid username or password."}},
    )

    with pytest.raises(PelicanAuthError):
        await _api(hass).async_get_thermostats()


async def test_permission_message_is_treated_as_auth(hass, aioclient_mock) -> None:
    """A permission refusal routes to reauth rather than being retried forever."""
    aioclient_mock.get(
        API_URL,
        json={"result": {"success": 0, "message": "User does not have permission."}},
    )

    with pytest.raises(PelicanAuthError):
        await _api(hass).async_get_thermostats()


async def test_other_failure_raises_generic_error(hass, aioclient_mock) -> None:
    """A non-auth refusal stays retryable rather than triggering reauth."""
    aioclient_mock.get(
        API_URL,
        json={
            "result": {
                "success": 0,
                "message": "No thermostats found matching selection criteria.",
            }
        },
    )

    with pytest.raises(PelicanApiError) as err:
        await _api(hass).async_get_thermostats()
    assert not isinstance(err.value, PelicanAuthError)


async def test_non_json_response_raises(hass, aioclient_mock) -> None:
    """A login page instead of JSON is reported as a site problem, not a crash."""
    aioclient_mock.get(API_URL, text="<html><body>Sign in</body></html>")

    with pytest.raises(PelicanResponseError, match="non-JSON"):
        await _api(hass).async_get_thermostats()


async def test_non_object_payload_raises(hass, aioclient_mock) -> None:
    """Valid JSON of the wrong shape is called out as an API change."""
    aioclient_mock.get(API_URL, text="[1, 2, 3]")

    with pytest.raises(PelicanResponseError, match="list"):
        await _api(hass).async_get_thermostats()


async def test_missing_result_envelope_raises(hass, aioclient_mock) -> None:
    """The live API nests everything under "result"; the docs show it flat.

    Reading the flat shape was the single defect that would have made every
    call fail, so the absence of the envelope is an explicit error rather than
    a silent empty read.
    """
    aioclient_mock.get(API_URL, json={"Thermostat": [], "success": 1})

    with pytest.raises(PelicanResponseError, match="result"):
        await _api(hass).async_get_thermostats()


@pytest.mark.parametrize("node_name", ["", "bad;node", "bad:node"])
async def test_unusable_node_name_is_refused_before_any_request(
    hass, aioclient_mock, node_name
) -> None:
    """A selector the site cannot parse changes EVERY thermostat.

    Verified against a live site: a malformed selector on a set returned
    "Updated 7 thermostats" with success. So nothing leaves the process.
    """
    with pytest.raises(PelicanApiError, match="every thermostat"):
        await _api(hass).async_set_thermostat(node_name, {"system": "Off"})

    assert aioclient_mock.call_count == 0


async def test_wrong_password_is_an_auth_error(hass, aioclient_mock) -> None:
    """The exact response a live site gives for a wrong password.

    HTTP 403 with a JSON body. It must become reauth, not a retry loop that
    hammers the site with credentials that can never work.
    """
    aioclient_mock.get(
        API_URL,
        status=403,
        json={
            "result": {"success": 0, "message": "Invalid Authentication Credentials"}
        },
    )

    with pytest.raises(PelicanAuthError, match="403"):
        await _api(hass).async_get_thermostats()


async def test_auth_message_alone_is_an_auth_error(hass, aioclient_mock) -> None:
    """If the site ever sends the same message with HTTP 200, still reauth."""
    aioclient_mock.get(
        API_URL,
        json={
            "result": {"success": 0, "message": "Invalid Authentication Credentials"}
        },
    )

    with pytest.raises(PelicanAuthError):
        await _api(hass).async_get_thermostats()


async def test_http_500_is_a_response_error(hass, aioclient_mock) -> None:
    """A server error is reported as a response problem, not bad credentials."""
    aioclient_mock.get(API_URL, status=500, text="boom")

    with pytest.raises(PelicanResponseError, match="500"):
        await _api(hass).async_get_thermostats()


async def test_connection_failure_is_distinct(hass, aioclient_mock) -> None:
    """An unreachable host is a connection error, distinguishable from the rest.

    A bare aiohttp.ClientConnectionError is used rather than the more specific
    ClientConnectorError: the latter's constructor takes an internal
    ConnectionKey whose shape changes between aiohttp releases, so building one
    in a test couples the suite to aiohttp internals for no added coverage. Both
    reach the same handler and produce PelicanConnectionError; only the message
    text differs.
    """
    aioclient_mock.get(API_URL, exc=aiohttp.ClientConnectionError("no route to host"))

    with pytest.raises(PelicanConnectionError) as err:
        await _api(hass).async_get_thermostats()
    assert not isinstance(err.value, PelicanAuthError)


async def test_timeout_is_distinct(hass, aioclient_mock) -> None:
    """A hung site is a timeout, not a generic network error."""
    aioclient_mock.get(API_URL, exc=TimeoutError())

    with pytest.raises(PelicanTimeoutError):
        await _api(hass).async_get_thermostats()


async def test_set_builds_semicolon_delimited_pairs(hass, aioclient_mock) -> None:
    """Set requests select by nodeName and send colon-delimited pairs."""
    aioclient_mock.get(API_URL, json={"result": {"success": 1, "message": "Updated 1"}})

    await _api(hass).async_set_thermostat(
        "thrm2A38", {"system": "Cool", "coolSetting": 72}
    )

    query = _query(aioclient_mock)
    assert query["request"] == "set"
    assert query["selection"] == "nodeName:thrm2A38;"
    assert query["value"] == "system:Cool;coolSetting:72"


async def test_set_with_no_values_makes_no_request(hass, aioclient_mock) -> None:
    """An empty change is a no-op, not an empty write."""
    await _api(hass).async_set_thermostat("thrm2A38", {})

    assert aioclient_mock.call_count == 0


async def test_no_credential_reaches_the_log(hass, aioclient_mock, caplog) -> None:
    """Rule 11: the request URL carries credentials and must never be logged."""
    aioclient_mock.get(API_URL, json={"result": {"Thermostat": [], "success": 1}})
    api = PelicanApi(async_get_clientsession(hass), HOST, "user@example.com", "sekrit")

    with caplog.at_level(logging.DEBUG, logger="custom_components.pelican.api"):
        await api.async_get_thermostats()

    assert "sekrit" not in caplog.text
    assert "user@example.com" not in caplog.text
    # The request was still described, just without the credential-bearing URL.
    assert "Requesting get Thermostat" in caplog.text
