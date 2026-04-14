from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SmartThingsError(Exception):
    """Base SmartThings integration error."""

    message: str


class SmartThingsAuthError(SmartThingsError):
    """Raised when the SmartThings token is invalid."""


class SmartThingsApiError(SmartThingsError):
    """Raised when a SmartThings API request fails."""


class SmartThingsConnectionError(SmartThingsError):
    """Raised when SmartThings cannot be reached."""
