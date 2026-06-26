from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from delivery_optimizer.models import Offer


class ApiIntegrationError(RuntimeError):
    """Raised when an upstream delivery API call fails."""


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
