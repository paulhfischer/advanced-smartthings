from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import Field

from .models import AddonOptions


DATA_DIR = Path(os.getenv("SMARTTHINGS_OVEN_BRIDGE_DATA_DIR", "/data"))
OPTIONS_PATH = Path(
    os.getenv(
        "SMARTTHINGS_OVEN_BRIDGE_OPTIONS_PATH",
        str(DATA_DIR / "options.json"),
    )
)
STATE_PATH = Path(
    os.getenv(
        "SMARTTHINGS_OVEN_BRIDGE_STATE_PATH",
        str(DATA_DIR / "state.json"),
    )
)
API_PORT = 8080
INGRESS_PORT = 8099
OAUTH_SCOPE = "x:devices:* r:devices:*"
OAUTH_AUTHORIZE_URL = "https://api.smartthings.com/oauth/authorize"
OAUTH_TOKEN_URL = "https://api.smartthings.com/oauth/token"
SUPERVISOR_URL = "http://supervisor"
TOKEN_REFRESH_SKEW_SECONDS = 300
OAUTH_STATE_TTL_SECONDS = 600
START_WARMING_DEDUPE_SECONDS = 30
RECENT_ERRORS_LIMIT = 20


class ServiceSettings(AddonOptions):
    data_dir: Path = DATA_DIR
    state_path: Path = STATE_PATH
    options_path: Path = OPTIONS_PATH
    api_port: int = API_PORT
    ingress_port: int = INGRESS_PORT
    oauth_scope: str = OAUTH_SCOPE
    oauth_authorize_url: str = OAUTH_AUTHORIZE_URL
    oauth_token_url: str = OAUTH_TOKEN_URL
    supervisor_url: str = SUPERVISOR_URL
    supervisor_token: str | None = Field(default_factory=lambda: os.getenv("SUPERVISOR_TOKEN"))
    token_refresh_skew_seconds: int = TOKEN_REFRESH_SKEW_SECONDS
    oauth_state_ttl_seconds: int = OAUTH_STATE_TTL_SECONDS
    start_warming_dedupe_seconds: int = START_WARMING_DEDUPE_SECONDS
    recent_errors_limit: int = RECENT_ERRORS_LIMIT

    def has_oauth_credentials(self) -> bool:
        return bool(self.smartthings_client_id and self.smartthings_client_secret)

    def has_device_id(self) -> bool:
        return bool(self.smartthings_device_id)

    def is_configured(self) -> bool:
        return self.has_oauth_credentials() and self.has_device_id()


def load_settings(options_path: Path = OPTIONS_PATH) -> ServiceSettings:
    raw_options: dict[str, object] = {}
    if options_path.exists():
        with options_path.open("r", encoding="utf-8") as handle:
            raw_options = json.load(handle)
    return ServiceSettings(**raw_options)


def configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
