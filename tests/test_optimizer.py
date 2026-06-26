import unittest

from delivery_optimizer import (
    Decision,
    DeliverySessionOptimizer,
    DriverPreferences,
    MarketState,
    Offer,
    PlatformAction,
    SessionState,
)
from delivery_optimizer.integrations import (
    DoorDashCredentials,
    DoorDashDriveClient,
    GrubhubCredentials,
    GrubhubPartnerClient,
    UberEatsClient,
)
from delivery_optimizer.integrations.auth import hs256_jwt


class DeliverySessionOptimizerTest(unittest.TestCase):
    def test_recommends_best_accepted_offer_across_platforms(self) -> None:
        optimizer = DeliverySessionOptimizer(
            DriverPreferences(
                vehicle_cost_per_mile=0.4,
                target_profit_per_hour=22,
                minimum_profit_per_hour=16,
                minimum_net_profit=3,
            )
        )
        recommendation = optimizer.recommend(
            [
                Offer(
                    platform="doordash",
                    offer_id="dd-low",
                    gross_payout=6.0,
                    pickup_miles=2.0,
                    dropoff_miles=5.0,
                    estimated_minutes=30,
                ),
                Offer(
                    platform="uber_eats",
                    offer_id="ue-good",
                    gross_payout=24.0,
                    pickup_miles=1.0,
                    dropoff_miles=3.5,
                    estimated_minutes=24,
                ),
            ]
        )

        self.assertIsNotNone(recommendation.selected)
        self.assertEqual(recommendation.selected.offer.offer_id, "ue-good")
        self.assertEqual(recommendation.selected.decision, Decision.ACCEPT)
        self.assertEqual(
            recommendation.platform_actions["uber_eats"],
            PlatformAction.ACCEPT_SELECTED,
        )
        self.assertEqual(
            recommendation.platform_actions["doordash"],
            PlatformAction.PAUSE_AFTER_PICKUP,
        )

    def test_declines_offer_below_target_after_costs(self) -> None:
        optimizer = DeliverySessionOptimizer(
            DriverPreferences(
                vehicle_cost_per_mile=0.7,
                target_profit_per_hour=25,
                minimum_profit_per_hour=18,
                minimum_net_profit=4,
            )
        )

        scored = optimizer.score_offer(
            Offer(
                platform="grubhub",
                offer_id="gh-bad",
                gross_payout=7.0,
                pickup_miles=4.0,
                dropoff_miles=8.0,
                estimated_minutes=42,
            )
        )

        self.assertEqual(scored.decision, Decision.DECLINE)
        self.assertIn("below session target rate", scored.reasons)

    def test_unknown_platform_uses_default_profile(self) -> None:
        optimizer = DeliverySessionOptimizer(
            DriverPreferences(
                vehicle_cost_per_mile=0.35,
                target_profit_per_hour=20,
                minimum_profit_per_hour=15,
                minimum_net_profit=3,
            )
        )

        scored = optimizer.score_offer(
            Offer(
                platform="new_marketplace",
                offer_id="nm-1",
                gross_payout=24.0,
                pickup_miles=1.0,
                dropoff_miles=2.0,
                estimated_minutes=20,
            )
        )

        self.assertEqual(scored.decision, Decision.ACCEPT)
        self.assertGreater(scored.net_profit, 0)

    def test_session_state_raises_threshold_when_driver_is_behind_goal(self) -> None:
        optimizer = DeliverySessionOptimizer(
            DriverPreferences(
                vehicle_cost_per_mile=0.4,
                target_profit_per_hour=30,
                minimum_profit_per_hour=15,
                minimum_net_profit=3,
            )
        )
        offer = Offer(
            platform="doordash",
            offer_id="dd-borderline",
            gross_payout=13.0,
            pickup_miles=1.0,
            dropoff_miles=2.5,
            estimated_minutes=25,
        )

        normal = optimizer.score_offer(offer)
        behind = optimizer.score_offer(
            offer,
            SessionState(elapsed_minutes=180, net_profit_so_far=30, goal_minutes=240),
        )

        self.assertGreater(normal.value_margin, behind.value_margin)
        self.assertEqual(behind.decision, Decision.DECLINE)

    def test_hot_market_charges_option_value_for_waiting(self) -> None:
        optimizer = DeliverySessionOptimizer(
            DriverPreferences(
                vehicle_cost_per_mile=0.35,
                target_profit_per_hour=24,
                minimum_profit_per_hour=16,
                minimum_net_profit=3,
                wait_option_value_weight=0.7,
            )
        )
        offer = Offer(
            platform="doordash",
            offer_id="dd-okay",
            gross_payout=18.0,
            pickup_miles=0.8,
            dropoff_miles=3.0,
            estimated_minutes=22,
        )

        normal = optimizer.score_offer(offer)
        hot_market = optimizer.score_offer(
            offer,
            market=MarketState(
                demand_multiplier=1.8,
                courier_saturation=0.7,
                expected_offer_profit_per_hour=34,
            ),
        )

        self.assertGreater(hot_market.option_value, normal.option_value)
        self.assertLess(hot_market.value_margin, normal.value_margin)

    def test_destination_penalty_is_discounted_for_hot_dropoff_zone(self) -> None:
        optimizer = DeliverySessionOptimizer(
            DriverPreferences(
                vehicle_cost_per_mile=0.35,
                target_profit_per_hour=18,
                minimum_profit_per_hour=14,
                minimum_net_profit=3,
                destination_penalty_per_mile=1.0,
            )
        )
        offer = Offer(
            platform="grubhub",
            offer_id="gh-zone",
            gross_payout=22.0,
            pickup_miles=1.0,
            dropoff_miles=4.0,
            return_miles=6.0,
            estimated_minutes=25,
            dropoff_zone="downtown",
        )

        cold = optimizer.score_offer(offer, market=MarketState(zone_heat={"downtown": 0.5}))
        hot = optimizer.score_offer(offer, market=MarketState(zone_heat={"downtown": 2.0}))

        self.assertGreater(cold.destination_penalty, hot.destination_penalty)
        self.assertGreater(hot.value_margin, cold.value_margin)


