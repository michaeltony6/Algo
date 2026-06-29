from __future__ import annotations

from dataclasses import dataclass, replace

from .models import DriverPreferences
from .optimizer import DeliverySessionOptimizer
from .policies import get_policy


@dataclass(frozen=True)
class DriverProfile:
    name: str
    description: str
    preferences: DriverPreferences
    policy_name: str = "balanced"

    def optimizer(self) -> DeliverySessionOptimizer:
        return DeliverySessionOptimizer(
            preferences=self.preferences,
            policy=get_policy(self.policy_name),
        )

    def tuned(self, **preference_changes: object) -> DriverProfile:
        return replace(self, preferences=replace(self.preferences, **preference_changes))


PROFILE_PRESETS: dict[str, DriverProfile] = {
    "maximize_hourly": DriverProfile(
        name="maximize_hourly",
        description="Prioritize high net hourly rate, even if mileage is a bit higher.",
        preferences=DriverPreferences(
            target_profit_per_hour=32,
            minimum_profit_per_hour=24,
            minimum_net_profit=5,
            wait_option_value_weight=0.45,
            risk_tolerance=0.45,
        ),
        policy_name="dinner_rush",
    ),
    "minimize_miles": DriverProfile(
        name="minimize_miles",
        description="Protect the car: stricter mileage, pickup distance, and deadhead limits.",
        preferences=DriverPreferences(
            vehicle_cost_per_mile=0.6,
            target_profit_per_hour=24,
            minimum_profit_per_hour=18,
            max_total_miles=12,
            max_pickup_miles=3,
            max_deadhead_ratio=0.45,
            return_to_zone_weight=0.75,
        ),
        policy_name="conservative",
    ),
    "stay_near_home": DriverProfile(
        name="stay_near_home",
        description="Penalize deliveries that end far from preferred zones.",
        preferences=DriverPreferences(
            target_profit_per_hour=25,
            minimum_profit_per_hour=18,
            return_to_zone_weight=1.0,
            destination_penalty_per_mile=0.9,
            preferred_zones=("home", "downtown"),
        ),
        policy_name="balanced",
    ),
    "avoid_shopping": DriverProfile(
        name="avoid_shopping",
        description="Avoid shop-and-pay and complex orders unless the payout is excellent.",
        preferences=DriverPreferences(
            target_profit_per_hour=26,
            minimum_profit_per_hour=20,
            shop_and_pay_penalty=5.0,
            risk_tolerance=0.3,
        ),
        policy_name="conservative",
    ),
    "aggressive": DriverProfile(
        name="aggressive",
        description="Accept more upside and uncertainty during strong demand.",
        preferences=DriverPreferences(
            target_profit_per_hour=28,
            minimum_profit_per_hour=18,
            risk_tolerance=0.7,
            payout_volatility_weight=0.3,
            wait_option_value_weight=0.25,
        ),
        policy_name="aggressive",
    ),
}


def get_profile(name: str) -> DriverProfile:
    try:
        return PROFILE_PRESETS[name]
    except KeyError as error:
        available = ", ".join(sorted(PROFILE_PRESETS))
        raise ValueError(f"unknown driver profile {name!r}; available: {available}") from error
