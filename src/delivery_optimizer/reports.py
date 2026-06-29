from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .models import MarketState, Offer
from .optimizer import DeliverySessionOptimizer
from .prediction import PredictionResult, SimpleStatsPredictor
from .simulation import (
    BacktestSimulator,
    DecisionStrategy,
    DollarsPerMileStrategy,
    HourlyThresholdStrategy,
    OfferEvent,
    OptimizerStrategy,
    StrategyRun,
)


@dataclass(frozen=True)
class HindsightResult:
    accepted_offer_ids: tuple[str, ...]
    max_profit: float
    active_minutes: float
    profit_per_hour: float


@dataclass(frozen=True)
class ShiftReport:
    strategy_runs: tuple[StrategyRun, ...]
    hindsight: HindsightResult
    predictions: tuple[PredictionResult, ...]
    best_strategy_name: str
    optimizer_lift_vs_baseline: float

    def to_dict(self) -> dict:
        return {
            "strategy_runs": [asdict(run) for run in self.strategy_runs],
            "hindsight": asdict(self.hindsight),
            "predictions": [asdict(prediction) for prediction in self.predictions],
            "best_strategy_name": self.best_strategy_name,
            "optimizer_lift_vs_baseline": self.optimizer_lift_vs_baseline,
        }


def build_shift_report(
    events: Iterable[OfferEvent],
    optimizer: DeliverySessionOptimizer,
    predictor: SimpleStatsPredictor | None = None,
    strategies: Iterable[DecisionStrategy] | None = None,
) -> ShiftReport:
    events = tuple(sorted(events, key=lambda item: item.timestamp_minutes))
    strategies = tuple(
        strategies
        or (
            OptimizerStrategy(),
            DollarsPerMileStrategy(minimum=2.0),
            HourlyThresholdStrategy(minimum_hourly=25),
        )
    )
    runs = BacktestSimulator(optimizer).compare(events, strategies)
    best_run = max(runs, key=lambda run: run.gross_profit) if runs else None
    optimizer_run = next((run for run in runs if run.strategy_name == "optimizer"), None)
    baseline_runs = [run for run in runs if run.strategy_name != "optimizer"]
    best_baseline_profit = max((run.gross_profit for run in baseline_runs), default=0.0)
    predictor = predictor or SimpleStatsPredictor()
    predictions = tuple(predictor.predict(event.offer, event.market) for event in events)
    hindsight = best_hindsight(events, optimizer)
    return ShiftReport(
        strategy_runs=runs,
        hindsight=hindsight,
        predictions=predictions,
        best_strategy_name=best_run.strategy_name if best_run else "",
        optimizer_lift_vs_baseline=round(
            (optimizer_run.gross_profit if optimizer_run else 0.0) - best_baseline_profit,
            2,
        ),
    )


def events_from_offers(offers: Iterable[Offer], market: MarketState | None = None) -> list[OfferEvent]:
    market = market or MarketState()
    return [
        OfferEvent(timestamp_minutes=index * 18, offer=offer, market=market)
        for index, offer in enumerate(offers)
    ]


def best_hindsight(
    events: Iterable[OfferEvent],
    optimizer: DeliverySessionOptimizer,
) -> HindsightResult:
    event_values: list[tuple[float, float, float, str]] = []
    for event in sorted(events, key=lambda item: item.timestamp_minutes):
        recommendation = optimizer.recommend([event.offer], market=event.market)
        scored = recommendation.ranked_offers[0]
        minutes = event.actual_minutes or scored.total_minutes
        payout = event.actual_payout if event.actual_payout is not None else max(scored.net_profit, 0)
        start = event.timestamp_minutes
        end = start + minutes
        if payout > 0 and minutes > 0:
            event_values.append((start, end, payout, event.offer.offer_id))

    if not event_values:
        return HindsightResult(accepted_offer_ids=(), max_profit=0.0, active_minutes=0.0, profit_per_hour=0.0)

    event_values.sort(key=lambda item: item[1])
    previous = [_last_non_overlapping(event_values, index) for index in range(len(event_values))]
    best = [0.0] * (len(event_values) + 1)
    selected: list[list[str]] = [[] for _ in range(len(event_values) + 1)]
    minutes_by_index = [0.0] * (len(event_values) + 1)

    for index, (_, _, profit, offer_id) in enumerate(event_values, start=1):
        take_profit = profit + best[previous[index - 1] + 1]
        skip_profit = best[index - 1]
        if take_profit > skip_profit:
            best[index] = take_profit
            selected[index] = selected[previous[index - 1] + 1] + [offer_id]
            minutes_by_index[index] = minutes_by_index[previous[index - 1] + 1] + (
                event_values[index - 1][1] - event_values[index - 1][0]
            )
        else:
            best[index] = skip_profit
            selected[index] = selected[index - 1]
            minutes_by_index[index] = minutes_by_index[index - 1]

    active_minutes = minutes_by_index[-1]
    return HindsightResult(
        accepted_offer_ids=tuple(selected[-1]),
        max_profit=round(best[-1], 2),
        active_minutes=round(active_minutes, 1),
        profit_per_hour=round(best[-1] / (active_minutes / 60), 2) if active_minutes else 0.0,
    )


def _last_non_overlapping(events: list[tuple[float, float, float, str]], index: int) -> int:
    start = events[index][0]
    for candidate in range(index - 1, -1, -1):
        if events[candidate][1] <= start:
            return candidate
    return -1
