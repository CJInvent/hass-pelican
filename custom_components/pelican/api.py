"""Thin async client for the Pelican Wireless OpenAPI (api.cgi)."""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from .errors import (
    PelicanApiError,
    PelicanAuthError,
    PelicanConnectionError,
    PelicanResponseError,
    PelicanTimeoutError,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30

# Reserved Thermostat attributes we pull on every poll. Keep this list tight:
# every attribute here is used by an entity somewhere in the integration, and
# scripts/check-consistency.py fails the build if that stops being true.
THERMOSTAT_ATTRIBUTES = (
    "name",
    "serialNo",
    "nodeName",
    "modelNo",
    "version",
    "system",
    "heatSetting",
    "coolSetting",
    "fan",
    "temperature",
    "humidity",
    "co2Level",
    "runStatus",
    "statusDisplay",
    "setBy",
    "schedule",
    "frontKeypad",
    "temperatureFormat",
    "minHeatSetting",
    "maxHeatSetting",
    "minCoolSetting",
    "maxCoolSetting",
)

# Substrings that mark a site refusal as an authentication problem rather than
# a transient one. Matched case-insensitively against the site's own message.
# Observed live for a wrong password: HTTP 403 with "Invalid Authentication
# Credentials" -- caught by the status check and by "authenticat" alike. The
# other hints are unobserved and kept as a net for wording we have not seen.
_AUTH_HINTS = (
    "password",
    "username",
    "login",
    "authenticat",
    "not authorized",
    "access denied",
    "permission",
)


def normalize_host(host: str) -> str:
    """Accept a bare hostname, a full URL, or something with a trailing slash."""
    host = host.strip()
    if "://" in host:
        host = host.split("://", 1)[1]
    return host.strip("/").split("/", 1)[0]


class PelicanApi:
    """Talks to https://<site>.officeclimatecontrol.net/api.cgi."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
    ) -> None:
        """Store connection details. No I/O happens here."""
        self._session = session
        self._host = normalize_host(host)
        self._username = username
        self._password = password

    @property
    def host(self) -> str:
        """Return the normalized site hostname."""
        return self._host

    @property
    def url(self) -> str:
        """Return the full API endpoint URL."""
        return f"https://{self._host}/api.cgi"

    async def _request(self, params: dict[str, str]) -> dict[str, Any]:
        """Issue one api.cgi call and return the decoded payload.

        Raises a specific PelicanError subclass for every failure mode so the
        caller can decide between reauth, retry and abort, and so the log line
        names the actual problem.
        """
        query = {
            "username": self._username,
            "password": self._password,
            **params,
        }
        # Credentials travel in the query string, so the URL is a credential and
        # is never logged (rule 11). The request shape is logged instead.
        _LOGGER.debug(
            "Requesting %s %s from %s",
            params.get("request"),
            params.get("object"),
            self._host,
        )

        try:
            async with self._session.get(
                self.url,
                params=query,
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                status = response.status
                text = await response.text()
        except TimeoutError as err:
            raise PelicanTimeoutError(
                f"{self._host} did not respond within {REQUEST_TIMEOUT}s"
            ) from err
        except aiohttp.ClientSSLError as err:
            raise PelicanConnectionError(
                f"TLS error connecting to {self._host}: {err}"
            ) from err
        except aiohttp.ClientConnectorError as err:
            raise PelicanConnectionError(
                f"Cannot reach {self._host}: {err}. Check the site hostname, "
                "DNS, and outbound internet access from Home Assistant"
            ) from err
        except aiohttp.ClientError as err:
            raise PelicanConnectionError(
                f"Network error talking to {self._host}: {err}"
            ) from err

        if status in (401, 403):
            raise PelicanAuthError(
                f"{self._host} rejected the credentials (HTTP {status}). "
                "Check the API user still exists and has thermostat access"
            )
        if status >= 400:
            raise PelicanResponseError(
                f"{self._host} returned HTTP {status} for a "
                f"{params.get('request')} {params.get('object')} request"
            )

        try:
            data = json.loads(text)
        except ValueError as err:
            # Every api.cgi response observed so far, errors included, has been
            # JSON. A non-JSON body therefore means we are not talking to
            # api.cgi at all: most likely a wrong hostname or an intermediary
            # (captive portal, proxy error page) in the path.
            raise PelicanResponseError(
                f"{self._host} returned a non-JSON response to a "
                f"{params.get('request')} {params.get('object')} request; "
                "verify the site hostname and that the OpenAPI is enabled "
                "for this account"
            ) from err

        if not isinstance(data, dict):
            raise PelicanResponseError(
                f"{self._host} returned {type(data).__name__} where an object "
                "was expected; the API may have changed"
            )

        # Everything the site returns is nested under "result". The published
        # examples show it flattened; the live API does not.
        payload = data.get("result")
        if not isinstance(payload, dict):
            raise PelicanResponseError(
                f"{self._host} returned a response with no 'result' object; "
                "the API may have changed"
            )

        # success comes back as the integer 1, not the string the docs show.
        if str(payload.get("success")) != "1":
            message = str(payload.get("message") or "").strip()
            detail = message or "the site gave no reason"
            if any(hint in message.lower() for hint in _AUTH_HINTS):
                raise PelicanAuthError(f"{self._host} rejected the request: {detail}")
            raise PelicanApiError(f"{self._host} refused the request: {detail}")

        return payload

    def _collect(self, data: dict[str, Any], key: str) -> list[dict[str, Any]]:
        """Normalize a payload that is an object for one row and a list for many."""
        raw = data.get(key) or []
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            raise PelicanResponseError(
                f"{self._host} returned an unexpected {key} payload shape"
            )
        return [item for item in raw if isinstance(item, dict)]

    async def async_get_thermostats(self) -> list[dict[str, Any]]:
        """Return every thermostat at the site with the attributes we care about."""
        data = await self._request(
            {
                "request": "get",
                "object": "Thermostat",
                "value": ";".join(THERMOSTAT_ATTRIBUTES),
            }
        )
        return self._collect(data, "Thermostat")

    async def async_set_thermostat(
        self, node_name: str, values: dict[str, Any]
    ) -> None:
        """Apply attribute/value pairs to the thermostat with this node name.

        Selection is by `nodeName` (e.g. "thrm2A38"). The site rejects
        `serialNo:` selection outright, and selecting by `name:` works but
        means putting free text a customer edits into a selector: names carry
        trailing spaces that are significant ("Sales " is not "Sales"),
        ampersands, and no uniqueness guarantee. nodeName has none of those
        problems.

        The guard below is not defensive programming, it is a verified hazard.
        The site does not reject a selection it cannot parse -- it ignores it,
        matches EVERY thermostat, and reports success. Confirmed against a live
        site: a malformed selector on a set returned "Updated 7 thermostats."
        One bad selector re-heats an entire building and nothing looks wrong.
        """
        if not values:
            return
        if not node_name or any(char in node_name for char in ";:"):
            raise PelicanApiError(
                f"Refusing to write with unusable node name {node_name!r}: the "
                "site treats a selector it cannot parse as every thermostat"
            )
        value = ";".join(f"{key}:{val}" for key, val in values.items())
        _LOGGER.debug("Setting %s on thermostat %s", value, node_name)
        await self._request(
            {
                "request": "set",
                "object": "Thermostat",
                "selection": f"nodeName:{node_name};",
                "value": value,
            }
        )

    async def async_validate(self) -> list[dict[str, Any]]:
        """Confirm credentials work and return the discovered thermostats."""
        return await self.async_get_thermostats()
