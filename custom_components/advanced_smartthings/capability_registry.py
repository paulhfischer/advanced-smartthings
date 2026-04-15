from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)
from homeassistant.components.button import ButtonEntityDescription
from homeassistant.components.number import NumberDeviceClass, NumberEntityDescription, NumberMode
from homeassistant.components.select import SelectEntityDescription
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature, UnitOfTime

from .models import CapabilityRef, DeviceRecord

AttributePath = tuple[str, ...]
TruthValue = bool | None
NumberRange = tuple[float, float, float, bool]

OVEN_MODE_TRANSLATIONS: dict[str, dict[str, str]] = {
    "NoOperation": {"en": "Off", "de": "Aus"},
    "Convection": {"en": "Convection", "de": "Umluft"},
    "Conventional": {"en": "Conventional", "de": "Ober-/Unterhitze"},
    "Bake": {"en": "Bake", "de": "Backen"},
    "Bottom": {"en": "Bottom Heat", "de": "Unterhitze"},
    "BottomHeat": {"en": "Bottom Heat", "de": "Unterhitze"},
    "BottomConvection": {"en": "Bottom Convection", "de": "Unterhitze + Umluft"},
    "TopConvection": {"en": "Top Convection", "de": "Oberhitze + Umluft"},
    "Broil": {"en": "Broil", "de": "Grill"},
    "LargeGrill": {"en": "Large Grill", "de": "Großer Grill"},
    "SmallGrill": {"en": "Small Grill", "de": "Kleiner Grill"},
    "EcoGrill": {"en": "Eco Grill", "de": "Eco-Grill"},
    "Defrost": {"en": "Defrost", "de": "Auftauen"},
    "defrosting": {"en": "Defrost", "de": "Auftauen"},
    "KeepWarm": {"en": "Keep Warm", "de": "Warmhalten"},
    "WarmHold": {"en": "Warm Hold", "de": "Warmhalten"},
    "warming": {"en": "Keep Warm", "de": "Warmhalten"},
    "Proof": {"en": "Proof", "de": "Gärstufe"},
    "BreadProof": {"en": "Bread Proof", "de": "Teig gehen lassen"},
    "ProveDough": {"en": "Prove Dough", "de": "Teig gehen lassen"},
    "SteamCook": {"en": "Steam Cook", "de": "Dampfgaren"},
    "SteamBake": {"en": "Steam Bake", "de": "Dampfbacken"},
    "SteamRoast": {"en": "Steam Roast", "de": "Dampfbraten"},
    "SteamConvection": {"en": "Steam Convection", "de": "Dampfumluft"},
    "SteamBottomConvection": {
        "en": "Steam Bottom Convection",
        "de": "Unterhitze + Dampf + Umluft",
    },
    "SteamTopConvection": {"en": "Steam Top Convection", "de": "Oberhitze + Dampf + Umluft"},
    "Autocook": {"en": "Auto Cook", "de": "Automatikprogramm"},
    "Drain": {"en": "Drain", "de": "Entleeren"},
    "Descale": {"en": "Descale", "de": "Entkalken"},
    "Dehydrate": {"en": "Dehydrate", "de": "Dörren"},
    "Pizza": {"en": "Pizza", "de": "Pizza"},
    "Roast": {"en": "Roast", "de": "Braten"},
    "Roasting": {"en": "Roasting", "de": "Braten"},
    "AirFry": {"en": "Air Fry", "de": "Heißluftfrittieren"},
    "AirFryer": {"en": "Air Fry", "de": "Heißluftfrittieren"},
    "HotBlast": {"en": "Hot Blast", "de": "Heißluft"},
    "PureConvection": {"en": "Pure Convection", "de": "Reine Umluft"},
    "PowerConvection": {"en": "Power Convection", "de": "Power-Umluft"},
}

STANDARD_OVEN_START_MODE_MAP: dict[str, str] = {
    "Convection": "ConvectionBake",
    "Conventional": "Conventional",
    "Bake": "Bake",
    "BottomHeat": "BottomHeat",
    "Bottom": "BottomHeat",
    "Broil": "Broil",
    "SteamCook": "SteamCook",
    "SteamBake": "SteamBake",
    "SteamRoast": "SteamRoast",
    "Proof": "Proof",
    "BreadProof": "Proof",
    "ProveDough": "Proof",
    "Dehydrate": "Dehydrate",
    "KeepWarm": "warming",
    "WarmHold": "warming",
    "Defrost": "defrosting",
}


