"""Config and options flow for the Pelican Wireless integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .api import PelicanApi, normalize_host
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MAX_SCAN_INTERVAL, MIN_SCAN_INTERVAL
from .errors import (
    PelicanApiError,
    PelicanAuthError,
    PelicanConnectionError,
    PelicanError,
    PelicanResponseError,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    }
)


async def _validate(hass, host: str, username: str, password: str) -> int:
    """Confirm the credentials work and return how many thermostats were found."""
    api = PelicanApi(async_get_clientsession(hass), host, username, password)
    thermostats = await api.async_validate()
    return len(thermostats)


async def _try_validate(
    hass, host: str, username: str, password: str
) -> tuple[int | None, str | None]:
    """Validate, returning the thermostat count or a form error key.

    Every failure is logged as well as shown, because the form only has room for
    one sentence and the log is where the actual site message lives.
    """
    try:
        found = await _validate(hass, host, username, password)
    except PelicanAuthError as err:
        _LOGGER.error("Pelican site %s rejected the credentials: %s", host, err)
        return None, "invalid_auth"
    except PelicanConnectionError as err:
        _LOGGER.error("Cannot reach Pelican site %s: %s", host, err)
        return None, "cannot_connect"
    except PelicanResponseError as err:
        _LOGGER.error("Unexpected response from Pelican site %s: %s", host, err)
        return None, "bad_response"
    except PelicanApiError as err:
        _LOGGER.error("Pelican site %s refused the request: %s", host, err)
        return None, "api_error"
    except PelicanError as err:
        _LOGGER.error("Pelican site %s failed validation: %s", host, err)
        return None, "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error validating Pelican site %s", host)
        return None, "unknown"

    if not found:
        _LOGGER.error(
            "Pelican site %s accepted the credentials but reported no "
            "thermostats for that user",
            host,
        )
        return None, "no_thermostats"

    _LOGGER.debug("Pelican site %s validated with %s thermostat(s)", host, found)
    return found, None


class PelicanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle adding a Pelican site."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the site hostname and API credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = normalize_host(user_input[CONF_HOST])
            await self.async_set_unique_id(host.lower())
            self._abort_if_unique_id_configured()

            _found, error = await _try_validate(
                self.hass,
                host,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=host,
                    data={
                        CONF_HOST: host,
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauth when the site starts rejecting the stored credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect fresh credentials for an existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            _found, error = await _try_validate(
                self.hass,
                entry.data[CONF_HOST],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): cv.string,
                    vol.Required(CONF_PASSWORD): cv.string,
                }
            ),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PelicanOptionsFlow:
        """Return the options flow."""
        return PelicanOptionsFlow()


class PelicanOptionsFlow(OptionsFlow):
    """Let the poll interval be tuned after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the poll interval."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    )
                }
            ),
        )
