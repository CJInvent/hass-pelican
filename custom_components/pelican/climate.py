"""Climate platform for Pelican thermostats."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    FAN_AUTO,
    FAN_ON,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_TENTHS, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PelicanConfigEntry
from .const import DOMAIN
from .coordinator import PelicanData
from .entity import PelicanEntity
from .errors import PelicanError
from .repairs import thermostat_has_cloud_schedule

PELICAN_TO_HVAC_MODE = {
    "Off": HVACMode.OFF,
    "Heat": HVACMode.HEAT,
    "Cool": HVACMode.COOL,
    "Auto": HVACMode.HEAT_COOL,
}
HVAC_MODE_TO_PELICAN = {value: key for key, value in PELICAN_TO_HVAC_MODE.items()}

PELICAN_TO_FAN_MODE = {"Auto": FAN_AUTO, "On": FAN_ON}
FAN_MODE_TO_PELICAN = {value: key for key, value in PELICAN_TO_FAN_MODE.items()}

RUN_STATUS_TO_ACTION = {
    "Off": HVACAction.IDLE,
    "Cool-Stage1": HVACAction.COOLING,
    "Cool-Stage2": HVACAction.COOLING,
    "Heat-Stage1": HVACAction.HEATING,
    "Heat-Stage2": HVACAction.HEATING,
    "Fan": HVACAction.FAN,
    "Fan2": HVACAction.FAN,
}

DEFAULT_MIN_TEMP = 40
DEFAULT_MAX_TEMP = 95

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PelicanConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one climate entity per thermostat found at the site."""
    data = entry.runtime_data
    async_add_entities(
        PelicanClimate(data, serial) for serial in (data.thermostats.data or {})
    )


class PelicanClimate(PelicanEntity, ClimateEntity):
    """A Pelican TC/TS series thermostat."""

    _attr_name = None
    _attr_target_temperature_step = 1
    # Home Assistant defaults Fahrenheit entities to whole-degree precision,
    # which would round the 72.4 F the thermostat actually reports down to 72.
    # Pelican reports tenths and commercial sites care about them for trending,
    # so keep what the API gives us. Setpoints stay whole-degree via
    # target_temperature_step, because the API only accepts integers.
    _attr_precision = PRECISION_TENTHS
    _attr_fan_modes = [FAN_AUTO, FAN_ON]
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL]

    def __init__(self, data: PelicanData, serial: str) -> None:
        """Initialize the thermostat entity."""
        super().__init__(data, serial)
        self._attr_unique_id = serial

    @property
    def temperature_unit(self) -> str:
        """Return the unit the thermostat itself is configured to report in."""
        if self.attr("temperatureFormat") == "Celsius":
            return UnitOfTemperature.CELSIUS
        return UnitOfTemperature.FAHRENHEIT

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Advertise a single setpoint, or a range while in Auto."""
        features = (
            ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        if self.hvac_mode == HVACMode.HEAT_COOL:
            return features | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        return features | ClimateEntityFeature.TARGET_TEMPERATURE

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the thermostat's active system mode."""
        return PELICAN_TO_HVAC_MODE.get(self.attr("system") or "")

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return what the equipment is actually doing right now."""
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        return RUN_STATUS_TO_ACTION.get(self.attr("runStatus") or "")

    @property
    def fan_mode(self) -> str | None:
        """Return the active fan mode."""
        return PELICAN_TO_FAN_MODE.get(self.attr("fan") or "")

    @property
    def current_temperature(self) -> float | None:
        """Return the measured space temperature."""
        return self.attr_float("temperature")

    @property
    def current_humidity(self) -> int | None:
        """Return measured humidity, or None on thermostats without a sensor."""
        humidity = self.attr_int("humidity")
        if not humidity:
            return None
        return humidity

    @property
    def target_temperature(self) -> float | None:
        """Return the active setpoint for single-setpoint modes."""
        if self.hvac_mode == HVACMode.HEAT:
            return self.attr_int("heatSetting")
        if self.hvac_mode == HVACMode.COOL:
            return self.attr_int("coolSetting")
        return None

    @property
    def target_temperature_low(self) -> float | None:
        """Return the heat setpoint while in Auto."""
        if self.hvac_mode == HVACMode.HEAT_COOL:
            return self.attr_int("heatSetting")
        return None

    @property
    def target_temperature_high(self) -> float | None:
        """Return the cool setpoint while in Auto."""
        if self.hvac_mode == HVACMode.HEAT_COOL:
            return self.attr_int("coolSetting")
        return None

    @property
    def min_temp(self) -> float:
        """Return the lowest setpoint the site configuration allows."""
        if self.hvac_mode == HVACMode.COOL:
            return self.attr_int("minCoolSetting") or DEFAULT_MIN_TEMP
        return self.attr_int("minHeatSetting") or DEFAULT_MIN_TEMP

    @property
    def max_temp(self) -> float:
        """Return the highest setpoint the site configuration allows."""
        if self.hvac_mode == HVACMode.HEAT:
            return self.attr_int("maxHeatSetting") or DEFAULT_MAX_TEMP
        return self.attr_int("maxCoolSetting") or DEFAULT_MAX_TEMP

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Surface Pelican-specific context that has no HA equivalent."""
        return {
            "set_by": self.attr("setBy"),
            "status_display": self.attr("statusDisplay"),
            "schedule": self.attr("schedule"),
            "serial_number": self._serial,
            # Surfaced here as well as on the binary sensor because this is the
            # entity people put on a dashboard and automate against.
            "cloud_schedule_active": thermostat_has_cloud_schedule(
                self.thermostat,
                bool(
                    (schedules := self.data.schedules.data)
                    and schedules.for_serial(self._serial)
                ),
            ),
        }

    async def _apply(self, values: dict[str, Any]) -> None:
        """Send a set request, translating API failures into HA errors."""
        try:
            await self.data.thermostats.async_apply(self._serial, values)
        except PelicanError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={
                    "name": str(self.name or self._serial),
                    "error": str(err),
                },
            ) from err

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Change the system mode."""
        await self._apply({"system": HVAC_MODE_TO_PELICAN[hvac_mode]})

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Change the fan mode."""
        await self._apply({"fan": FAN_MODE_TO_PELICAN[fan_mode]})

    async def async_turn_off(self) -> None:
        """Turn the system off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_turn_on(self) -> None:
        """Return the system to Auto."""
        await self.async_set_hvac_mode(HVACMode.HEAT_COOL)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set one or both setpoints, optionally changing mode at the same time."""
        values: dict[str, Any] = {}

        mode: HVACMode | None = kwargs.get("hvac_mode")
        if mode is not None:
            values["system"] = HVAC_MODE_TO_PELICAN[mode]

        target_mode = mode or self.hvac_mode

        low = kwargs.get(ATTR_TARGET_TEMP_LOW)
        high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        if low is not None:
            values["heatSetting"] = round(low)
        if high is not None:
            values["coolSetting"] = round(high)

        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is not None:
            if target_mode == HVACMode.HEAT:
                values["heatSetting"] = round(temperature)
            elif target_mode == HVACMode.COOL:
                values["coolSetting"] = round(temperature)
            else:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="single_setpoint_in_auto",
                    translation_placeholders={
                        "name": str(self.name or self._serial),
                        "mode": str(target_mode),
                    },
                )

        if not values:
            return

        await self._apply(values)