@dataclass(frozen=True, kw_only=True)
class AdvancedSmartThingsEntityMixin:
    device_id: str
    device_label: str
    component_id: str
    component_label: str | None
    capability: str
    requires_remote_control: bool = False


@dataclass(frozen=True, kw_only=True)
class AdvancedSmartThingsSensorEntityDescription(
    AdvancedSmartThingsEntityMixin,
    SensorEntityDescription,
):
    value_path: AttributePath
    unit_path: AttributePath = ()
    state_kind: Literal["numeric", "string"] = "string"


@dataclass(frozen=True, kw_only=True)
class AdvancedSmartThingsBinarySensorEntityDescription(
    AdvancedSmartThingsEntityMixin,
    BinarySensorEntityDescription,
):
    value_path: AttributePath
    on_values: tuple[str, ...] = field(default_factory=tuple)
    off_values: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, kw_only=True)
class AdvancedSmartThingsSwitchEntityDescription(
    AdvancedSmartThingsEntityMixin,
    SwitchEntityDescription,
):
    state_path: AttributePath
    on_command: str
    off_command: str
    on_arguments: tuple[Any, ...] = field(default_factory=tuple)
    off_arguments: tuple[Any, ...] = field(default_factory=tuple)
    supported_values_path: AttributePath = ()
    use_supported_non_off_value: bool = False


@dataclass(frozen=True, kw_only=True)
class AdvancedSmartThingsSelectEntityDescription(
    AdvancedSmartThingsEntityMixin,
    SelectEntityDescription,
):
    value_path: AttributePath
    command: str
    options_path: AttributePath = ()
    fallback_options: tuple[str, ...] = field(default_factory=tuple)
    option_map: tuple[tuple[str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True, kw_only=True)
class AdvancedSmartThingsButtonEntityDescription(
    AdvancedSmartThingsEntityMixin,
    ButtonEntityDescription,
):
    command: str
    arguments: tuple[Any, ...] = field(default_factory=tuple)
    press_strategy: Literal["command", "oven_start_program"] = "command"


@dataclass(frozen=True, kw_only=True)
class AdvancedSmartThingsNumberEntityDescription(
    AdvancedSmartThingsEntityMixin,
    NumberEntityDescription,
):
    value_path: AttributePath
    command: str
    unit_path: AttributePath = ()
    range_path: AttributePath = ()
    fallback_range: NumberRange | None = None
    value_kind: Literal["numeric", "duration_minutes"] = "numeric"
    range_strategy: Literal[
        "none",
        "status_range",
        "oven_temperature_spec",
        "oven_timer_spec",
    ] = "none"
    static_min_value: float | None = None
    static_max_value: float | None = None
    static_step: float | None = None
    cast_to_int: bool = False


AdvancedSmartThingsEntityDescription = (
    AdvancedSmartThingsSensorEntityDescription
    | AdvancedSmartThingsBinarySensorEntityDescription
    | AdvancedSmartThingsSwitchEntityDescription
    | AdvancedSmartThingsSelectEntityDescription
    | AdvancedSmartThingsButtonEntityDescription
    | AdvancedSmartThingsNumberEntityDescription
)


def build_entity_descriptions(
    device: DeviceRecord,
    capability_definitions: dict[tuple[str, int], dict[str, Any] | None],
) -> list[AdvancedSmartThingsEntityDescription]:
    """Build the explicit v1 entity set for a supported SmartThings appliance."""
    descriptions: list[AdvancedSmartThingsEntityDescription] = []
    if _is_oven(device):
        descriptions.extend(_build_oven_descriptions(device, capability_definitions))
    if _is_refrigerator(device):
        descriptions.extend(_build_refrigerator_descriptions(device, capability_definitions))
    if _is_cooktop(device):
        descriptions.extend(_build_cooktop_descriptions(device))
    return descriptions


def normalize_string_value(raw_value: Any) -> str | None:
    """Normalize a SmartThings attribute value to a lowercase string."""
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return "true" if raw_value else "false"
    if isinstance(raw_value, str):
        return raw_value.casefold()
    return str(raw_value).casefold()


def normalize_bool_value(raw_value: Any) -> TruthValue:
    """Normalize a SmartThings attribute value to a boolean where possible."""
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, int | float):
        return bool(raw_value)
    string_value = normalize_string_value(raw_value)
    if string_value in {"true", "enabled", "on", "open", "opened", "run", "running"}:
        return True
    if string_value in {"false", "disabled", "off", "closed", "ready", "finished"}:
        return False
    return None


