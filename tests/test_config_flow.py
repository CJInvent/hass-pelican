"""Tests for the Pelican config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.pelican.const import DOMAIN
from custom_components.pelican.errors import PelicanAuthError, PelicanError

from .conftest import HOST

USER_INPUT = {
    "host": f"https://{HOST}/",
    "username": "ha@example.com",
    "password": "hunter2",
}


async def test_user_flow_creates_entry(hass, mock_api) -> None:
    """A valid site and credentials produce an entry with a normalized host."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == HOST
    # The pasted URL is stored as a bare hostname.
    assert result["data"]["host"] == HOST
    assert result["result"].unique_id == HOST


@pytest.mark.parametrize(
    ("side_effect", "expected"),
    [
        (PelicanAuthError("Invalid username or password."), "invalid_auth"),
        (PelicanError("Timeout talking to site"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors(hass, mock_api, side_effect, expected) -> None:
    """Each failure class maps to its own message and lets the user retry."""
    mock_api.async_validate = AsyncMock(side_effect=side_effect)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}

    # Recovering from the error must still be possible in the same flow.
    mock_api.async_validate = AsyncMock(return_value=[{"serialNo": "41111"}])
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_site_with_no_thermostats_is_rejected(hass, mock_api) -> None:
    """Valid credentials but an empty site is a setup error, not a silent entry."""
    mock_api.async_validate = AsyncMock(return_value=[])

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["errors"] == {"base": "no_thermostats"}


async def test_duplicate_site_aborts(hass, mock_api, config_entry) -> None:
    """The same site cannot be added twice, however the host was typed."""
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_credentials(hass, mock_api, config_entry) -> None:
    """Reauth replaces the stored credentials without recreating the entry."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"username": "ha2@example.com", "password": "new-password"},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["username"] == "ha2@example.com"
    assert config_entry.data["host"] == HOST
