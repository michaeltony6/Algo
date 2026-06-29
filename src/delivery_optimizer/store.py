from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .calibration import DeliveryRecord, records_from_json
from .models import MarketState, Offer, ScoredOffer
from .normalization import normalize_offer_mapping


SCHEMA_VERSION = 1


class OptimizerStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.initialize()

    def close(self) -> None:
        self.connection.close()

    def initialize(self) -> None:
        with self._lock:
            self.connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS offers (
                    offer_id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    offer_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    policy_name TEXT NOT NULL,
                    value_margin REAL NOT NULL,
                    profit_per_hour REAL NOT NULL,
                    reasons_json TEXT NOT NULL,
                    scored_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (offer_id) REFERENCES offers (offer_id)
                );
                CREATE TABLE IF NOT EXISTS completed_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    offered_payout REAL NOT NULL,
                    final_payout REAL NOT NULL,
                    estimated_minutes REAL NOT NULL,
                    actual_minutes REAL NOT NULL,
                    estimated_miles REAL NOT NULL,
                    actual_miles REAL NOT NULL,
                    accepted INTEGER NOT NULL,
                    completed INTEGER NOT NULL,
                    canceled INTEGER NOT NULL,
                    timestamp_minutes REAL,
                    pickup_wait_minutes REAL NOT NULL,
                    dropoff_zone TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS strategy_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT NOT NULL,
                    gross_profit REAL NOT NULL,
                    profit_per_hour REAL NOT NULL,
                    accepted_count INTEGER NOT NULL,
                    declined_count INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self.connection.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            self.connection.commit()

    def record_offer(self, offer: Offer) -> None:
        with self._lock:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO offers (offer_id, platform, payload_json)
                VALUES (?, ?, ?)
                """,
                (offer.offer_id, offer.platform, _json(asdict(offer))),
            )
            self.connection.commit()

    def record_offers(self, offers: Iterable[Offer]) -> None:
        for offer in offers:
            self.record_offer(offer)

    def record_decision(self, scored_offer: ScoredOffer) -> None:
        with self._lock:
            self.record_offer(scored_offer.offer)
            self.connection.execute(
                """
                INSERT INTO decisions (
                    offer_id, decision, policy_name, value_margin, profit_per_hour,
                    reasons_json, scored_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scored_offer.offer.offer_id,
                    scored_offer.decision.value,
                    scored_offer.policy_name,
                    scored_offer.value_margin,
                    scored_offer.profit_per_hour,
                    _json(scored_offer.reasons),
                    _json(asdict(scored_offer)),
                ),
            )
            self.connection.commit()

    def record_delivery(self, record: DeliveryRecord) -> None:
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO completed_deliveries (
                    platform, offered_payout, final_payout, estimated_minutes,
                    actual_minutes, estimated_miles, actual_miles, accepted,
                    completed, canceled, timestamp_minutes, pickup_wait_minutes,
                    dropoff_zone, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.platform,
                    record.offered_payout,
                    record.final_payout,
                    record.estimated_minutes,
                    record.actual_minutes,
                    record.estimated_miles,
                    record.actual_miles,
                    int(record.accepted),
                    int(record.completed),
                    int(record.canceled),
                    record.timestamp_minutes,
                    record.pickup_wait_minutes,
                    record.dropoff_zone,
                    _json(asdict(record)),
                ),
            )
            self.connection.commit()

    def import_history_json(self, path: str | Path) -> int:
        records = records_from_json(path)
        for record in records:
            self.record_delivery(record)
        return len(records)

    def list_offers(self) -> list[Offer]:
        with self._lock:
            rows = self.connection.execute("SELECT payload_json FROM offers ORDER BY created_at").fetchall()
        offers: list[Offer] = []
        for row in rows:
            result = normalize_offer_mapping(json.loads(row["payload_json"]))
            if result.offer:
                offers.append(result.offer)
        return offers

    def list_delivery_records(self) -> list[DeliveryRecord]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT payload_json FROM completed_deliveries ORDER BY id"
            ).fetchall()
        return [DeliveryRecord.from_mapping(json.loads(row["payload_json"])) for row in rows]

    def record_market_snapshot(self, label: str, market: MarketState) -> None:
        with self._lock:
            self.connection.execute(
                "INSERT INTO market_snapshots (label, payload_json) VALUES (?, ?)",
                (label, _json(asdict(market))),
            )
            self.connection.commit()

    def record_strategy_run(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO strategy_runs (
                    strategy_name, gross_profit, profit_per_hour,
                    accepted_count, declined_count, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["strategy_name"],
                    payload["gross_profit"],
                    payload["profit_per_hour"],
                    payload["accepted_count"],
                    payload["declined_count"],
                    _json(payload),
                ),
            )
            self.connection.commit()

    def summary(self) -> dict[str, Any]:
        with self._lock:
            offer_count = self.connection.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
            decision_count = self.connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
            delivery_count = self.connection.execute("SELECT COUNT(*) FROM completed_deliveries").fetchone()[0]
            total_profit = self.connection.execute(
                "SELECT COALESCE(SUM(final_payout), 0) FROM completed_deliveries WHERE completed = 1"
            ).fetchone()[0]
            total_minutes = self.connection.execute(
                "SELECT COALESCE(SUM(actual_minutes), 0) FROM completed_deliveries WHERE completed = 1"
            ).fetchone()[0]
        return {
            "path": str(self.path),
            "schema_version": SCHEMA_VERSION,
            "offer_count": offer_count,
            "decision_count": decision_count,
            "delivery_count": delivery_count,
            "completed_profit": round(float(total_profit), 2),
            "completed_hours": round(float(total_minutes) / 60, 2) if total_minutes else 0,
        }


def _json(value: Any) -> str:
    return json.dumps(value, default=_json_default, sort_keys=True)


def _json_default(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)