def coerce_numeric_value(raw_value: Any) -> float | None:
    """Convert a SmartThings attribute value to a number."""
    if isinstance(raw_value, int | float):
        return float(raw_value)
    if isinstance(raw_value, str):
        try:
            return float(raw_value)
        except ValueError:
            return None
    return None


def format_duration_minutes(minutes: float) -> str:
    """Render a minute value as HH:MM:SS for SmartThings."""
    total_seconds = max(0, round(minutes * 60))
    hours, remainder = divmod(total_seconds, 3600)
    whole_minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{whole_minutes:02d}:{seconds:02d}"


def parse_duration_minutes(raw_value: Any) -> float | None:
    """Convert a SmartThings HH:MM:SS value into minutes."""
    if raw_value is None:
        return None
    if isinstance(raw_value, int | float):
        return float(raw_value) / 60.0
    if not isinstance(raw_value, str):
        return None
    parts = raw_value.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (int(part) for part in parts)
    except ValueError:
        return None
    return (hours * 3600 + minutes * 60 + seconds) / 60.0


def normalize_temperature_unit(raw_value: Any) -> str | None:
    """Normalize SmartThings temperature units to Home Assistant units."""
    if not isinstance(raw_value, str):
        return None
    if raw_value == "C":
        return UnitOfTemperature.CELSIUS
    if raw_value == "F":
        return UnitOfTemperature.FAHRENHEIT
    return raw_value


def normalize_oven_mode(raw_value: Any, language: str = "en") -> str | None:
    """Map raw SmartThings oven modes to user-facing select options."""
    if not isinstance(raw_value, str) or not raw_value:
        return None
    language = _normalize_language(language)
    translations = OVEN_MODE_TRANSLATIONS.get(raw_value)
    if translations is not None:
        return translations.get(language, translations["en"])
    return _humanize_oven_mode(raw_value)


def resolve_standard_oven_start_mode(
    raw_mode: str,
    supported_modes: Sequence[str],
) -> str | None:
    """Resolve a Samsung-specific oven mode to a standard SmartThings start argument."""
    if raw_mode in supported_modes:
        return raw_mode

    mapped_mode = STANDARD_OVEN_START_MODE_MAP.get(raw_mode)
    if mapped_mode in supported_modes:
        return mapped_mode
    return None


def denormalize_oven_mode(
    option: str,
    *,
    language: str = "en",
    raw_options: Sequence[str] | None = None,
) -> str:
    """Map a displayed oven mode back to the SmartThings raw value."""
    language = _normalize_language(language)
    for raw_mode in raw_options or OVEN_MODE_TRANSLATIONS:
        if normalize_oven_mode(raw_mode, language) == option:
            return raw_mode
    return option


def oven_mode_display_language(language: str | None) -> str:
    """Return the supported display language for oven mode labels."""
    return _normalize_language(language)


def _normalize_language(language: str | None) -> str:
    if isinstance(language, str) and language.casefold().startswith("de"):
        return "de"
    return "en"


def _humanize_oven_mode(raw_value: str) -> str:
    spaced = raw_value.replace("_", " ").replace("+", " + ")
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", spaced)
    spaced = re.sub(r"(?<=[A-Za-z])(?=[0-9])", " ", spaced)
    return re.sub(r"\s+", " ", spaced).strip()


