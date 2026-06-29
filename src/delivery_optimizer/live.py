from __future__ import annotations

import random
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import Decision, Location, MarketState, Offer, OfferSource, Recommendation, SessionState
from .optimizer import DeliverySessionOptimizer
from .profiles import get_profile


PLATFORMS = ("doordash", "uber_eats", "grubhub")
ZONES = ("downtown", "midtown", "campus", "airport", "suburbs", "home")
RESTAURANTS = (
    "Noodle Lab",
    "Taco Station",
    "Green Bowl",
    "Burger Works",
    "Curry House",
    "Pizza Dock",
    "Sushi Point",
)


@dataclass(frozen=True)
class RandomRouteConfig:
    seed: int = 42
    offers_per_tick_min: int = 1
    offers_per_tick_max: int = 4
    tick_minutes: float = 4.0
    center_latitude: float = 34.0522
    center_longitude: float = -118.2437
    max_radius_degrees: float = 0.08


@dataclass(frozen=True)
class LiveDecisionEvent:
    tick: int
    timestamp_minutes: float
    status: str
    selected_offer_id: str | None
    selected_platform: str | None
    active_until_minute: float
    batch: tuple[Offer, ...]
    recommendation: Recommendation
    realized_profit: float = 0.0
    realized_minutes: float = 0.0
    realized_miles: float = 0.0


@dataclass(frozen=True)
class LiveRouteLabState:
    tick: int
    elapsed_minutes: float
    active_until_minute: float
    active_offer_id: str | None
    net_profit: float
    driven_miles: float
    accepted_count: int
    declined_count: int
    events: tuple[LiveDecisionEvent, ...] = field(default_factory=tuple)


class RandomRouteGenerator:
    def __init__(self, config: RandomRouteConfig | None = None) -> None:
        self.config = config or RandomRouteConfig()
        self.random = random.Random(self.config.seed)

    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.config = RandomRouteConfig(
                seed=seed,
                offers_per_tick_min=self.config.offers_per_tick_min,
                offers_per_tick_max=self.config.offers_per_tick_max,
                tick_minutes=self.config.tick_minutes,
                center_latitude=self.config.center_latitude,
                center_longitude=self.config.center_longitude,
                max_radius_degrees=self.config.max_radius_degrees,
            )
        self.random = random.Random(self.config.seed)

    def generate_batch(self, tick: int, market: MarketState) -> tuple[Offer, ...]:
        count = self.random.randint(self.config.offers_per_tick_min, self.config.offers_per_tick_max)
        return tuple(self.generate_offer(tick, index, market) for index in range(count))

    def generate_offer(self, tick: int, index: int, market: MarketState) -> Offer:
        platform = self.random.choice(PLATFORMS)
        pickup_zone = self.random.choice(ZONES)
        dropoff_zone = self.random.choice(ZONES)
        pickup_miles = round(self.random.uniform(0.2, 6.2), 1)
        dropoff_miles = round(self.random.uniform(1.0, 11.5), 1)
        return_miles = round(max(0.0, self.random.gauss(2.8, 2.2)), 1)
        traffic = max(market.traffic_multiplier, 0.7)
        estimated_minutes = round(
            (pickup_miles * 3.2 + dropoff_miles * 3.0 + self.random.uniform(5, 14)) * traffic,
            1,
        )
        demand_bonus = (market.demand_multiplier - 1) * self.random.uniform(2.0, 7.0)
        base_pay = 3.5 + (dropoff_miles * self.random.uniform(1.05, 2.1)) + demand_bonus
        tip = self.random.uniform(1.0, 10.5)
        gross_payout = round(max(4.0, base_pay + tip), 2)
        confidence = round(self.random.uniform(0.72, 0.96), 2)
        completion_probability = round(self.random.uniform(0.88, 1.0), 2)
        is_shop_and_pay = self.random.random() < 0.14
        stacked_count = 2 if self.random.random() < 0.16 else 1
        pickup_location = self._location(f"{self.random.choice(RESTAURANTS)} pickup")
        dropoff_location = self._location(f"{dropoff_zone} dropoff")
        offer_id = f"live-{tick:03d}-{index + 1}-{platform}"
        return Offer(
            platform=platform,
            offer_id=offer_id,
            gross_payout=gross_payout,
            pickup_miles=pickup_miles,
            dropoff_miles=dropoff_miles,
            estimated_minutes=estimated_minutes,
            pickup_wait_minutes=round(self.random.uniform(0, 7), 1),
            return_miles=return_miles,
            tip_estimate=round(tip * self.random.uniform(0.1, 0.45), 2),
            bonus=round(max(0.0, demand_bonus * 0.5), 2),
            completion_probability=completion_probability,
            source=OfferSource.SIMULATED,
            confidence=confidence,
            acceptance_deadline_seconds=round(self.random.uniform(8, 65), 1),
            latest_dropoff_minutes=round(estimated_minutes + self.random.uniform(-4, 14), 1),
            pickup_location=pickup_location,
            dropoff_location=dropoff_location,
            pickup_zone=pickup_zone,
            dropoff_zone=dropoff_zone,
            corridor_id=f"{pickup_zone}->{dropoff_zone}",
            distance_to_preferred_zone_miles=return_miles,
            stacked_count=stacked_count,
            order_complexity=round(self.random.uniform(0, 2.5), 1),
            is_shop_and_pay=is_shop_and_pay,
            metadata={
                "restaurant": pickup_location.label,
                "simulated": True,
                "tick": tick,
                "batch_index": index,
            },
        )

    def _location(self, label: str) -> Location:
        return Location(
            latitude=round(
                self.config.center_latitude
                + self.random.uniform(-self.config.max_radius_degrees, self.config.max_radius_degrees),
                6,
            ),
            longitude=round(
                self.config.center_longitude
                + self.random.uniform(-self.config.max_radius_degrees, self.config.max_radius_degrees),
                6,
            ),
            label=label,
        )


