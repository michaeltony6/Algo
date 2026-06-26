from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from delivery_optimizer.models import Offer


class ApiIntegrationError(RuntimeError):
    """Raised when an upstream delivery API call fails."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ApiCredentialsError(ApiIntegrationError):
    """Raised when a connector is missing required credentials."""


class DeliveryPlatformClient(Protocol):
    platform: str

    def fetch_available_offers(self) -> list[Offer]:
        """Return normalized offers when the official integration exposes them."""


@dataclass(frozen=True)
class ApiRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes = b""


@dataclass(frozen=True)
class ClientSettings:
    timeout_seconds: float = 20.0
    max_retries: int = 2
    backoff_seconds: float = 0.25
    retry_status_codes: tuple[int, ...] = (408, 409, 425, 429, 500, 502, 503, 504)
