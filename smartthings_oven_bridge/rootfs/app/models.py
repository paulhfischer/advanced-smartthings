from __future__ import annotations

from datetime import datetime
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import SecretStr


class AddonOptions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    smartthings_client_id: str | None = Field(default=None, min_length=1)
    smartthings_client_secret: SecretStr | None = None
    smartthings_device_id: str | None = Field(default=None, min_length=1)
    smartthings_api_base_url: str = "https://api.smartthings.com/v1"
    log_level: Literal["debug", "info", "warning", "error"] = "info"


class TokenBundle(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: datetime
    scope: str | None = None
    token_type: str = "Bearer"


class PendingOAuthState(BaseModel):
    value: str
    callback_url: str
    created_at: datetime
    expires_at: datetime


class RecentError(BaseModel):
    created_at: datetime
    code: str
    message: str
    details: dict[str, Any] | None = None


class DeviceCache(BaseModel):
    metadata: dict[str, Any] | None = None
    status: dict[str, Any] | None = None
    last_refreshed_at: datetime | None = None


class DiscoveredDevice(BaseModel):
    device_id: str = Field(min_length=1)
    label: str | None = None
    name: str | None = None
    manufacturer_name: str | None = None
    device_type_name: str | None = None
    location_id: str | None = None
    room_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    looks_like_oven: bool = False


class DedupeEntry(BaseModel):
    key: str
    expires_at: datetime


class PersistentState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    token: TokenBundle | None = None
    pending_oauth_state: PendingOAuthState | None = None
    auth_broken: bool = False
    auth_broken_reason: str | None = None
    last_successful_contact_at: datetime | None = None
    device_cache: DeviceCache = Field(default_factory=DeviceCache)
    discovered_devices: list[DiscoveredDevice] = Field(default_factory=list)
    recent_errors: list[RecentError] = Field(default_factory=list)
    start_warming_dedupe: DedupeEntry | None = None


class DeviceCommand(BaseModel):
    component: str = Field(default="main", min_length=1)
    capability: str = Field(min_length=1)
    command: str = Field(min_length=1)
    arguments: list[Any] = Field(default_factory=list)


class StartWarmingRequest(BaseModel):
    setpoint: int = Field(ge=1, le=300)
    duration_seconds: int = Field(ge=1, le=86_400)


class RawCommandRequest(BaseModel):
    commands: list[DeviceCommand] = Field(min_length=1)


class CommandResult(BaseModel):
    action: str
    result: str
    commands: list[DeviceCommand] = Field(default_factory=list)
    duration_applied: bool = False
    deduplicated: bool = False
    device_status_checked: bool = False


class CallbackResolution(BaseModel):
    ready: bool
    callback_url: str | None = None
    reason: str | None = None
    source: str | None = None


class InternalApiResolution(BaseModel):
    ready: bool
    base_url: str | None = None
    hostname: str | None = None
    reason: str | None = None
    source: str | None = None
