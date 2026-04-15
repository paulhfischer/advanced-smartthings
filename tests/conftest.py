from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_TOKEN
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.advanced_smartthings.const import (
    CONF_LOCATION_IDS,
    CONF_SELECTED_DEVICE_IDS,
    DOMAIN,
    OAUTH_TOKEN_URL,
)

CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"
ACCESS_TOKEN = "test-access-token"
REFRESH_TOKEN = "test-refresh-token"

TOKEN_PAYLOAD = {
    CONF_ACCESS_TOKEN: ACCESS_TOKEN,
    "refresh_token": REFRESH_TOKEN,
    "token_type": "Bearer",
    "expires_in": 3600,
    "scope": "r:devices:* x:devices:* r:locations:*",
}

LOCATIONS_PAYLOAD = {
    "items": [
        {
            "locationId": "location-1",
            "name": "My home",
        }
    ]
}

OVEN_DEVICE = {
    "deviceId": "device-oven-1",
    "label": "Backofen",
    "name": "[oven] Samsung (LCD)",
    "manufacturerName": "Samsung Electronics",
    "type": "OCF",
    "ocfDeviceType": "oic.d.oven",
    "locationId": "location-1",
    "roomId": "room-1",
    "components": [
        {
            "id": "main",
            "label": "main",
            "categories": [{"name": "Oven"}],
            "capabilities": [
                {"id": "remoteControlStatus", "version": 1},
                {"id": "temperatureMeasurement", "version": 1},
                {"id": "samsungce.lamp", "version": 1},
                {"id": "samsungce.kitchenModeSpecification", "version": 1},
                {"id": "samsungce.kitchenDeviceDefaults", "version": 1},
            ],
        },
        {
            "id": "cavity-01",
            "label": "cavity-01",
            "categories": [{"name": "Other"}],
            "capabilities": [
                {"id": "samsungce.ovenMode", "version": 1},
                {"id": "samsungce.ovenOperatingState", "version": 1},
                {"id": "ovenSetpoint", "version": 1},
            ],
        },
    ],
}

FRIDGE_DEVICE = {
    "deviceId": "device-fridge-1",
    "label": "Kühlschrank",
    "name": "Family Hub",
    "manufacturerName": "Samsung Electronics",
    "type": "OCF",
    "locationId": "location-1",
    "roomId": "room-1",
    "components": [
        {
            "id": "main",
            "label": "main",
            "categories": [{"name": "Refrigerator"}],
            "capabilities": [
                {"id": "powerConsumptionReport", "version": 1},
                {"id": "custom.waterFilter", "version": 1},
            ],
        },
        {
            "id": "cooler",
            "label": "cooler",
            "categories": [{"name": "Other"}],
            "capabilities": [
                {"id": "contactSensor", "version": 1},
                {"id": "thermostatCoolingSetpoint", "version": 1},
            ],
        },
        {
            "id": "freezer",
            "label": "freezer",
            "categories": [{"name": "Other"}],
            "capabilities": [
                {"id": "contactSensor", "version": 1},
                {"id": "thermostatCoolingSetpoint", "version": 1},
            ],
        },
    ],
}

COOKTOP_DEVICE = {
    "deviceId": "device-cooktop-1",
    "label": "Kochfeld",
    "name": "[cooktop] Samsung",
    "manufacturerName": "Samsung Electronics",
    "type": "OCF",
    "ocfDeviceType": "oic.d.cooktop",
    "locationId": "location-1",
    "roomId": "room-1",
    "components": [
        {
            "id": "main",
            "label": "main",
            "categories": [{"name": "Cooktop"}],
            "capabilities": [
                {"id": "switch", "version": 1},
                {"id": "custom.cooktopOperatingState", "version": 1},
            ],
        }
    ],
}

UNSUPPORTED_DEVICE = {
    "deviceId": "device-unsupported-1",
    "label": "Unsupported thing",
    "name": "Unsupported thing",
    "manufacturerName": "Unknown",
    "type": "OCF",
    "locationId": "location-1",
    "roomId": "room-1",
    "components": [
        {
            "id": "main",
            "label": "main",
            "categories": [{"name": "Other"}],
            "capabilities": [
                {"id": "execute", "version": 1},
            ],
        }
    ],
}

OVEN_STATUS = {
    "components": {
        "main": {
            "remoteControlStatus": {
                "remoteControlEnabled": {"value": "true"},
            },
            "temperatureMeasurement": {
                "temperature": {"value": 33, "unit": "C"},
            },
            "samsungce.lamp": {
                "brightnessLevel": {"value": "off"},
                "supportedBrightnessLevel": {"value": ["off", "high"]},
            },
            "samsungce.kitchenDeviceDefaults": {
                "defaultOvenMode": {"value": "Convection"},
            },
            "samsungce.kitchenModeSpecification": {
                "specification": {
                    "value": {
                        "single": [
                            {
                                "mode": "Convection",
                                "supportedOptions": {
                                    "temperature": {
                                        "C": {
                                            "min": 30,
                                            "max": 275,
                                            "default": 160,
                                            "resolution": 5,
                                        }
                                    },
                                    "operationTime": {
                                        "min": "00:00:01",
                                        "max": "11:59:59",
                                        "default": "00:30:00",
                                        "resolution": "00:00:01",
                                    },
                                },
                            },
                            {
                                "mode": "KeepWarm",
                                "supportedOptions": {
                                    "temperature": {
                                        "C": {
                                            "min": 40,
                                            "max": 120,
                                            "default": 70,
                                            "resolution": 5,
                                        }
                                    },
                                    "operationTime": {
                                        "min": "00:05:00",
                                        "max": "12:00:00",
                                        "default": "01:00:00",
                                        "resolution": "00:05:00",
                                    },
                                },
                            },
                        ]
                    }
                }
            },
        },
        "cavity-01": {
            "samsungce.ovenMode": {
                "supportedOvenModes": {"value": ["Convection", "KeepWarm"]},
                "ovenMode": {"value": "NoOperation"},
            },
            "samsungce.ovenOperatingState": {
                "operationTime": {"value": "01:30:00"},
                "operatingState": {"value": "ready"},
                "ovenJobState": {"value": "ready"},
            },
            "ovenSetpoint": {
                "ovenSetpoint": {"value": 180, "unit": "C"},
            },
        },
    }
}

