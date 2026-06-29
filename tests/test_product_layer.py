import tempfile
import unittest
from pathlib import Path

from delivery_optimizer import DeliverySessionOptimizer, DriverPreferences, MarketState, Offer
from delivery_optimizer.calibration import DeliveryRecord
from delivery_optimizer.dashboard import DashboardApp, seed_demo_data
from delivery_optimizer.prediction import SimpleStatsPredictor
from delivery_optimizer.profiles import get_profile
from delivery_optimizer.reports import build_shift_report, events_from_offers
from delivery_optimizer.store import OptimizerStore


class StoreAndProductLayerTest(unittest.TestCase):
    def test_store_records_offers_deliveries_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = OptimizerStore(Path(tmp) / "optimizer.sqlite3")
            offer = Offer(
                platform="doordash",
                offer_id="dd-store",
                gross_payout=20,
                pickup_miles=1,
                dropoff_miles=3,
                estimated_minutes=22,
            )
            store.record_offer(offer)
            store.record_delivery(
                DeliveryRecord(
                    platform="doordash",
                    offered_payout=20,
                    final_payout=22,
                    estimated_minutes=22,
                    actual_minutes=24,
                    estimated_miles=4,
                    actual_miles=4.5,
                    dropoff_zone="downtown",
                )
            )

            summary = store.summary()

            self.assertEqual(summary["offer_count"], 1)
            self.assertEqual(summary["delivery_count"], 1)
            self.assertEqual(summary["completed_profit"], 22)
            self.assertEqual(store.list_offers()[0].offer_id, "dd-store")
            store.close()

    def test_demo_seed_and_dashboard_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = OptimizerStore(Path(tmp) / "optimizer.sqlite3")
            seed_demo_data(store)
            state = DashboardApp(store).state(
                {
                    "profile": ["maximize_hourly"],
                    "demand": ["1.2"],
                    "traffic": ["1.1"],
                    "weather": ["0"],
                    "saturation": ["1"],
                    "expectedHourly": ["28"],
                }
            )

            self.assertGreaterEqual(state["summary"]["offer_count"], 3)
            self.assertIn("recommendation", state)
            self.assertIn("strategy_runs", state["report"])
            self.assertIn("platform_profiles", state["calibration"])
            store.close()

    def test_predictor_and_shift_report_surface_counterfactuals(self) -> None:
        records = [
            DeliveryRecord(
                platform="uber_eats",
                offered_payout=12,
                final_payout=14,
                estimated_minutes=20,
                actual_minutes=25,
                estimated_miles=4,
                actual_miles=4.5,
                dropoff_zone="midtown",
            )
        ]
        offers = [
            Offer(
                platform="uber_eats",
                offer_id="ue-report",
                gross_payout=18,
                pickup_miles=1,
                dropoff_miles=3,
                estimated_minutes=20,
                dropoff_zone="midtown",
            )
        ]
        optimizer = DeliverySessionOptimizer(
            DriverPreferences(target_profit_per_hour=18, minimum_profit_per_hour=12)
        )
        predictor = SimpleStatsPredictor(records)

        prediction = predictor.predict(offers[0], MarketState(expected_offer_profit_per_hour=30))
        report = build_shift_report(events_from_offers(offers), optimizer, predictor)

        self.assertGreater(prediction.predicted_final_payout, offers[0].gross_payout)
        self.assertGreaterEqual(report.hindsight.max_profit, 0)
        self.assertGreaterEqual(len(report.strategy_runs), 3)

    def test_driver_profile_builds_optimizer(self) -> None:
        profile = get_profile("minimize_miles")
        optimizer = profile.optimizer()

        self.assertEqual(optimizer.policy.name, "conservative")
        self.assertLess(profile.preferences.max_total_miles, 20)


if __name__ == "__main__":
    unittest.main()
