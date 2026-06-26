from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import MarketState, PlatformProfile
from .optimizer import DEFAULT_PLATFORM_PROFILES
from .policies import ScoringPolicy


@dataclass(frozen=True)
class DeliveryRecord:
    platform: str
    offered_payout: float
    final_payout: float
    estimated_minutes: float
    actual_minutes: float
    estimated_miles: float
    actual_miles: float
    accepted: bool = True
    completed: bool = True
    canceled: bool = False
    timestamp_minutes: float | None = None
    pickup_wait_minutes: float = 0.0
    dropoff_zone: str = ""

    @staticmethod
    def from_mapping(payload: dict[str, Any]) -> DeliveryRecord:
        return DeliveryRecord(
            platform=str(payload["platform"]),
            offered_payout=float(payload.get("offered_payout", payload.get("gross_payout", 0))),
            final_payout=float(payload.get("final_payout", payload.get("actual_payout", 0))),
            estimated_minutes=float(payload.get("estimated_minutes", 0)),
            actual_minutes=float(payload.get("actual_minutes", payload.get("estimated_minutes", 0))),
            estimated_miles=float(payload.get("estimated_miles", payload.get("total_miles", 0))),
            actual_miles=float(payload.get("actual_miles", payload.get("estimated_miles", 0))),
            accepted=bool(payload.get("accepted", True)),
            completed=bool(payload.get("completed", True)),
            canceled=bool(payload.get("canceled", False)),
            timestamp_minutes=(
                float(payload["timestamp_minutes"])
                if payload.get("timestamp_minutes") is not None
                else None
            ),
            pickup_wait_minutes=float(payload.get("pickup_wait_minutes", 0)),
            dropoff_zone=str(payload.get("dropoff_zone", "")),
        )


@dataclass(frozen=True)
class CalibrationReport:
    platform_profiles: dict[str, PlatformProfile]
    market_state: MarketState
    suggested_policy: ScoringPolicy
    sample_size: int
    notes: tuple[str, ...]


def records_from_json(path: str | Path) -> list[DeliveryRecord]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("history file must contain a JSON array")
    return [DeliveryRecord.from_mapping(item) for item in raw]


def calibrate(
    records: Iterable[DeliveryRecord],
    base_profiles: dict[str, PlatformProfile] | None = None,
    base_policy: ScoringPolicy | None = None,
) -> CalibrationReport:
    records = tuple(records)
    base_profiles = base_profiles or DEFAULT_PLATFORM_PROFILES
    base_policy = base_policy or ScoringPolicy()
    by_platform: dict[str, list[DeliveryRecord]] = defaultdict(list)
    completed_records: list[DeliveryRecord] = []
    for record in records:
        by_platform[record.platform].append(record)
        if record.accepted and record.completed and record.actual_minutes > 0:
            completed_records.append(record)

    profiles: dict[str, PlatformProfile] = {}
    notes: list[str] = []
    for platform, platform_records in by_platform.items():
        base = base_profiles.get(platform, PlatformProfile(name=platform))
        accepted = [record for record in platform_records if record.accepted]
        completed = [record for record in accepted if record.completed and not record.canceled]
        canceled = [record for record in accepted if record.canceled or not record.completed]
        payout_errors = [
            abs(record.final_payout - record.offered_payout) / max(record.offered_payout, 1)
            for record in completed
        ]
        wait_errors = [
            max(0.0, record.actual_minutes - record.estimated_minutes)
            for record in completed
        ]
        platform_hours = _observed_hours(platform_records)
        profiles[platform] = PlatformProfile(
            name=platform,
            reliability=_clamp(len(completed) / max(len(accepted), 1), 0.5, 0.995),
            cancellation_risk=_clamp(len(canceled) / max(len(accepted), 1), 0.0, 0.5),
            wait_time_buffer_minutes=_mean(wait_errors, base.wait_time_buffer_minutes),
            offer_arrival_rate_per_hour=(
                len(platform_records) / platform_hours if platform_hours else base.offer_arrival_rate_per_hour
            ),
            payout_volatility=_clamp(_mean(payout_errors, base.payout_volatility), 0.0, 0.6),
            tip_transparency=_clamp(1 - _mean(payout_errors, 1 - base.tip_transparency), 0.2, 1.0),
            dispatch_confidence=_clamp(len(completed) / max(len(accepted), 1), 0.5, 0.99),
        )
        if len(platform_records) < 10:
            notes.append(f"{platform}: calibration sample is small ({len(platform_records)} records)")

    hourly = [
        record.final_payout / (record.actual_minutes / 60)
        for record in completed_records
        if record.actual_minutes > 0
    ]
    wait_minutes = [
        max(0.0, record.actual_minutes - record.estimated_minutes)
        for record in completed_records
    ]
    market_state = MarketState(
        estimated_wait_minutes=_mean(wait_minutes, 8.0),
        expected_offer_profit_per_hour=_mean(hourly, 22.0),
        platform_expected_profit_per_hour={
            platform: _mean(
                [
                    record.final_payout / (record.actual_minutes / 60)
                    for record in platform_records
                    if record.completed and record.actual_minutes > 0
                ],
                22.0,
            )
            for platform, platform_records in by_platform.items()
        },
    )

    average_volatility = _mean(
        [profile.payout_volatility for profile in profiles.values()],
        0.08,
    )
    average_wait_error = _mean(wait_minutes, 0.0)
    suggested_policy = base_policy.tuned(
        name="calibrated",
        volatility_penalty_weight=_clamp(1 + average_volatility, 0.75, 1.75),
        platform_wait_market_weight=_clamp(0.15 + (average_wait_error / 120), 0.05, 0.4),
    )

    return CalibrationReport(
        platform_profiles=profiles,
        market_state=market_state,
        suggested_policy=suggested_policy,
        sample_size=len(records),
        notes=tuple(notes),
    )


def _mean(values: Iterable[float], default: float) -> float:
    values = tuple(values)
    return statistics.fmean(values) if values else default


def _observed_hours(records: list[DeliveryRecord]) -> float:
    timestamps = sorted(record.timestamp_minutes for record in records if record.timestamp_minutes is not None)
    if len(timestamps) < 2:
        return 0.0
    return max((timestamps[-1] - timestamps[0]) / 60, 0.1)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