class LiveRouteLab:
    def __init__(self, config: RandomRouteConfig | None = None, max_events: int = 80) -> None:
        self.config = config or RandomRouteConfig()
        self.generator = RandomRouteGenerator(self.config)
        self.max_events = max_events
        self._lock = threading.RLock()
        self.reset()

    def reset(self, seed: int | None = None) -> LiveRouteLabState:
        with self._lock:
            self.generator.reset(seed)
            self.tick = 0
            self.elapsed_minutes = 0.0
            self.active_until_minute = 0.0
            self.active_offer_id: str | None = None
            self.net_profit = 0.0
            self.driven_miles = 0.0
            self.accepted_count = 0
            self.declined_count = 0
            self.events: list[LiveDecisionEvent] = []
            return self.state()

    def step(
        self,
        profile_name: str = "maximize_hourly",
        market: MarketState | None = None,
    ) -> LiveDecisionEvent:
        with self._lock:
            market = market or MarketState()
            profile = get_profile(profile_name)
            optimizer = profile.optimizer()
            self.tick += 1
            self.elapsed_minutes += self.config.tick_minutes
            batch = self.generator.generate_batch(self.tick, market)
            recommendation = optimizer.recommend(
                batch,
                state=SessionState(
                    elapsed_minutes=self.elapsed_minutes,
                    net_profit_so_far=self.net_profit,
                    active_until_minute=self.active_until_minute,
                    active_offer_id=self.active_offer_id,
                ),
                market=market,
            )

            status = "evaluated"
            realized_profit = 0.0
            realized_minutes = 0.0
            realized_miles = 0.0
            selected_offer_id = None
            selected_platform = None

            if self.elapsed_minutes < self.active_until_minute:
                status = "busy_observed"
                self.declined_count += len(batch)
            elif recommendation.selected is None:
                status = "declined_batch"
                self.declined_count += len(batch)
            else:
                selected = recommendation.selected
                status = "accepted"
                selected_offer_id = selected.offer.offer_id
                selected_platform = selected.offer.platform
                realized_minutes = selected.total_minutes
                realized_miles = selected.total_miles
                realized_profit = selected.net_profit
                self.active_offer_id = selected.offer.offer_id
                self.active_until_minute = self.elapsed_minutes + selected.total_minutes
                self.net_profit += selected.net_profit
                self.driven_miles += selected.total_miles
                self.accepted_count += 1
                self.declined_count += max(0, len(batch) - 1)

            event = LiveDecisionEvent(
                tick=self.tick,
                timestamp_minutes=round(self.elapsed_minutes, 1),
                status=status,
                selected_offer_id=selected_offer_id,
                selected_platform=selected_platform,
                active_until_minute=round(self.active_until_minute, 1),
                batch=batch,
                recommendation=recommendation,
                realized_profit=round(realized_profit, 2),
                realized_minutes=round(realized_minutes, 1),
                realized_miles=round(realized_miles, 2),
            )
            self.events.append(event)
            if len(self.events) > self.max_events:
                self.events = self.events[-self.max_events :]
            return event

    def state(self) -> LiveRouteLabState:
        with self._lock:
            return LiveRouteLabState(
                tick=self.tick,
                elapsed_minutes=round(self.elapsed_minutes, 1),
                active_until_minute=round(self.active_until_minute, 1),
                active_offer_id=self.active_offer_id,
                net_profit=round(self.net_profit, 2),
                driven_miles=round(self.driven_miles, 2),
                accepted_count=self.accepted_count,
                declined_count=self.declined_count,
                events=tuple(self.events),
            )


def event_to_dict(event: LiveDecisionEvent) -> dict[str, Any]:
    return {
        "tick": event.tick,
        "timestamp_minutes": event.timestamp_minutes,
        "status": event.status,
        "selected_offer_id": event.selected_offer_id,
        "selected_platform": event.selected_platform,
        "active_until_minute": event.active_until_minute,
        "realized_profit": event.realized_profit,
        "realized_minutes": event.realized_minutes,
        "realized_miles": event.realized_miles,
        "batch": [_offer_to_dict(offer) for offer in event.batch],
        "recommendation": {
            "selected_offer_id": (
                event.recommendation.selected.offer.offer_id
                if event.recommendation.selected
                else None
            ),
            "ranked_offers": [
                _scored_to_dict(scored) for scored in event.recommendation.ranked_offers
            ],
            "platform_actions": {
                platform: action.value
                for platform, action in event.recommendation.platform_actions.items()
            },
        },
    }


def live_state_to_dict(state: LiveRouteLabState) -> dict[str, Any]:
    return {
        "tick": state.tick,
        "elapsed_minutes": state.elapsed_minutes,
        "active_until_minute": state.active_until_minute,
        "active_offer_id": state.active_offer_id,
        "net_profit": state.net_profit,
        "driven_miles": state.driven_miles,
        "accepted_count": state.accepted_count,
        "declined_count": state.declined_count,
        "profit_per_hour": round(state.net_profit / (state.elapsed_minutes / 60), 2)
        if state.elapsed_minutes
        else 0.0,
        "events": [event_to_dict(event) for event in state.events],
    }


def _offer_to_dict(offer: Offer) -> dict[str, Any]:
    data = asdict(offer)
    data["source"] = offer.source.value
    return data


def _scored_to_dict(scored: object) -> dict[str, Any]:
    data = asdict(scored)
    data["decision"] = scored.decision.value
    data["offer"] = _offer_to_dict(scored.offer)
    return data
