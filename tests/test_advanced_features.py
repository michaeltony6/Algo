import os
import unittest

from delivery_optimizer import (
    DeliverySessionOptimizer,
    DriverPreferences,
    Location,
    MarketState,
    Offer,
    PlatformAction,
    get_policy,
)
from delivery_optimizer.calibration import DeliveryRecord, calibrate
from delivery_optimizer.integrations import DoorDashCredentials, GrubhubCredentials, UberCredentials
from delivery_optimizer.normalization import normalize_offer_mapping
from delivery_optimizer.routing import HaversineRouteProvider, enrich_offer_routes
from delivery_optimizer.simulation import (
    BacktestSimulator,
    DollarsPerMileStrategy,
    OfferEvent,
    OptimizerStrategy,
)


class PolicyAndActionTest(unittest.TestCase):
    def test_conservative_policy_scores_lower_than_aggressive_policy(self) -> None:
        offer = Offer(
            platform="uber_eats",
            offer_id="ue-risky",
            gross_payout=24.0,
            pickup_miles=2.0,
            dropoff_miles=4.0,
            estimated_minutes=25,
            confidence=0.75,
            completion_probability=0.9,
        )
        preferences = DriverPreferences(target_profit_per_hour=20, minimum_profit_per_hour=14)

        conservative = DeliverySessionOptimizer(preferences, policy=get_policy("conservative")).score_offer(offer)
        aggressive = DeliverySessionOptimizer(preferences, policy=get_policy("aggressive")).score_offer(offer)

        self.assertLess(conservative.value_margin, aggressive.value_margin)
        self.assertEqual(conservative.policy_name, "conservative")
        self.assertEqual(aggressive.policy_name, "aggressive")

    def test_tight_deadline_makes_other_platforms_decline_conflicting(self) -> None:
        optimizer = DeliverySessionOptimizer(
            DriverPreferences(target_profit_per_hour=12, minimum_profit_per_hour=8, minimum_net_profit=2)
        )
        recommendation = optimizer.recommend(
            [
                Offer(
                    platform="doordash",
                    offer_id="dd-tight",
                    gross_payout=40,
                    pickup_miles=0.5,
                    dropoff_miles=1,
                    estimated_minutes=20,
                    latest_dropoff_minutes=23,
                ),
                Offer(
                    platform="uber_eats",
                    offer_id="ue-lower",
                    gross_payout=10,
                    pickup_miles=0.2,
                    dropoff_miles=1,
                    estimated_minutes=15,
                ),
            ]
        )

        self.assertEqual(recommendation.selected.offer.offer_id, "dd-tight")
        self.assertEqual(recommendation.platform_actions["uber_eats"], PlatformAction.DECLINE_CONFLICTING)


class RoutingAndNormalizationTest(unittest.TestCase):
    def test_haversine_provider_enriches_offer_route_fields(self) -> None:
        offer = Offer(
            platform="doordash",
            offer_id="dd-route",
            gross_payout=18,
            pickup_miles=0,
            dropoff_miles=0,
            estimated_minutes=1,
            pickup_location=Location(34.0522, -118.2437, "pickup"),
            dropoff_location=Location(34.0622, -118.2537, "dropoff"),
        )

        enriched = enrich_offer_routes(
            offer,
            HaversineRouteProvider(speed_mph=20, circuity=1.2),
            current_location=Location(34.05, -118.24, "current"),
            preferred_location=Location(34.0522, -118.2437, "preferred"),
        )

        self.assertGreater(enriched.pickup_miles, 0)
        self.assertGreater(enriched.dropoff_miles, 0)
        self.assertGreater(enriched.return_miles, 0)
        self.assertLessEqual(enriched.confidence, offer.confidence)

    def test_normalizer_reports_errors_and_warning_confidence(self) -> None:
        invalid = normalize_offer_mapping({"platform": "doordash"})
        self.assertFalse(invalid.is_valid)
        self.assertIn("offer_id", {issue.field for issue in invalid.issues})

        valid = normalize_offer_mapping(
            {
                "platform": "doordash",
                "offer_id": "dd-normalized",
                "gross_payout": 16,
                "estimated_minutes": 20,
            }
        )
        self.assertTrue(valid.is_valid)
        self.assertLess(valid.offer.confidence, 0.9)
        self.assertTrue(any(issue.severity == "warning" for issue in valid.issues))


