from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ScoringPolicy:
    name: str = "balanced"
    risk_penalty_weight: float = 1.0
    volatility_penalty_weight: float = 1.0
    confidence_penalty_weight: float = 1.0
    destination_penalty_weight: float = 1.0
    lateness_penalty_weight: float = 1.0
    shop_and_pay_penalty_weight: float = 1.0
    option_value_weight_multiplier: float = 1.0
    platform_wait_market_weight: float = 0.15
    weather_time_drag: float = 0.25
    weather_failure_drag: float = 0.35
    complexity_minutes_per_point: float = 2.0
    stacked_order_minutes: float = 4.0
    keep_online_pickup_miles: float = 1.5
    keep_online_pickup_minutes: float = 12.0
    same_corridor_max_pickup_miles: float = 2.0
    tight_deadline_buffer_minutes: float = 5.0

    def tuned(self, **changes: float | str) -> ScoringPolicy:
        return replace(self, **changes)


BALANCED_POLICY = ScoringPolicy()

CONSERVATIVE_POLICY = ScoringPolicy(
    name="conservative",
    risk_penalty_weight=1.25,
    volatility_penalty_weight=1.35,
    confidence_penalty_weight=1.2,
    destination_penalty_weight=1.25,
    lateness_penalty_weight=1.5,
    shop_and_pay_penalty_weight=1.25,
    option_value_weight_multiplier=1.15,
    keep_online_pickup_miles=0.8,
    keep_online_pickup_minutes=8.0,
)

AGGRESSIVE_POLICY = ScoringPolicy(
    name="aggressive",
    risk_penalty_weight=0.75,
    volatility_penalty_weight=0.75,
    confidence_penalty_weight=0.8,
    destination_penalty_weight=0.8,
    lateness_penalty_weight=0.9,
    option_value_weight_multiplier=0.75,
    keep_online_pickup_miles=2.5,
    keep_online_pickup_minutes=16.0,
)

DINNER_RUSH_POLICY = ScoringPolicy(
    name="dinner_rush",
    risk_penalty_weight=1.05,
    volatility_penalty_weight=1.1,
    destination_penalty_weight=1.35,
    option_value_weight_multiplier=1.45,
    platform_wait_market_weight=0.25,
    same_corridor_max_pickup_miles=1.25,
)

RAINY_DAY_POLICY = ScoringPolicy(
    name="rainy_day",
    risk_penalty_weight=1.35,
    volatility_penalty_weight=1.15,
    destination_penalty_weight=1.3,
    lateness_penalty_weight=1.35,
    weather_time_drag=0.45,
    weather_failure_drag=0.55,
    keep_online_pickup_miles=0.5,
)

POLICIES: dict[str, ScoringPolicy] = {
    policy.name: policy
    for policy in (
        BALANCED_POLICY,
        CONSERVATIVE_POLICY,
        AGGRESSIVE_POLICY,
        DINNER_RUSH_POLICY,
        RAINY_DAY_POLICY,
    )
}


def get_policy(name: str | None) -> ScoringPolicy:
    if not name:
        return BALANCED_POLICY
    try:
        return POLICIES[name]
    except KeyError as error:
        available = ", ".join(sorted(POLICIES))
        raise ValueError(f"unknown scoring policy {name!r}; available: {available}") from error