def _build_oven_descriptions(
    device: DeviceRecord,
    capability_definitions: dict[tuple[str, int], dict[str, Any] | None],
) -> list[AdvancedSmartThingsEntityDescription]:
    descriptions: list[AdvancedSmartThingsEntityDescription] = []
    control_component = _find_first_component_with_capabilities(
        device,
        ("samsungce.ovenMode", "samsungce.ovenOperatingState", "ovenSetpoint"),
    )
    lamp_capability = _find_capability(device, "samsungce.lamp")
    remote_control_capability = _find_capability(device, "remoteControlStatus")
    specification_capability = _find_component_capability(
        device,
        "main",
        "samsungce.kitchenModeSpecification",
    )

    if control_component is None:
        return descriptions

    if remote_control_capability is not None:
        descriptions.append(
            AdvancedSmartThingsBinarySensorEntityDescription(
                key=_entity_key(remote_control_capability, "remote_control"),
                name="Remote control",
                translation_key="oven_remote_control",
                device_id=device.device_id,
                device_label=device.label,
                component_id=remote_control_capability.component_id,
                component_label=remote_control_capability.component_label,
                capability=remote_control_capability.capability_id,
                value_path=("remoteControlEnabled", "value"),
                on_values=("true",),
                off_values=("false",),
            )
        )

    oven_mode_capability = _find_component_capability(
        device, control_component, "samsungce.ovenMode"
    )
    if oven_mode_capability is not None:
        descriptions.append(
            AdvancedSmartThingsSelectEntityDescription(
                key=_entity_key(oven_mode_capability, "mode"),
                name="Oven mode",
                translation_key="oven_mode",
                device_id=device.device_id,
                device_label=device.label,
                component_id=oven_mode_capability.component_id,
                component_label=oven_mode_capability.component_label,
                capability=oven_mode_capability.capability_id,
                requires_remote_control=True,
                value_path=("ovenMode", "value"),
                command="setOvenMode",
                options_path=("supportedOvenModes", "value"),
                fallback_options=tuple(
                    _enum_options(
                        capability_definitions.get(("samsungce.ovenMode", 1)),
                        "supportedOvenModes",
                        "setOvenMode",
                    )
                ),
            )
        )

    oven_timer_capability = _find_component_capability(
        device,
        control_component,
        "samsungce.ovenOperatingState",
    )
    if oven_timer_capability is not None and specification_capability is not None:
        descriptions.append(
            AdvancedSmartThingsNumberEntityDescription(
                key=_entity_key(oven_timer_capability, "timer"),
                name="Timer",
                translation_key="oven_timer",
                device_id=device.device_id,
                device_label=device.label,
                component_id=oven_timer_capability.component_id,
                component_label=oven_timer_capability.component_label,
                capability=oven_timer_capability.capability_id,
                requires_remote_control=True,
                value_path=("operationTime", "value"),
                command="setOperationTime",
                value_kind="duration_minutes",
                range_strategy="oven_timer_spec",
                static_min_value=0,
                static_max_value=720,
                static_step=1,
                native_unit_of_measurement=UnitOfTime.MINUTES,
                device_class=NumberDeviceClass.DURATION,
                mode=NumberMode.BOX,
                cast_to_int=True,
            )
        )

        descriptions.append(
            AdvancedSmartThingsButtonEntityDescription(
                key=_entity_key(oven_timer_capability, "start_program"),
                name="Start program",
                translation_key="oven_start_program",
                device_id=device.device_id,
                device_label=device.label,
                component_id=oven_timer_capability.component_id,
                component_label=oven_timer_capability.component_label,
                capability=oven_timer_capability.capability_id,
                requires_remote_control=True,
                command="start",
                press_strategy="oven_start_program",
                icon="mdi:play",
            )
        )
        descriptions.append(
            AdvancedSmartThingsButtonEntityDescription(
                key=_entity_key(oven_timer_capability, "stop_program"),
                name="Stop program",
                translation_key="oven_stop_program",
                device_id=device.device_id,
                device_label=device.label,
                component_id=oven_timer_capability.component_id,
                component_label=oven_timer_capability.component_label,
                capability=oven_timer_capability.capability_id,
                requires_remote_control=True,
                command="stop",
                icon="mdi:stop",
            )
        )

    oven_setpoint_capability = _find_component_capability(device, control_component, "ovenSetpoint")
    if oven_setpoint_capability is not None and specification_capability is not None:
        descriptions.append(
            AdvancedSmartThingsNumberEntityDescription(
                key=_entity_key(oven_setpoint_capability, "temperature"),
                name="Temperature",
                translation_key="oven_temperature",
                device_id=device.device_id,
                device_label=device.label,
                component_id=oven_setpoint_capability.component_id,
                component_label=oven_setpoint_capability.component_label,
                capability=oven_setpoint_capability.capability_id,
                requires_remote_control=True,
                value_path=("ovenSetpoint", "value"),
                unit_path=("ovenSetpoint", "unit"),
                command="setOvenSetpoint",
                fallback_range=_numeric_schema(
                    capability_definitions.get(("ovenSetpoint", 1)),
                    "ovenSetpoint",
                    "setOvenSetpoint",
                ),
                range_strategy="oven_temperature_spec",
                static_min_value=30,
                static_max_value=300,
                static_step=5,
                device_class=NumberDeviceClass.TEMPERATURE,
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                mode=NumberMode.BOX,
                cast_to_int=True,
                icon="mdi:thermometer",
            )
        )

    if lamp_capability is not None:
        descriptions.append(
            AdvancedSmartThingsSwitchEntityDescription(
                key=_entity_key(lamp_capability, "lamp"),
                name="Lamp",
                translation_key="oven_lamp",
                device_id=device.device_id,
                device_label=device.label,
                component_id=lamp_capability.component_id,
                component_label=lamp_capability.component_label,
                capability=lamp_capability.capability_id,
                state_path=("brightnessLevel", "value"),
                supported_values_path=("supportedBrightnessLevel", "value"),
                on_command="setBrightnessLevel",
                off_command="setBrightnessLevel",
                off_arguments=("off",),
                use_supported_non_off_value=True,
                icon="mdi:lightbulb",
            )
        )

    return descriptions


