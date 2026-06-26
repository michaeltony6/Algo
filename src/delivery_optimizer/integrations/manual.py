from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from delivery_optimizer.models import Location, Offer, OfferSource


def offers_from_json(path: str | Path) -> list[Offer]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("offers file must contain a JSON array")
    return [offer_from_mapping(item) for item in raw]


def offers_from_iterable(items: Iterable[dict[str, Any]]) -> list[Offer]:
    return [offer_from_mapping(item) for item in items]


def offer_from_mapping(data: dict[str, Any]) -> Offer:
    payload = dict(data)
    payload["source"] = OfferSource(payload.get("source", OfferSource.MANUAL.value))
    if isinstance(payload.get("pickup_location"), dict):
        payload["pickup_location"] = Location(**payload["pickup_location"])
    if isinstance(payload.get("dropoff_location"), dict):
        payload["dropoff_location"] = Location(**payload["dropoff_location"])
    return Offer(**payload)
