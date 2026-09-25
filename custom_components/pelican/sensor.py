"""Sensors for Pelican thermostats."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CONCENTRATION_PARTS_PER_MILLION, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PelicanConfigEntry
from .coordinator import PelicanData
from .entity import PelicanEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class PelicanSensorDescription(SensorEntityDescription):
    """Describes a Pelican sensor and how to read it off the payload."""

    value_fn: Callable[[PelicanEntity], str | float | None]
    exists_fn: Callable[[PelicanEntity], bool] = lambda entity: True


SENSORS: tuple[PelicanSensorDescription, ...] = (
    PelicanSensorDescription(
        key="status_display",
        translation_key="status_display",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda entity: entity.attr("statusDisplay"),
    ),
    PelicanSensorDescription(
        key="run_status",
        translation_key="run_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda entity: entity.attr("runStatus"),
    ),
    PelicanSensorDescription(
        key="set_by",
        translation_key="set_by",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda entity: entity.attr("setBy"),
    ),
    PelicanSensorDescription(
        key="co2",
        device_class=SensorDeviceClass.CO2,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        value_fn=lambda entity: entity.attr_int("co2Level"),
        # No CO2 sensor means no entity. Verified: TS200 units report co2Level
        # as "" (which attr_int reads as None). Kept for CO2-capable models,
        # which Pelican documents but no live site here has confirmed.
        exists_fn=lambda entity: bool(entity.attr_int("co2Level")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PelicanConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors for every thermostat."""
    data = entry.runtime_data
    entities: list[PelicanSensor] = []
    for serial in data.thermostats.data or {}:
        for description in SENSORS:
            sensor = PelicanSensor(data, serial, description)
            if description.exists_fn(sensor):
                entities.append(sensor)
    async_add_entities(entities)


class PelicanSensor(PelicanEntity, SensorEntity):
    """A single read-only value off a Pelican thermostat."""

    entity_description: PelicanSensorDescription

    def __init__(
        self,
        data: PelicanData,
        serial: str,
        description: PelicanSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(data, serial)
        self.entity_description = description
        self._attr_unique_id = f"{serial}_{description.key}"

    @property
    def native_value(self) -> str | float | None:
        """Return the current value."""
        return self.entity_description.value_fn(self)
