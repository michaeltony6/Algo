from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class Decision(str, Enum):
    ACCEPT = "accept"
    DECLINE = "decline"


class PlatformAction(str, Enum):
    ACCEPT_SELECTED = "accept_selected"
    KEEP_ONLINE = "keep_online"
    PAUSE_WHILE_ACTIVE = "pause_while_active"


def _validate_non_negative(name: str, value: float) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _validate_probability(name: str, value: float) -> None:
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class DriverPreferences:
    vehicle_cost_per_mile: float = 0.45
    target_profit_per_hour: float = 25.0
    minimum_profit_per_hour: float = 18.0
    minimum_net_profit: float = 4.0
    max_offer_minutes: float = 60.0
    max_total_miles: float = 20.0
    max_pickup_miles: float = 6.0
    return_to_zone_weight: float = 0.5
    risk_tolerance: float = 0.4

    def __post_init__(self) -> None:
        for name in (
            "vehicle_cost_per_mile",
            "target_profit_per_hour",
            "minimum_profit_per_hour",
            "minimum_net_profit",
            "max_offer_minutes",
            "max_total_miles",
            "max_pickup_miles",
            "return_to_zone_weight",
        ):
            _validate_non_negative(name, float(getattr(self, name)))
        _validate_probability("risk_tolerance", self.risk_tolerance)


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    reliability: float = 0.95
    cancellation_risk: float = 0.03
    wait_time_buffer_minutes: float = 3.0
    offer_arrival_rate_per_hour: float = 4.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("platform profile name is required")
        _validate_probability("reliability", self.reliability)
        _validate_probability("cancellation_risk", self.cancellation_risk)
        _validate_non_negative("wait_time_buffer_minutes", self.wait_time_buffer_minutes)
        _validate_non_negative("offer_arrival_rate_per_hour", self.offer_arrival_rate_per_hour)


@dataclass(frozen=True)
class Offer:
    platform: str
    offer_id: str
    gross_payout: float
    pickup_miles: float
    dropoff_miles: float
    estimated_minutes: float
    pickup_wait_minutes: float = 0.0
    return_miles: float = 0.0
    tip_estimate: float = 0.0
    bonus: float = 0.0
    tolls: float = 0.0
    parking: float = 0.0
    completion_probability: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.platform:
            raise ValueError("offer platform is required")
        if not self.offer_id:
            raise ValueError("offer_id is required")
        for name in (
            "gross_payout",
            "pickup_miles",
            "dropoff_miles",
            "estimated_minutes",
            "pickup_wait_minutes",
            "return_miles",
            "tip_estimate",
            "bonus",
            "tolls",
            "parking",
        ):
            _validate_non_negative(name, float(getattr(self, name)))
        if self.estimated_minutes == 0:
            raise ValueError("estimated_minutes must be greater than zero")
        _validate_probability("completion_probability", self.completion_probability)


@dataclass(frozen=True)
class SessionState:
    elapsed_minutes: float = 0.0
    net_profit_so_far: float = 0.0
    goal_minutes: float = 240.0

    def __post_init__(self) -> None:
        _validate_non_negative("elapsed_minutes", self.elapsed_minutes)
        _validate_non_negative("goal_minutes", self.goal_minutes)


@dataclass(frozen=True)
class ScoredOffer:
    offer: Offer
    decision: Decision
    expected_revenue: float
    operating_cost: float
    risk_penalty: float
    opportunity_cost: float
    net_profit: float
    profit_per_hour: float
    total_miles: float
    total_minutes: float
    value_margin: float
    reasons: tuple[str, ...]

    @property
    def score(self) -> float:
        return self.value_margin


@dataclass(frozen=True)
class Recommendation:
    selected: ScoredOffer | None
    ranked_offers: tuple[ScoredOffer, ...]
    platform_actions: Mapping[str, PlatformAction]