class CalibrationAndSimulationTest(unittest.TestCase):
    def test_calibration_learns_platform_profile_and_market_rate(self) -> None:
        report = calibrate(
            [
                DeliveryRecord(
                    platform="doordash",
                    offered_payout=10,
                    final_payout=12,
                    estimated_minutes=20,
                    actual_minutes=24,
                    estimated_miles=4,
                    actual_miles=4.5,
                    timestamp_minutes=0,
                ),
                DeliveryRecord(
                    platform="doordash",
                    offered_payout=9,
                    final_payout=0,
                    estimated_minutes=18,
                    actual_minutes=0,
                    estimated_miles=3,
                    actual_miles=0,
                    completed=False,
                    canceled=True,
                    timestamp_minutes=20,
                ),
            ]
        )

        profile = report.platform_profiles["doordash"]
        self.assertLess(profile.reliability, 1)
        self.assertGreater(profile.cancellation_risk, 0)
        self.assertGreater(report.market_state.expected_offer_profit_per_hour, 0)
        self.assertEqual(report.suggested_policy.name, "calibrated")

    def test_backtest_compares_optimizer_to_baseline_strategy(self) -> None:
        optimizer = DeliverySessionOptimizer(
            DriverPreferences(target_profit_per_hour=18, minimum_profit_per_hour=12, minimum_net_profit=2)
        )
        events = [
            OfferEvent(
                timestamp_minutes=0,
                offer=Offer(
                    platform="doordash",
                    offer_id="dd-good",
                    gross_payout=32,
                    pickup_miles=0.5,
                    dropoff_miles=2,
                    estimated_minutes=20,
                ),
                actual_payout=24,
                actual_minutes=28,
                actual_miles=3,
            ),
            OfferEvent(
                timestamp_minutes=45,
                offer=Offer(
                    platform="uber_eats",
                    offer_id="ue-bad",
                    gross_payout=8,
                    pickup_miles=3,
                    dropoff_miles=6,
                    estimated_minutes=35,
                ),
            ),
        ]

        runs = BacktestSimulator(optimizer).compare(
            events,
            [OptimizerStrategy(), DollarsPerMileStrategy(minimum=3.0)],
        )

        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0].strategy_name, "optimizer")
        self.assertGreaterEqual(runs[0].accepted_count, 1)
        self.assertGreater(runs[0].profit_per_hour, 0)


class CredentialLoadingTest(unittest.TestCase):
    def test_credentials_can_load_from_environment(self) -> None:
        old_values = {key: os.environ.get(key) for key in (
            "UBER_CLIENT_ID",
            "UBER_CLIENT_SECRET",
            "DOORDASH_DEVELOPER_ID",
            "DOORDASH_KEY_ID",
            "DOORDASH_SIGNING_SECRET",
            "GRUBHUB_PARTNER_KEY",
            "GRUBHUB_CLIENT_ID",
            "GRUBHUB_SIGNING_SECRET",
        )}
        try:
            os.environ.update(
                {
                    "UBER_CLIENT_ID": "uber-client",
                    "UBER_CLIENT_SECRET": "uber-secret",
                    "DOORDASH_DEVELOPER_ID": "dd-dev",
                    "DOORDASH_KEY_ID": "dd-key",
                    "DOORDASH_SIGNING_SECRET": "dd-secret",
                    "GRUBHUB_PARTNER_KEY": "gh-partner",
                    "GRUBHUB_CLIENT_ID": "gh-client",
                    "GRUBHUB_SIGNING_SECRET": "gh-secret",
                }
            )
            self.assertEqual(UberCredentials.from_env().client_id, "uber-client")
            self.assertEqual(DoorDashCredentials.from_env().key_id, "dd-key")
            self.assertEqual(GrubhubCredentials.from_env().partner_key, "gh-partner")
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