def _build_refrigerator_descriptions(
    device: DeviceRecord,
    capability_definitions: dict[tuple[str, int], dict[str, Any] | None],
) -> list[AdvancedSmartThingsEntityDescription]:
    descriptions: list[AdvancedSmartThingsEntityDescription] = []

    refrigerator_door = _find_component_capability(device, "cooler", "contactSensor")
    if refrigerator_door is not None:
        descriptions.append(
            AdvancedSmartThingsBinarySensorEntityDescription(
                key=_entity_key(refrigerator_door, "door"),
                name="Refrigerator door",
                translation_key="refrigerator_door",
                device_id=device.device_id,
                device_label=device.label,
                component_id=refrigerator_door.component_id,
                component_label=refrigerator_door.component_label,
                capability=refrigerator_door.capability_id,
                value_path=("contact", "value"),
                device_class=BinarySensorDeviceClass.DOOR,
                on_values=("open",),
                off_values=("closed",),
            )
        )

    freezer_door = _find_component_capability(device, "freezer", "contactSensor")
    if freezer_door is not None:
        descriptions.append(
            AdvancedSmartThingsBinarySensorEntityDescription(
                key=_entity_key(freezer_door, "door"),
                name="Freezer door",
                translation_key="freezer_door",
                device_id=device.device_id,
                device_label=device.label,
                component_id=freezer_door.component_id,
                component_label=freezer_door.component_label,
                capability=freezer_door.capability_id,
                value_path=("contact", "value"),
                device_class=BinarySensorDeviceClass.DOOR,
                on_values=("open",),
                off_values=("closed",),
            )
        )

    thermostat_definition = capability_definitions.get(("thermostatCoolingSetpoint", 1))
    refrigerator_temperature = _find_component_capability(
        device,
        "cooler",
        "thermostatCoolingSetpoint",
    )
    if refrigerator_temperature is not None:
        descriptions.append(
            AdvancedSmartThingsNumberEntityDescription(
                key=_entity_key(refrigerator_temperature, "setpoint"),
                name="Refrigerator temperature",
                translation_key="refrigerator_temperature",
                device_id=device.device_id,
                device_label=device.label,
                component_id=refrigerator_temperature.component_id,
                component_label=refrigerator_temperature.component_label,
                capability=refrigerator_temperature.capability_id,
                value_path=("coolingSetpoint", "value"),
                unit_path=("coolingSetpoint", "unit"),
                range_path=("coolingSetpointRange", "value"),
                fallback_range=_numeric_schema(
                    thermostat_definition,
                    "coolingSetpoint",
                    "setCoolingSetpoint",
                ),
                range_strategy="status_range",
                command="setCoolingSetpoint",
                device_class=NumberDeviceClass.TEMPERATURE,
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                mode=NumberMode.BOX,
                cast_to_int=True,
            )
        )

    freezer_temperature = _find_component_capability(
        device,
        "freezer",
        "thermostatCoolingSetpoint",
    )
    if freezer_temperature is not None:
        descriptions.append(
            AdvancedSmartThingsNumberEntityDescription(
                key=_entity_key(freezer_temperature, "setpoint"),
                name="Freezer temperature",
                translation_key="freezer_temperature",
                device_id=device.device_id,
                device_label=device.label,
                component_id=freezer_temperature.component_id,
                component_label=freezer_temperature.component_label,
                capability=freezer_temperature.capability_id,
                value_path=("coolingSetpoint", "value"),
                unit_path=("coolingSetpoint", "unit"),
                range_path=("coolingSetpointRange", "value"),
                fallback_range=_numeric_schema(
                    thermostat_definition,
                    "coolingSetpoint",
                    "setCoolingSetpoint",
                ),
                range_strategy="status_range",
                command="setCoolingSetpoint",
                device_class=NumberDeviceClass.TEMPERATURE,
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                mode=NumberMode.BOX,
                cast_to_int=True,
            )
        )

    power_consumption = _find_component_capability(device, "main", "powerConsumptionReport")
    if power_consumption is not None:
        descriptions.append(
            AdvancedSmartThingsSensorEntityDescription(
                key=_entity_key(power_consumption, "power"),
                name="Power consumption",
                translation_key="current_power_consumption",
                device_id=device.device_id,
                device_label=device.label,
                component_id=power_consumption.component_id,
                component_label=power_consumption.component_label,
                capability=power_consumption.capability_id,
                value_path=("powerConsumption", "value", "power"),
                state_kind="numeric",
                device_class=SensorDeviceClass.POWER,
                native_unit_of_measurement=UnitOfPower.WATT,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:flash",
            )
        )

    water_filter = _find_component_capability(device, "main", "custom.waterFilter")
    if water_filter is not None:
        descriptions.append(
            AdvancedSmartThingsSensorEntityDescription(
                key=_entity_key(water_filter, "usage"),
                name="Water filter usage",
                translation_key="water_filter_usage",
                device_id=device.device_id,
                device_label=device.label,
                component_id=water_filter.component_id,
                component_label=water_filter.component_label,
                capability=water_filter.capability_id,
                value_path=("waterFilterUsage", "value"),
                state_kind="numeric",
                native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:water-percent",
            )
        )

    return descriptions


