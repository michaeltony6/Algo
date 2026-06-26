from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from enum import Enum
from typing import Any

from .integrations.manual import offers_from_json
from .models import DriverPreferences, MarketState, SessionState
from .optimizer import DeliverySessionOptimizer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rank delivery offers by expected net profit.")
    parser.add_argument("--offers", required=True, help="Path to a JSON array of offers.")
    parser.add_argument("--target-hourly", type=float, default=25.0)
    parser.add_argument("--minimum-hourly", type=float, default=18.0)
    parser.add_argument("--minimum-net", type=float, default=4.0)
    parser.add_argument("--vehicle-cost", type=float, default=0.45)
    parser.add_argument("--elapsed-minutes", type=float, default=0.0)
    parser.add_argument("--net-profit-so-far", type=float, default=0.0)
    parser.add_argument("--goal-minutes", type=float, default=240.0)
    parser.add_argument("--demand-multiplier", type=float, default=1.0)
    parser.add_argument("--traffic-multiplier", type=float, default=1.0)
    parser.add_argument("--weather-risk", type=float, default=0.0)
    parser.add_argument("--courier-saturation", type=float, default=1.0)
    parser.add_argument("--expected-offer-hourly", type=float, default=22.0)
    args = parser.parse_args(argv)

    offers = offers_from_json(args.offers)
    preferences = DriverPreferences(
        vehicle_cost_per_mile=args.vehicle_cost,
        target_profit_per_hour=args.target_hourly,
        minimum_profit_per_hour=args.minimum_hourly,
        minimum_net_profit=args.minimum_net,
    )
    state = SessionState(
        elapsed_minutes=args.elapsed_minutes,
        net_profit_so_far=args.net_profit_so_far,
        goal_minutes=args.goal_minutes,
    )
    market = MarketState(
        demand_multiplier=args.demand_multiplier,
        traffic_multiplier=args.traffic_multiplier,
        weather_risk=args.weather_risk,
        courier_saturation=args.courier_saturation,
        expected_offer_profit_per_hour=args.expected_offer_hourly,
    )
    recommendation = DeliverySessionOptimizer(preferences).recommend(offers, state, market)
    print(json.dumps(_recommendation_to_dict(recommendation), indent=2))
    return 0


def _recommendation_to_dict(recommendation: Any) -> dict[str, Any]:
    return {
        "selected_offer_id": (
            recommendation.selected.offer.offer_id if recommendation.selected else None
        ),
        "selected_platform": (
            recommendation.selected.offer.platform if recommendation.selected else None
        ),
        "platform_actions": {
            platform: action.value for platform, action in recommendation.platform_actions.items()
        },
        "ranked_offers": [_scored_offer_to_dict(offer) for offer in recommendation.ranked_offers],
    }


def _scored_offer_to_dict(scored_offer: Any) -> dict[str, Any]:
    data = asdict(scored_offer)
    data["decision"] = scored_offer.decision.value
    data["offer"]["metadata"] = dict(scored_offer.offer.metadata)
    return _json_safe(data)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value
