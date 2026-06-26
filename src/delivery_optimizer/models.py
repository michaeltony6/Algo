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
    KEEP_UNTIL_PICKUP = "keep_until_pickup"
    ACCEPT_SAME_CORRIDOR_ONLY = "accept_same_corridor_only"
    PAUSE_AFTER_PICKUP = "pause_after_pickup"
    PAUSE_WHILE_ACTIVE = "pause_while_active"
    DECLINE_CONFLICTING = "decline_conflicting"


class OfferSource(str, Enum):
    MANUAL = "manual"
    API = "api"
    WEBHOOK = "webhook"
    SIMULATED = "simulated"


def _validate_non_negative(name: str, value: float) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _validate_probability(name: str, value: float) -> None:
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float
    label: str = ""

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")


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
    max_deadhead_ratio: float = 0.65
    wait_option_value_weight: float = 0.35
    payout_volatility_weight: float = 0.5
    destination_penalty_per_mile: float = 0.2
    lateness_penalty_per_minute: float = 0.4
    shop_and_pay_penalty: float = 1.5
    preferred_zones: tuple[str, ...] = ()

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
            "wait_option_value_weight",
            "payout_volatility_weight",
            "destination_penalty_per_mile",
            "lateness_penalty_per_minute",
            "shop_and_pay_penalty",
        ):
            _validate_non_negative(name, float(getattr(self, name)))
        _validate_probability("risk_tolerance", self.risk_tolerance)
        _validate_probability("max_deadhead_ratio", self.max_deadhead_ratio)


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    reliability: float = 0.95
    cancellation_risk: float = 0.03
    wait_time_buffer_minutes: float = 3.0
    offer_arrival_rate_per_hour: float = 4.0
    payout_volatility: float = 0.08
    tip_transparency: float = 0.75
    dispatch_confidence: float = 0.9

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("platform profile name is required")
        _validate_probability("reliability", self.reliability)
        _validate_probability("cancellation_risk", self.cancellation_risk)
        _validate_probability("payout_volatility", self.payout_volatility)
        _validate_probability("tip_transparency", self.tip_transparency)
        _validate_probability("dispatch_confidence", self.dispatch_confidence)
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
    source: OfferSource = OfferSource.MANUAL
    confidence: float = 0.9
    acceptance_deadline_seconds: float | None = None
    latest_dropoff_minutes: float | None = None
    pickup_location: Location | None = None
    dropoff_location: Location | None = None
    pickup_zone: str = ""
    dropoff_zone: str = ""
    corridor_id: str = ""
    distance_to_preferred_zone_miles: float = 0.0
    stacked_count: int = 1
    order_complexity: float = 0.0
    is_shop_and_pay: bool = False
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
            "distance_to_preferred_zone_miles",
            "order_complexity",
        ):
            _validate_non_negative(name, float(getattr(self, name)))
        if self.estimated_minutes == 0:
            raise ValueError("estimated_minutes must be greater than zero")
        _validate_probability("completion_probability", self.completion_probability)
        _validate_probability("confidence", self.confidence)
        if self.acceptance_deadline_seconds is not None:
            _validate_non_negative("acceptance_deadline_seconds", self.acceptance_deadline_seconds)
        if self.latest_dropoff_minutes is not None:
            _validate_non_negative("latest_dropoff_minutes", self.latest_dropoff_minutes)
        if self.stacked_count < 1:
            raise ValueError("stacked_count must be at least 1")


@dataclass(frozen=True)
class SessionState:
    elapsed_minutes: float = 0.0
    net_profit_so_far: float = 0.0
    goal_minutes: float = 240.0
    active_offer_id: str | None = None
    active_until_minute: float = 0.0
    current_zone: str = ""

    def __post_init__(self) -> None:
        _validate_non_negative("elapsed_minutes", self.elapsed_minutes)
        _validate_non_negative("goal_minutes", self.goal_minutes)
        _validate_non_negative("active_until_minute", self.active_until_minute)


@dataclass(frozen=True)
class MarketState:
    demand_multiplier: float = 1.0
    traffic_multiplier: float = 1.0
    weather_risk: float = 0.0
    courier_saturation: float = 1.0
    estimated_wait_minutes: float = 8.0
    expected_offer_profit_per_hour: float = 22.0
    platform_expected_profit_per_hour: Mapping[str, float] = field(default_factory=dict)
    platform_wait_minutes: Mapping[str, float] = field(default_factory=dict)
    zone_heat: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "demand_multiplier",
            "traffic_multiplier",
            "courier_saturation",
            "estimated_wait_minutes",
            "expected_offer_profit_per_hour",
        ):
            _validate_non_negative(name, float(getattr(self, name)))
        _validate_probability("weather_risk", self.weather_risk)
        for platform, value in self.platform_expected_profit_per_hour.items():
            _validate_non_negative(f"platform_expected_profit_per_hour[{platform}]", value)
        for platform, value in self.platform_wait_minutes.items():
            _validate_non_negative(f"platform_wait_minutes[{platform}]", value)
        for zone, value in self.zone_heat.items():
            _validate_non_negative(f"zone_heat[{zone}]", value)


@dataclass(frozen=True)
class ScoredOffer:
    offer: Offer
    decision: Decision
    policy_name: str
    expected_revenue: float
    operating_cost: float
    risk_penalty: float
    opportunity_cost: float
    net_profit: float
    profit_per_hour: float
    total_miles: float
    total_minutes: float
    option_value: float
    destination_penalty: float
    lateness_penalty: float
    volatility_penalty: float
    confidence_penalty: float
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
