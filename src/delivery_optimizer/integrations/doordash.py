from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from delivery_optimizer.models import Offer, OfferSource

from .auth import hs256_jwt, now_epoch
from .base import ApiCredentialsError, ApiIntegrationError, ApiRequest
from .http import UrlLibHttpClient


@dataclass(frozen=True)
class DoorDashCredentials:
    developer_id: str
    key_id: str
    signing_secret: str

    def validate(self) -> None:
        if not self.developer_id or not self.key_id or not self.signing_secret:
            raise ApiCredentialsError("DoorDash developer_id, key_id, and signing_secret are required")

    @staticmethod
    def from_env(prefix: str = "DOORDASH") -> DoorDashCredentials:
        return DoorDashCredentials(
            developer_id=os.environ.get(f"{prefix}_DEVELOPER_ID", ""),
            key_id=os.environ.get(f"{prefix}_KEY_ID", ""),
            signing_secret=os.environ.get(f"{prefix}_SIGNING_SECRET", ""),
        )


class DoorDashDriveClient:
    platform = "doordash"

    def __init__(
        self,
        credentials: DoorDashCredentials,
        base_url: str = "https://openapi.doordash.com",
        http_client: UrlLibHttpClient | None = None,
    ) -> None:
        credentials.validate()
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client or UrlLibHttpClient()

    def build_jwt(self, lifetime_seconds: int = 300) -> str:
        if lifetime_seconds <= 0:
            raise ValueError("lifetime_seconds must be positive")
        issued_at = now_epoch()
        return hs256_jwt(
            header={"alg": "HS256", "typ": "JWT", "kid": self.credentials.key_id},
            payload={
                "aud": "doordash",
                "iss": self.credentials.developer_id,
                "kid": self.credentials.key_id,
                "iat": issued_at,
                "exp": issued_at + lifetime_seconds,
            },
            secret=self.credentials.signing_secret,
        )

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.build_jwt()}",
            "Content-Type": "application/json",
            "User-Agent": "DeliverySessionOptimizer/0.1",
        }

    def create_delivery_quote(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = ApiRequest(
            method="POST",
            url=f"{self.base_url}/drive/v2/quotes",
            headers=self.headers(),
            body=body,
        )
        return self.http_client.send(request).json()

    def fetch_available_offers(self) -> list[Offer]:
        raise ApiIntegrationError(
            "DoorDash's public Drive/Marketplace APIs do not expose a driver-offer feed. "
            "Use approved webhooks, quote/order data, or manual offer capture."
        )

    @staticmethod
    def quote_to_offer(payload: dict[str, Any], offer_id: str | None = None) -> Offer:
        fee_cents = _first_number(payload, "fee", "fee_cents", "delivery_fee", "delivery_fee_cents")
        distance_miles = _meters_to_miles(_first_number(payload, "distance_meters", "route_distance_meters"))
        duration_minutes = _seconds_to_minutes(_first_number(payload, "duration_seconds", "estimated_duration_seconds"))
        return Offer(
            platform="doordash",
            offer_id=offer_id or str(payload.get("external_delivery_id") or payload.get("id") or "doordash_quote"),
            gross_payout=round(fee_cents / 100, 2) if fee_cents > 100 else fee_cents,
            pickup_miles=0.0,
            dropoff_miles=distance_miles,
            estimated_minutes=max(duration_minutes, 1.0),
            source=OfferSource.API,
            confidence=0.75,
            metadata=payload,
        )


def _first_number(payload: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _meters_to_miles(value: float) -> float:
    return round(value / 1609.344, 2) if value else 0.0


def _seconds_to_minutes(value: float) -> float:
    return round(value / 60, 1) if value else 0.0
