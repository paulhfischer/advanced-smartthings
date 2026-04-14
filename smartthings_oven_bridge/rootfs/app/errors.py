from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class BridgeError(Exception):
    code: str
    message: str
    status_code: int
    details: Any | None = None

    def to_response(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return payload


class ConfigurationError(BridgeError):
    def __init__(self, message: str, details: object | None = None) -> None:
        super().__init__(
            code="missing_config",
            message=message,
            status_code=400,
            details=details,
        )


class InvalidOAuthStateError(BridgeError):
    def __init__(self, message: str = "OAuth state is invalid or expired.") -> None:
        super().__init__(
            code="invalid_oauth_state",
            message=message,
            status_code=400,
        )


class AuthenticationRequiredError(BridgeError):
    def __init__(self, message: str = "SmartThings authorization is required.") -> None:
        super().__init__(
            code="reauth_required",
            message=message,
            status_code=401,
        )


class TokenRefreshError(BridgeError):
    def __init__(self, message: str = "Unable to refresh the SmartThings access token.") -> None:
        super().__init__(
            code="token_refresh_failed",
            message=message,
            status_code=401,
        )


class UpstreamPermissionError(BridgeError):
    def __init__(self, message: str = "SmartThings denied access to this device.") -> None:
        super().__init__(
            code="smartthings_forbidden",
            message=message,
            status_code=502,
        )


class UpstreamNotFoundError(BridgeError):
    def __init__(self, message: str = "The requested SmartThings resource was not found.") -> None:
        super().__init__(
            code="smartthings_not_found",
            message=message,
            status_code=404,
        )


class UnsupportedCapabilityError(BridgeError):
    def __init__(
        self,
        message: str = "This oven does not expose a supported command mapping.",
        details: object | None = None,
    ) -> None:
        super().__init__(
            code="unsupported_capability_mapping",
            message=message,
            status_code=400,
            details=details,
        )


class UpstreamTimeoutError(BridgeError):
    def __init__(self, message: str = "Timed out while talking to SmartThings.") -> None:
        super().__init__(
            code="smartthings_timeout",
            message=message,
            status_code=504,
        )


class UpstreamRequestError(BridgeError):
    def __init__(
        self,
        message: str = "SmartThings request failed.",
        details: object | None = None,
    ) -> None:
        super().__init__(
            code="smartthings_request_failed",
            message=message,
            status_code=502,
            details=details,
        )


class StorageError(BridgeError):
    def __init__(self, message: str, details: object | None = None) -> None:
        super().__init__(
            code="storage_error",
            message=message,
            status_code=502,
            details=details,
        )
