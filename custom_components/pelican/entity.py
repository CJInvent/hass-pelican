"""Base entity shared by every Pelican platform."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN, MANUFACTURER, STATUS_UNREACHABLE
from .coordinator import PelicanData


class PelicanEntity(CoordinatorEntity[DataUpdateCoordinator[Any]]):
    """One entity attached to one Pelican thermostat.

    Identity and availability always come from the thermostat coordinator.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        data: PelicanData,
        serial: str,
        coordinator: DataUpdateCoordinator[Any] | None = None,
    ) -> None:
        """Initialize the entity for a given thermostat serial number."""
        super().__init__(coordinator or data.thermostats)
        self.data = data
        self._serial = serial

    @property
    def serial(self) -> str:
        """Return the thermostat serial number this entity belongs to."""
        return self._serial

    @property
    def thermostat(self) -> dict[str, Any]:
        """Return this thermostat's latest payload."""
        return (self.data.thermostats.data or {}).get(self._serial, {})

    def attr(self, key: str) -> str | None:
        """Return a raw attribute as a string, or None when absent/blank."""
        value = self.thermostat.get(key)
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    def attr_int(self, key: str) -> int | None:
        """Return an attribute coerced to int, or None when it isn't numeric."""
        value = self.attr(key)
        if value is None:
            return None
        try:
            return round(float(value))
        except ValueError:
            return None

    def attr_float(self, key: str) -> float | None:
        """Return an attribute coerced to float, or None when it isn't numeric."""
        value = self.attr(key)
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    @property
    def available(self) -> bool:
        """Mark entities unavailable when the site drops the thermostat."""
        return (
            self.data.thermostats.last_update_success
            and self._serial in (self.data.thermostats.data or {})
            and self.attr("statusDisplay") != STATUS_UNREACHABLE
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device this entity belongs to."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=self.attr("name") or self._serial,
            manufacturer=MANUFACTURER,
            model=self.attr("modelNo"),
            sw_version=self.attr("version"),
            serial_number=self._serial,
            configuration_url=f"https://{self.data.api.host}/",
        )