OVEN_STATUS_REMOTE_DISABLED = {
    "components": {
        **OVEN_STATUS["components"],
        "main": {
            **OVEN_STATUS["components"]["main"],
            "remoteControlStatus": {
                "remoteControlEnabled": {"value": "false"},
            },
        },
    }
}

FRIDGE_STATUS = {
    "components": {
        "main": {
            "powerConsumptionReport": {
                "powerConsumption": {
                    "value": {
                        "power": 1458,
                    }
                }
            },
            "custom.waterFilter": {
                "waterFilterUsage": {"value": 13},
            },
        },
        "cooler": {
            "contactSensor": {
                "contact": {"value": "closed"},
            },
            "thermostatCoolingSetpoint": {
                "coolingSetpointRange": {
                    "value": {"minimum": 1, "maximum": 7, "step": 1},
                    "unit": "C",
                },
                "coolingSetpoint": {"value": 6, "unit": "C"},
            },
        },
        "freezer": {
            "contactSensor": {
                "contact": {"value": "open"},
            },
            "thermostatCoolingSetpoint": {
                "coolingSetpointRange": {
                    "value": {"minimum": -23, "maximum": -15, "step": 1},
                    "unit": "C",
                },
                "coolingSetpoint": {"value": -18, "unit": "C"},
            },
        },
    }
}

COOKTOP_STATUS = {
    "components": {
        "main": {
            "switch": {
                "switch": {"value": "off"},
            },
            "custom.cooktopOperatingState": {
                "cooktopOperatingState": {"value": "ready"},
            },
        }
    }
}

SAMSUNG_OVEN_MODE_DEFINITION = {
    "attributes": {
        "supportedOvenModes": {
            "schema": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["Convection", "KeepWarm", "NoOperation"],
                        },
                    }
                },
            }
        }
    },
    "commands": {
        "setOvenMode": {
            "arguments": [
                {
                    "schema": {
                        "type": "string",
                        "enum": ["Convection", "KeepWarm", "NoOperation"],
                    }
                }
            ]
        }
    },
}

OVEN_SETPOINT_DEFINITION = {
    "attributes": {
        "ovenSetpoint": {
            "schema": {
                "type": "object",
                "properties": {
                    "value": {"type": "number", "minimum": 0, "maximum": 300},
                    "unit": {"type": "string", "enum": ["C", "F"]},
                },
            }
        }
    },
    "commands": {
        "setOvenSetpoint": {
            "arguments": [
                {
                    "schema": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 300,
                    }
                }
            ]
        }
    },
}

THERMOSTAT_COOLING_SETPOINT_DEFINITION = {
    "attributes": {
        "coolingSetpoint": {
            "schema": {
                "type": "object",
                "properties": {
                    "value": {"type": "number", "minimum": -460, "maximum": 10000},
                    "unit": {"type": "string", "enum": ["C", "F"]},
                },
                "required": ["value", "unit"],
            }
        }
    },
    "commands": {
        "setCoolingSetpoint": {
            "arguments": [
                {
                    "schema": {
                        "type": "number",
                        "minimum": -460,
                        "maximum": 10000,
                    }
                }
            ]
        }
    },
}


def mock_capability_definitions(aioclient_mock) -> None:
    """Register the capability-definition responses used by the tests."""
    aioclient_mock.post(OAUTH_TOKEN_URL, json=TOKEN_PAYLOAD)
    aioclient_mock.get(
        "https://api.smartthings.com/v1/capabilities/samsungce.ovenMode/1",
        json=SAMSUNG_OVEN_MODE_DEFINITION,
    )
    aioclient_mock.get(
        "https://api.smartthings.com/v1/capabilities/ovenSetpoint/1",
        json=OVEN_SETPOINT_DEFINITION,
    )
    aioclient_mock.get(
        "https://api.smartthings.com/v1/capabilities/thermostatCoolingSetpoint/1",
        json=THERMOSTAT_COOLING_SETPOINT_DEFINITION,
    )
    for capability in (
        "samsungce.lamp",
        "samsungce.kitchenModeSpecification",
        "samsungce.kitchenDeviceDefaults",
        "samsungce.ovenOperatingState",
        "powerConsumptionReport",
        "custom.waterFilter",
        "contactSensor",
        "switch",
        "custom.cooktopOperatingState",
        "execute",
    ):
        aioclient_mock.get(
            f"https://api.smartthings.com/v1/capabilities/{capability}/1",
            status=404,
        )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    with patch(
        "custom_components.advanced_smartthings.async_setup_entry",
        return_value=True,
    ) as patched:
        yield patched


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Advanced SmartThings",
        data={
            "auth_implementation": "advanced_smartthings-test",
            CONF_CLIENT_ID: CLIENT_ID,
            CONF_CLIENT_SECRET: CLIENT_SECRET,
            CONF_TOKEN: {
                **TOKEN_PAYLOAD,
                "expires_at": 9_999_999_999,
            },
            CONF_LOCATION_IDS: ["location-1"],
        },
        options={
            CONF_SELECTED_DEVICE_IDS: [
                "device-oven-1",
                "device-fridge-1",
                "device-cooktop-1",
            ]
        },
        unique_id="account-1",
    )
