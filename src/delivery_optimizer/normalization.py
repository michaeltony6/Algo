from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Location, Offer, OfferSource


@dataclass(frozen=True)
class NormalizationIssue:
    field: str
    message: str
    severity: str = "warning"


@dataclass(frozen=True)
class NormalizationResult:
    offer: Offer | None
    issues: tuple[NormalizationIssue, ...]
    source_payload: dict[str, Any]

    @property
    def is_valid(self) -> bool:
        return self.offer is not None and not any(issue.severity == "error" for issue in self.issues)

    def require_offer(self) -> Offer:
        if self.offer is None:
            messages = "; ".join(f"{issue.field}: {issue.message}" for issue in self.issues)
            raise ValueError(messages or "payload could not be normalized into an offer")
        return self.offer


def normalize_offer_mapping(payload: dict[str, Any], platform: str | None = None) -> NormalizationResult:
    data = dict(payload)
    issues: list[NormalizationIssue] = []
    if platform:
        data.setdefault("platform", platform)
    _require(data, "platform", issues)
    _require(data, "offer_id", issues)
    _require_number(data, "gross_payout", issues)
    _require_number(data, "estimated_minutes", issues)
    data.setdefault("pickup_miles", 0.0)
    data.setdefault("dropoff_miles", 0.0)
    data["source"] = OfferSource(data.get("source", OfferSource.MANUAL.value))
    if isinstance(data.get("pickup_location"), dict):
        data["pickup_location"] = Location(**data["pickup_location"])
    if isinstance(data.get("dropoff_location"), dict):
        data["dropoff_location"] = Location(**data["dropoff_location"])

    if data.get("pickup_miles", 0) == 0 and not data.get("pickup_location"):
        issues.append(NormalizationIssue("pickup_miles", "missing pickup distance or location lowers confidence"))
    if data.get("dropoff_miles", 0) == 0 and not data.get("dropoff_location"):
        issues.append(NormalizationIssue("dropoff_miles", "missing dropoff distance or location lowers confidence"))
    if "confidence" not in data:
        missing_distance = data.get("pickup_miles", 0) == 0 or data.get("dropoff_miles", 0) == 0
        data["confidence"] = 0.72 if missing_distance else 0.9

    if any(issue.severity == "error" for issue in issues):
        return NormalizationResult(offer=None, issues=tuple(issues), source_payload=payload)

    try:
        offer = Offer(**data)
    except (TypeError, ValueError) as error:
        issues.append(NormalizationIssue("payload", str(error), "error"))
        offer = None
    return NormalizationResult(offer=offer, issues=tuple(issues), source_payload=payload)


def _require(data: dict[str, Any], field: str, issues: list[NormalizationIssue]) -> None:
    if data.get(field) in (None, ""):
        issues.append(NormalizationIssue(field, "required field is missing", "error"))


def _require_number(data: dict[str, Any], field: str, issues: list[NormalizationIssue]) -> None:
    if field not in data:
        issues.append(NormalizationIssue(field, "required numeric field is missing", "error"))
        return
    if not isinstance(data[field], (int, float)):
        issues.append(NormalizationIssue(field, "must be numeric", "error"))
