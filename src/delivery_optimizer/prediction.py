from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from .calibration import DeliveryRecord
from .models import MarketState, Offer


@dataclass(frozen=True)
class PredictionResult:
    offer_id: str
    platform: str
    predicted_final_payout: float
    predicted_actual_minutes: float
    predicted_actual_miles: float
    cancellation_risk: float
    zone_profitability: float
    better_offer_probability: float
    confidence: float


class SimpleStatsPredictor:
    def __init__(self, records: Iterable[DeliveryRecord] = ()) -> None:
        self.records = tuple(records)
        self._by_platform: dict[str, list[DeliveryRecord]] = defaultdict(list)
        self._by_zone: dict[str, list[DeliveryRecord]] = defaultdict(list)
        for record in self.records:
            self._by_platform[record.platform].append(record)
            if record.dropoff_zone:
                self._by_zone[record.dropoff_zone].append(record)

    def predict(self, offer: Offer, market: MarketState | None = None) -> PredictionResult:
        market = market or MarketState()
        platform_records = self._by_platform.get(offer.platform, [])
        zone_records = self._by_zone.get(offer.dropoff_zone, [])

        payout_ratio = _mean(
            [
                record.final_payout / max(record.offered_payout, 1)
                for record in platform_records
                if record.completed and record.offered_payout > 0
            ],
            1.0,
        )
        minute_ratio = _mean(
            [
                record.actual_minutes / max(record.estimated_minutes, 1)
                for record in platform_records
                if record.completed and record.estimated_minutes > 0
            ],
            1.0,
        )
        mile_ratio = _mean(
            [
                record.actual_miles / max(record.estimated_miles, 1)
                for record in platform_records
                if record.completed and record.estimated_miles > 0
            ],
            1.0,
        )
        cancellation_risk = _mean(
            [1.0 if record.canceled or not record.completed else 0.0 for record in platform_records],
            0.05,
        )
        zone_profitability = _mean(
            [
                record.final_payout / (record.actual_minutes / 60)
                for record in zone_records
                if record.completed and record.actual_minutes > 0
            ],
            market.expected_offer_profit_per_hour,
        )
        current_offer_hourly = offer.gross_payout / max(offer.estimated_minutes / 60, 0.1)
        better_offer_probability = _clamp(
            (market.expected_offer_profit_per_hour - current_offer_hourly + (market.demand_multiplier * 5)) / 40,
            0.0,
            0.95,
        )
        sample_size = len(platform_records) + len(zone_records)
        confidence = _clamp(0.35 + (sample_size / 50), 0.35, 0.95)

        total_miles = offer.pickup_miles + offer.dropoff_miles + offer.return_miles
        return PredictionResult(
            offer_id=offer.offer_id,
            platform=offer.platform,
            predicted_final_payout=round(offer.gross_payout * payout_ratio, 2),
            predicted_actual_minutes=round(offer.estimated_minutes * minute_ratio * market.traffic_multiplier, 1),
            predicted_actual_miles=round(total_miles * mile_ratio, 2),
            cancellation_risk=round(cancellation_risk, 3),
            zone_profitability=round(zone_profitability, 2),
            better_offer_probability=round(better_offer_probability, 3),
            confidence=round(confidence, 3),
        )

    def rank_zone_profitability(self) -> list[tuple[str, float]]:
        zone_scores = []
        for zone, records in self._by_zone.items():
            hourly = [
                record.final_payout / (record.actual_minutes / 60)
                for record in records
                if record.completed and record.actual_minutes > 0
            ]
            if hourly:
                zone_scores.append((zone, round(statistics.fmean(hourly), 2)))
        return sorted(zone_scores, key=lambda item: item[1], reverse=True)


def _mean(values: Iterable[float], default: float) -> float:
    values = tuple(values)
    return statistics.fmean(values) if values else default


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
