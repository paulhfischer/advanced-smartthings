from __future__ import annotations

from custom_components.advanced_smartthings.discovery import (
    build_device_catalog,
    build_device_options,
    parse_devices,
)

from .conftest import (
    COOKTOP_DEVICE,
    FRIDGE_DEVICE,
    OVEN_DEVICE,
    OVEN_SETPOINT_DEFINITION,
    SAMSUNG_OVEN_MODE_DEFINITION,
    THERMOSTAT_COOLING_SETPOINT_DEFINITION,
    UNSUPPORTED_DEVICE,
)


def test_build_device_options_filters_unsupported_devices() -> None:
    devices = parse_devices([OVEN_DEVICE, FRIDGE_DEVICE, COOKTOP_DEVICE, UNSUPPORTED_DEVICE])
    catalog = build_device_catalog(
        devices,
        capability_definitions={
            ("samsungce.ovenMode", 1): SAMSUNG_OVEN_MODE_DEFINITION,
            ("ovenSetpoint", 1): OVEN_SETPOINT_DEFINITION,
            ("thermostatCoolingSetpoint", 1): THERMOSTAT_COOLING_SETPOINT_DEFINITION,
        },
    )

    options = build_device_options(catalog)

    assert "device-unsupported-1" not in options
    assert "device-oven-1" in options
    assert "device-fridge-1" in options
    assert "device-cooktop-1" in options
