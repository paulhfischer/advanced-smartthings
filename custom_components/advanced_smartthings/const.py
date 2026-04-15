from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "advanced_smartthings"
NAME = "Advanced SmartThings"

API_BASE_URL = "https://api.smartthings.com/v1"
OAUTH_AUTHORIZE_URL = "https://api.smartthings.com/oauth/authorize"
OAUTH_TOKEN_URL = "https://api.smartthings.com/oauth/token"
OAUTH_SCOPES = (
    "r:devices:*",
    "x:devices:*",
    "r:locations:*",
)

CONF_LOCATION_IDS = "location_ids"
CONF_SELECTED_DEVICE_IDS = "selected_device_ids"
CONF_UNSUPPORTED_CAPABILITIES = "unsupported_capabilities"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=5)
POST_COMMAND_REFRESH_DELAYS = (2, 5, 10)

PLATFORMS: tuple[Platform, ...] = (
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
)
