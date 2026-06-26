from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from delivery_optimizer.models import Offer, OfferSource

from .base import ApiCredentialsError, ApiIntegrationError, ApiRequest
from .http import UrlLibHttpClient


@dataclass(frozen=True)
class GrubhubCredentials:
    partner_key: str
    client_id: str
    signing_secret: str

    def validate(self) -> None:
        if not self.partner_key or not self.client_id or not self.signing_secret:
            raise ApiCredentialsError("Grubhub partner_key, client_id, and signing_secret are required")


class GrubhubPartnerClient:
    platform = "grubhub"

    def __init__(
        self,
        credentials: GrubhubCredentials,
        base_url: str = "https://api-gtm.grubhub.com",
        http_client: UrlLibHttpClient | None = None,
    ) -> None:
        credentials.validate()
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client or UrlLibHttpClient()

    def headers(self, method: str, path: str, body: bytes = b"") -> dict[str, str]:
        return {
            "X-GH-PARTNER-KEY": self.credentials.partner_key,
            "Authorization": self._authorization_header(method, path, body),
            "Content-Type": "application/json",
        }

    def _authorization_header(self, method: str, path: str, body: bytes) -> str:
        parsed = urlparse(self.base_url)
        host = parsed.hostname or "api-gtm.grubhub.com"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        nonce = f"{int(time.time())}:{uuid.uuid4().hex}"
        body_hash = base64.b64encode(hashlib.sha256(body).digest()).decode("ascii")
        normalized = "\n".join(
            [
                nonce,
                method.upper(),
                path,
                host,
                str(port),
                body_hash,
                "",
            ]
        )
        mac = base64.b64encode(
            hmac.new(
                self.credentials.signing_secret.encode("utf-8"),
                normalized.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("ascii")
        return (
            f'MAC id="sv:v1:{self.credentials.client_id}",'
            f'nonce="{nonce}",bodyhash="{body_hash}",mac="{mac}"'
        )

    def post_order_update(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = ApiRequest(
            method="POST",
            url=f"{self.base_url}{path}",
            headers=self.headers("POST", path, body),
            body=body,
        )
        return self.http_client.send(request).json()

    def fetch_available_offers(self) -> list[Offer]:
        raise ApiIntegrationError(
            "Grubhub Partner APIs support merchant/POS menu and order workflows, "
            "not a public courier-offer feed. Use approved order payloads or manual offer capture."
        )

    @staticmethod
    def order_to_offer(payload: dict[str, Any], fallback_minutes: float = 30.0) -> Offer:
        payout = _money(payload)
        distance = _distance_miles(payload)
        return Offer(
            platform="grubhub",
            offer_id=str(payload.get("order_uuid") or payload.get("order_id") or "grubhub_order"),
            gross_payout=payout,
            pickup_miles=0.0,
            dropoff_miles=distance,
            estimated_minutes=float(payload.get("estimated_minutes") or fallback_minutes),
            source=OfferSource.API,
            confidence=0.75,
            metadata=payload,
        )


def _money(payload: dict[str, Any]) -> float:
    for key in ("estimated_payout", "driver_payout", "delivery_fee", "total"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return round(float(value) / 100, 2) if value > 100 else round(float(value), 2)
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
