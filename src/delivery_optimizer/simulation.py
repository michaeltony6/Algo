from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Protocol

from .models import Decision, MarketState, Offer, PlatformAction, Recommendation, SessionState
from .optimizer import DeliverySessionOptimizer


@dataclass(frozen=True)
class OfferEvent:
    timestamp_minutes: float
    offer: Offer
    market: MarketState = field(default_factory=MarketState)
    actual_payout: float | None = None
    actual_minutes: float | None = None
    actual_miles: float | None = None


@dataclass(frozen=True)
class StrategyRun:
    strategy_name: str
    accepted_count: int
    declined_count: int
    gross_profit: float
    active_minutes: float
    driven_miles: float
    profit_per_hour: float
    recommendations: tuple[Recommendation, ...]


class DecisionStrategy(Protocol):
    name: str

    def recommend(
        self,
        offer: Offer,
        state: SessionState,
        market: MarketState,
        optimizer: DeliverySessionOptimizer,
    ) -> Recommendation:
        ...


class OptimizerStrategy:
    name = "optimizer"

    def recommend(
        self,
        offer: Offer,
        state: SessionState,
        market: MarketState,
        optimizer: DeliverySessionOptimizer,
    ) -> Recommendation:
        return optimizer.recommend([offer], state, market)


class DollarsPerMileStrategy:
    def __init__(self, minimum: float = 2.0) -> None:
        self.minimum = minimum
        self.name = f"dollars_per_mile_{minimum:g}"

    def recommend(
        self,
        offer: Offer,
        state: SessionState,
        market: MarketState,
        optimizer: DeliverySessionOptimizer,
    ) -> Recommendation:
        recommendation = optimizer.recommend([offer], state, market)
        scored = recommendation.ranked_offers[0]
        total_miles = max(scored.total_miles, 0.1)
        if offer.gross_payout / total_miles < self.minimum:
            scored = replace(
                scored,
                decision=Decision.DECLINE,
                reasons=("below dollars-per-mile threshold",),
            )
            return Recommendation(selected=None, ranked_offers=(scored,), platform_actions=recommendation.platform_actions)
        scored = replace(scored, decision=Decision.ACCEPT, reasons=())
        return Recommendation(
            selected=scored,
            ranked_offers=(scored,),
            platform_actions={offer.platform: PlatformAction.ACCEPT_SELECTED},
        )


class HourlyThresholdStrategy:
    def __init__(self, minimum_hourly: float = 25.0) -> None:
        self.minimum_hourly = minimum_hourly
        self.name = f"hourly_threshold_{minimum_hourly:g}"

    def recommend(
        self,
        offer: Offer,
        state: SessionState,
        market: MarketState,
        optimizer: DeliverySessionOptimizer,
    ) -> Recommendation:
        recommendation = optimizer.recommend([offer], state, market)
        scored = recommendation.ranked_offers[0]
        if scored.profit_per_hour < self.minimum_hourly:
            scored = replace(
                scored,
                decision=Decision.DECLINE,
                reasons=("below hourly threshold",),
            )
            return Recommendation(selected=None, ranked_offers=(scored,), platform_actions=recommendation.platform_actions)
        scored = replace(scored, decision=Decision.ACCEPT, reasons=())
        return Recommendation(
            selected=scored,
            ranked_offers=(scored,),
            platform_actions={offer.platform: PlatformAction.ACCEPT_SELECTED},
        )


class BacktestSimulator:
    def __init__(self, optimizer: DeliverySessionOptimizer) -> None:
        self.optimizer = optimizer

    def run(self, events: Iterable[OfferEvent], strategy: DecisionStrategy) -> StrategyRun:
        state = SessionState()
        accepted = 0
        declined = 0
        gross_profit = 0.0
        active_minutes = 0.0
        driven_miles = 0.0
        recommendations: list[Recommendation] = []

        for event in sorted(events, key=lambda item: item.timestamp_minutes):
            if event.timestamp_minutes < state.active_until_minute:
                declined += 1
                continue
            state = SessionState(
                elapsed_minutes=event.timestamp_minutes,
                net_profit_so_far=gross_profit,
                goal_minutes=state.goal_minutes,
            )
            recommendation = strategy.recommend(event.offer, state, event.market, self.optimizer)
            recommendations.append(recommendation)
            if recommendation.selected is None:
                declined += 1
                continue
            selected = recommendation.selected
            accepted += 1
            minutes = event.actual_minutes or selected.total_minutes
            payout = event.actual_payout if event.actual_payout is not None else selected.net_profit
            miles = event.actual_miles if event.actual_miles is not None else selected.total_miles
            gross_profit += payout
            active_minutes += minutes
            driven_miles += miles
            state = SessionState(
                elapsed_minutes=event.timestamp_minutes,
                net_profit_so_far=gross_profit,
                goal_minutes=state.goal_minutes,
                active_offer_id=selected.offer.offer_id,
                active_until_minute=event.timestamp_minutes + minutes,
                current_zone=selected.offer.dropoff_zone,
            )

        profit_per_hour = gross_profit / (active_minutes / 60) if active_minutes else 0.0
        return StrategyRun(
            strategy_name=strategy.name,
            accepted_count=accepted,
            declined_count=declined,
            gross_profit=round(gross_profit, 2),
            active_minutes=round(active_minutes, 1),
            driven_miles=round(driven_miles, 2),
            profit_per_hour=round(profit_per_hour, 2),
            recommendations=tuple(recommendations),
        )

    def compare(self, events: Iterable[OfferEvent], strategies: Iterable[DecisionStrategy]) -> tuple[StrategyRun, ...]:
        events = tuple(events)
        return tuple(self.run(events, strategy) for strategy in strategies)