class IntegrationScaffoldTest(unittest.TestCase):
    def test_doordash_jwt_has_three_segments(self) -> None:
        client = DoorDashDriveClient(
            DoorDashCredentials(
                developer_id="developer",
                key_id="key",
                signing_secret="secret",
            )
        )

        token = client.build_jwt()

        self.assertEqual(len(token.split(".")), 3)

    def test_hs256_jwt_is_deterministic_for_same_claims(self) -> None:
        header = {"alg": "HS256", "typ": "JWT", "kid": "key"}
        payload = {"aud": "doordash", "iss": "developer", "iat": 1, "exp": 2}

        self.assertEqual(
            hs256_jwt(header, payload, "secret"),
            hs256_jwt(header, payload, "secret"),
        )

    def test_grubhub_auth_header_contains_required_mac_parts(self) -> None:
        client = GrubhubPartnerClient(
            GrubhubCredentials(
                partner_key="partner",
                client_id="client",
                signing_secret="secret",
            )
        )

        header = client.headers("POST", "/orders", b"{}")["Authorization"]

        self.assertIn('MAC id="sv:v1:client"', header)
        self.assertIn("nonce=", header)
        self.assertIn("bodyhash=", header)
        self.assertIn("mac=", header)

    def test_uber_order_payload_normalizes_to_offer(self) -> None:
        offer = UberEatsClient.order_to_offer(
            {
                "order_id": "ue-1",
                "estimated_payout": {"amount": 1650},
                "distance_meters": 4828,
                "duration_seconds": 1800,
            }
        )

        self.assertEqual(offer.platform, "uber_eats")
        self.assertEqual(offer.offer_id, "ue-1")
        self.assertEqual(offer.gross_payout, 16.5)
        self.assertAlmostEqual(offer.dropoff_miles, 3.0, places=1)


if __name__ == "__main__":
    unittest.main()
