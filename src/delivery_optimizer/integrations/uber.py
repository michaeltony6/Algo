from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from delivery_optimizer.models import Offer, OfferSource

from .base import ApiCredentialsError, ApiIntegrationError, ApiRequest
from .http import UrlLibHttpClient


@dataclass(frozen=True)
class UberCredentials:
    client_id: str
    client_secret: str
    scope: str = "eats.order"

    def validate(self) -> None:
        if not self.client_id or not self.client_secret:
            raise ApiCredentialsError("Uber client_id and client_secret are required")


class UberEatsClient:
    platform = "uber_eats"

    def __init__(
        self,
        credentials: UberCredentials,
        base_url: str = "https://api.uber.com",
        token_url: str = "https://auth.uber.com/oauth/v2/token",
        http_client: UrlLibHttpClient | None = None,
    ) -> None:
        credentials.validate()
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.token_url = token_url
        self.http_client = http_client or UrlLibHttpClient()
        self._access_token: str | None = None

    def fetch_access_token(self) -> str:
        body = urlencode(
            {
                "client_id": self.credentials.client_id,
                "client_secret": self.credentials.client_secret,
                "grant_type": "client_credentials",
                "scope": self.credentials.scope,
            }
        ).encode("utf-8")
        request = ApiRequest(
            method="POST",
            url=self.token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=body,
        )
        payload = self.http_client.send(request).json()
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ApiIntegrationError("Uber token response did not include access_token")
        self._access_token = token
        return token

    def headers(self) -> dict[str, str]:
        token = self._access_token or self.fetch_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip",
        }

    def get_order(self, order_id: str) -> dict[str, Any]:
        request = ApiRequest(
            method="GET",
            url=f"{self.base_url}/v2/eats/order/{order_id}",
            headers=self.headers(),
        )
        return self.http_client.send(request).json()

    def fetch_available_offers(self) -> list[Offer]:
        raise ApiIntegrationError(
            "Uber Eats Marketplace APIs expose approved merchant/store/order workflows, "
            "not a public courier-offer feed. Use approved order payloads or manual offer capture."
        )

    @staticmethod
    def order_to_offer(payload: dict[str, Any], fallback_minutes: float = 25.0) -> Offer:
        payout = _money(payload, "estimated_payout", "courier_payout", "delivery_fee", "total")
        distance = _distance_miles(payload)
        duration = _duration_minutes(payload) or fallback_minutes
        return Offer(
            platform="uber_eats",
            offer_id=str(payload.get("id") or payload.get("order_id") or "uber_eats_order"),
            gross_payout=payout,
            pickup_miles=0.0,
            dropoff_miles=distance,
            estimated_minutes=max(duration, 1.0),
            source=OfferSource.API,
            confidence=0.75,
            metadata=payload,
        )


def _money(payload: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return round(float(value), 2)
        if isinstance(value, dict):
            amount = value.get("amount") or value.get("value")
            if isinstance(amount, (int, float)):
                return round(float(amount) / 100, 2) if amount > 100 else round(float(amount), 2)
    return 0.0


def _distance_miles(payload: dict[str, Any]) -> float:
    for key in ("distance_miles", "route_distance_miles"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return round(float(value), 2)
    for key in ("distance_meters", "route_distance_meters"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return round(float(value) / 1609.344, 2)
    return 0.0


def _duration_minutes(payload: dict[str, Any]) -> float:
    for key in ("duration_minutes", "estimated_minutes"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return round(float(value), 1)
    for key in ("duration_seconds", "estimated_duration_seconds"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return round(float(value) / 60, 1)
    return 0.0
