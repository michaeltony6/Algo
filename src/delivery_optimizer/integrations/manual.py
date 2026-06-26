from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from delivery_optimizer.models import Offer
from delivery_optimizer.normalization import NormalizationResult, normalize_offer_mapping


def offers_from_json(path: str | Path) -> list[Offer]:
    import json

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("offers file must contain a JSON array")
    return [offer_from_mapping(item) for item in raw]


def offers_from_iterable(items: Iterable[dict[str, Any]]) -> list[Offer]:
    return [offer_from_mapping(item) for item in items]


def offer_from_mapping(data: dict[str, Any]) -> Offer:
    return normalize_offer_mapping(data).require_offer()


def normalize_offer_from_mapping(data: dict[str, Any]) -> NormalizationResult:
    return normalize_offer_mapping(data)
