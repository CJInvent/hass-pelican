"""Thin async client for the Pelican Wireless OpenAPI (api.cgi)."""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30

# Reserved Thermostat attributes we pull on every poll. Keep this list tight:
# every attribute here is used by an entity somewhere in the integration.
THERMOSTAT_ATTRIBUTES = (
    "name",
    "serialNo",
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

_AUTH_HINTS = (
    "password",
    "username",
    "login",
    "authenticat",
    "not authorized",
    "access denied",
)


class PelicanError(Exception):
    """Any failure talking to the Pelican site."""


class PelicanAuthError(PelicanError):
    """Credentials were rejected by the Pelican site."""


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
        """Issue one api.cgi call and return the decoded payload."""
        query = {
            "username": self._username,
            "password": self._password,
            **params,
        }
        try:
            async with self._session.get(
                self.url,
                params=query,
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                response.raise_for_status()
                text = await response.text()
        except TimeoutError as err:
            raise PelicanError(f"Timeout talking to {self._host}") from err
        except aiohttp.ClientError as err:
            raise PelicanError(f"Error talking to {self._host}: {err}") from err

        try:
            data = json.loads(text)
        except ValueError as err:
            # A login page instead of JSON usually means the credentials or the
            # site name are wrong.
            raise PelicanError(
                f"{self._host} returned a non-JSON response; check the site name"
            ) from err

        if not isinstance(data, dict):
            raise PelicanError(f"Unexpected response from {self._host}")

        if str(data.get("success")) != "1":
            message = str(data.get("message") or "Request rejected by the Pelican site")
            if any(hint in message.lower() for hint in _AUTH_HINTS):
                raise PelicanAuthError(message)
            raise PelicanError(message)

        return data

    async def async_get_thermostats(self) -> list[dict[str, Any]]:
        """Return every thermostat at the site with the attributes we care about."""
        data = await self._request(
            {
                "request": "get",
                "object": "Thermostat",
                "value": ";".join(THERMOSTAT_ATTRIBUTES),
            }
        )
        raw = data.get("Thermostat") or []
        # A single match comes back as an object, several as a list.
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            raise PelicanError("Unexpected Thermostat payload shape")
        return [item for item in raw if isinstance(item, dict)]

    async def async_set_thermostat(self, serial: str, values: dict[str, Any]) -> None:
        """Apply attribute/value pairs to one thermostat, selected by serial number."""
        if not values:
            return
        value = ";".join(f"{key}:{val}" for key, val in values.items())
        _LOGGER.debug("Setting %s on thermostat %s", value, serial)
        await self._request(
            {
                "request": "set",
                "object": "Thermostat",
                "selection": f"serialNo:{serial};",
                "value": value,
            }
        )

    async def async_validate(self) -> list[dict[str, Any]]:
        """Confirm credentials work and return the discovered thermostats."""
        return await self.async_get_thermostats()