def _build_cooktop_descriptions(device: DeviceRecord) -> list[AdvancedSmartThingsEntityDescription]:
    descriptions: list[AdvancedSmartThingsEntityDescription] = []
    switch_capability = _find_component_capability(device, "main", "switch")
    if switch_capability is not None:
        descriptions.append(
            AdvancedSmartThingsBinarySensorEntityDescription(
                key=_entity_key(switch_capability, "active"),
                name="Cooktop active",
                translation_key="cooktop_active",
                device_id=device.device_id,
                device_label=device.label,
                component_id=switch_capability.component_id,
                component_label=switch_capability.component_label,
                capability=switch_capability.capability_id,
                value_path=("switch", "value"),
                on_values=("on",),
                off_values=("off",),
                icon="mdi:stove",
            )
        )
    return descriptions


def _is_oven(device: DeviceRecord) -> bool:
    return _matches_device(
        device, categories={"oven"}, ocf_device_types={"oic.d.oven"}, name_tokens={"[oven]"}
    )


def _is_refrigerator(device: DeviceRecord) -> bool:
    return _matches_device(
        device,
        categories={"refrigerator"},
        ocf_device_types={"oic.d.refrigerator"},
        name_tokens={"family hub"},
    )


def _is_cooktop(device: DeviceRecord) -> bool:
    return _matches_device(
        device,
        categories={"cooktop"},
        ocf_device_types={"oic.d.cooktop"},
        name_tokens={"[cooktop]"},
    )


def _matches_device(
    device: DeviceRecord,
    *,
    categories: set[str],
    ocf_device_types: set[str],
    name_tokens: set[str],
) -> bool:
    device_categories = {
        category_name.casefold() for category_name in _component_category_names(device.raw, "main")
    }
    if device_categories & {category.casefold() for category in categories}:
        return True

    ocf_device_type = device.raw.get("ocfDeviceType")
    if isinstance(ocf_device_type, str) and ocf_device_type.casefold() in {
        item.casefold() for item in ocf_device_types
    }:
        return True

    device_name = (device.name or "").casefold()
    return any(token.casefold() in device_name for token in name_tokens)


def _component_category_names(raw_device: dict[str, Any], component_id: str) -> tuple[str, ...]:
    categories: list[str] = []
    raw_components = raw_device.get("components")
    if not isinstance(raw_components, list):
        return ()
    for raw_component in raw_components:
        if not isinstance(raw_component, dict):
            continue
        if raw_component.get("id") != component_id:
            continue
        raw_categories = raw_component.get("categories")
        if not isinstance(raw_categories, list):
            continue
        for raw_category in raw_categories:
            if not isinstance(raw_category, dict):
                continue
            category_name = raw_category.get("name")
            if isinstance(category_name, str) and category_name:
                categories.append(category_name)
    return tuple(categories)


