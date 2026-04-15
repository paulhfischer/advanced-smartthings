from __future__ import annotations

from custom_components.advanced_smartthings.capability_registry import (
    AdvancedSmartThingsBinarySensorEntityDescription,
    AdvancedSmartThingsNumberEntityDescription,
    AdvancedSmartThingsSelectEntityDescription,
    AdvancedSmartThingsSensorEntityDescription,
    AdvancedSmartThingsSwitchEntityDescription,
    build_entity_descriptions,
    denormalize_oven_mode,
    normalize_oven_mode,
    resolve_standard_oven_start_mode,
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
        isinstance(description, AdvancedSmartThingsNumberEntityDescription)
        and description.translation_key == "oven_temperature"
        for description in oven_descriptions
    )
    assert any(
        isinstance(description, AdvancedSmartThingsSensorEntityDescription)
        and description.translation_key == "oven_current_temperature"
        for description in oven_descriptions
    )
    assert any(
        isinstance(description, AdvancedSmartThingsSensorEntityDescription)
        and description.translation_key == "oven_program"
        for description in oven_descriptions
    )
    assert any(
        isinstance(description, AdvancedSmartThingsSensorEntityDescription)
        and description.translation_key == "oven_timer_status"
        for description in oven_descriptions
    )
    assert any(
        isinstance(description, AdvancedSmartThingsSensorEntityDescription)
        and description.translation_key == "oven_target_temperature"
        for description in oven_descriptions
    )
    assert any(
        isinstance(description, AdvancedSmartThingsSwitchEntityDescription)
        and description.translation_key == "oven_power"
        for description in oven_descriptions
    )
    assert any(
        isinstance(description, AdvancedSmartThingsSwitchEntityDescription)
        and description.translation_key == "oven_lamp"
        for description in oven_descriptions
    )
    assert any(
        isinstance(description, AdvancedSmartThingsBinarySensorEntityDescription)
        and description.translation_key == "oven_remote_control"
        for description in oven_descriptions
    )
    assert any(
        isinstance(description, AdvancedSmartThingsBinarySensorEntityDescription)
        and description.translation_key == "oven_running"
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


def test_oven_mode_labels_support_english_and_german() -> None:
    assert normalize_oven_mode("NoOperation", "en") == "Off"
    assert normalize_oven_mode("NoOperation", "de") == "Aus"
    assert normalize_oven_mode("Convection", "en") == "Bake"
    assert normalize_oven_mode("Convection", "de") == "Heißluft"
    assert normalize_oven_mode("ConvectionBake", "de") == "Heißluft"
    assert normalize_oven_mode("warming", "en") == "Keep Warm"
    assert normalize_oven_mode("warming", "de") == "Warmhalten"
    assert normalize_oven_mode("KeepWarm", "de") == "Warmhalten"
    assert normalize_oven_mode("BottomConvection", "de") == "Unterhitze + Umluft"
    assert normalize_oven_mode("SteamCook", "de") == "Dampfgaren"
    assert normalize_oven_mode("AirFry", "de") == "Heißluftfrittieren"
    assert normalize_oven_mode("PowerConvectionCombi", "en") == "Power Convection Combi"

    assert (
        denormalize_oven_mode(
            "Heißluft",
            language="de",
            raw_options=["Convection", "Conventional"],
        )
        == "Convection"
    )
    assert (
        denormalize_oven_mode(
            "Warmhalten",
            language="de",
            raw_options=["KeepWarm", "warming"],
        )
        == "KeepWarm"
    )


def test_standard_oven_start_mode_mapping_is_deterministic() -> None:
    assert (
        resolve_standard_oven_start_mode(
            "Convection",
            ["Others", "ConvectionBake", "Conventional"],
        )
        == "ConvectionBake"
    )
    assert (
        resolve_standard_oven_start_mode(
            "KeepWarm",
            ["warming", "ConvectionBake"],
        )
        == "warming"
    )
    assert (
        resolve_standard_oven_start_mode(
            "warming",
            ["warming", "ConvectionBake"],
        )
        == "warming"
    )
    assert resolve_standard_oven_start_mode("AirFry", ["Bake", "Conventional"]) is None
