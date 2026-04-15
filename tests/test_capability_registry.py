from __future__ import annotations

from custom_components.advanced_smartthings.capability_registry import (
    AdvancedSmartThingsBinarySensorEntityDescription,
    AdvancedSmartThingsNumberEntityDescription,
    AdvancedSmartThingsSelectEntityDescription,
    AdvancedSmartThingsSensorEntityDescription,
    AdvancedSmartThingsSwitchEntityDescription,
    build_entity_descriptions,
)
from custom_components.advanced_smartthings.discovery import parse_devices

from .conftest import (
    COOKTOP_DEVICE,
    FRIDGE_DEVICE,
    OVEN_DEVICE,
    OVEN_SETPOINT_DEFINITION,
    SAMSUNG_OVEN_MODE_DEFINITION,
    THERMOSTAT_COOLING_SETPOINT_DEFINITION,
)


def test_build_entity_descriptions_for_supported_v1_appliances() -> None:
    devices = parse_devices([OVEN_DEVICE, FRIDGE_DEVICE, COOKTOP_DEVICE])
    definitions = {
        ("samsungce.ovenMode", 1): SAMSUNG_OVEN_MODE_DEFINITION,
        ("ovenSetpoint", 1): OVEN_SETPOINT_DEFINITION,
        ("thermostatCoolingSetpoint", 1): THERMOSTAT_COOLING_SETPOINT_DEFINITION,
    }

    oven_descriptions = build_entity_descriptions(devices[0], definitions)
    fridge_descriptions = build_entity_descriptions(devices[1], definitions)
    cooktop_descriptions = build_entity_descriptions(devices[2], definitions)

    assert any(
        isinstance(description, AdvancedSmartThingsSelectEntityDescription)
        for description in oven_descriptions
    )
    assert any(
        isinstance(description, AdvancedSmartThingsNumberEntityDescription)
        and description.translation_key == "oven_timer"
        for description in oven_descriptions
    )
    assert any(
        isinstance(description, AdvancedSmartThingsSwitchEntityDescription)
        for description in oven_descriptions
    )
    assert any(
        isinstance(description, AdvancedSmartThingsBinarySensorEntityDescription)
        and description.translation_key == "oven_remote_control"
        for description in oven_descriptions
    )

    assert (
        sum(
            isinstance(description, AdvancedSmartThingsBinarySensorEntityDescription)
            for description in fridge_descriptions
        )
        == 2
    )
    assert (
        sum(
            isinstance(description, AdvancedSmartThingsNumberEntityDescription)
            for description in fridge_descriptions
        )
        == 2
    )
    assert (
        sum(
            isinstance(description, AdvancedSmartThingsSensorEntityDescription)
            for description in fridge_descriptions
        )
        == 2
    )

    assert len(cooktop_descriptions) == 1
    assert isinstance(cooktop_descriptions[0], AdvancedSmartThingsBinarySensorEntityDescription)