def _find_first_component_with_capabilities(
    device: DeviceRecord,
    capability_ids: tuple[str, ...],
) -> str | None:
    component_capabilities: dict[str, set[str]] = {}
    for capability in device.capabilities:
        component_capabilities.setdefault(capability.component_id, set()).add(
            capability.capability_id
        )

    preferred_components = sorted(
        component_capabilities,
        key=lambda component_id: (component_id == "main", component_id),
    )
    for component_id in preferred_components:
        if all(
            capability_id in component_capabilities[component_id]
            for capability_id in capability_ids
        ):
            return component_id
    return None


def _find_component_capability(
    device: DeviceRecord,
    component_id: str,
    capability_id: str,
) -> CapabilityRef | None:
    for capability in device.capabilities:
        if capability.component_id == component_id and capability.capability_id == capability_id:
            return capability
    return None


def _find_capability(device: DeviceRecord, capability_id: str) -> CapabilityRef | None:
    for capability in device.capabilities:
        if capability.capability_id == capability_id:
            return capability
    return None


def _entity_key(capability_ref: CapabilityRef, suffix: str) -> str:
    component = capability_ref.component_id.replace(" ", "_").casefold()
    capability = capability_ref.capability_id.replace(".", "_").casefold()
    return f"{component}_{capability}_{suffix}"


def _enum_options(
    definition: dict[str, Any] | None,
    attribute_name: str,
    command_name: str,
) -> list[str]:
    if definition is None:
        return []
    for schema in (
        _extract_attribute_schema(definition, attribute_name),
        _extract_command_argument_schema(definition, command_name),
    ):
        options = _find_string_enum(schema)
        if options:
            return options
    return []


def _numeric_schema(
    definition: dict[str, Any] | None,
    attribute_name: str,
    command_name: str,
) -> NumberRange | None:
    if definition is None:
        return None
    for schema in (
        _extract_command_argument_schema(definition, command_name),
        _extract_attribute_schema(definition, attribute_name),
    ):
        parsed = _find_numeric_constraints(schema)
        if parsed is not None:
            return parsed
    return None


def _extract_attribute_schema(
    definition: dict[str, Any], attribute_name: str
) -> dict[str, Any] | None:
    attributes = definition.get("attributes")
    if not isinstance(attributes, dict):
        return None
    attribute = attributes.get(attribute_name)
    if not isinstance(attribute, dict):
        return None
    schema = attribute.get("schema")
    return schema if isinstance(schema, dict) else None


def _extract_command_argument_schema(
    definition: dict[str, Any], command_name: str
) -> dict[str, Any] | None:
    commands = definition.get("commands")
    if not isinstance(commands, dict):
        return None
    command = commands.get(command_name)
    if not isinstance(command, dict):
        return None
    arguments = command.get("arguments")
    if not isinstance(arguments, list) or not arguments:
        return None
    first_argument = arguments[0]
    if not isinstance(first_argument, dict):
        return None
    schema = first_argument.get("schema")
    return schema if isinstance(schema, dict) else None


def _find_string_enum(schema: dict[str, Any] | None) -> list[str]:
    if schema is None:
        return []

    if schema.get("type") == "string":
        enum = schema.get("enum")
        if isinstance(enum, list) and all(isinstance(item, str) for item in enum):
            return [item for item in enum if item]

    properties = schema.get("properties")
    if isinstance(properties, dict):
        value_schema = properties.get("value")
        if isinstance(value_schema, dict):
            nested = _find_string_enum(value_schema)
            if nested:
                return nested

    items = schema.get("items")
    if isinstance(items, dict):
        return _find_string_enum(items)

    return []


def _find_numeric_constraints(schema: dict[str, Any] | None) -> NumberRange | None:
    if schema is None:
        return None

    schema_type = schema.get("type")
    if schema_type in {"integer", "number"}:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, int | float) and isinstance(maximum, int | float):
            step = schema.get("multipleOf")
            parsed_step = float(step) if isinstance(step, int | float) else 1.0
            return float(minimum), float(maximum), parsed_step, schema_type == "integer"

    properties = schema.get("properties")
    if isinstance(properties, dict):
        value_schema = properties.get("value")
        if isinstance(value_schema, dict):
            nested = _find_numeric_constraints(value_schema)
            if nested is not None:
                return nested

    return None
