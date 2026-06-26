import unittest

from delivery_optimizer import (
    Decision,
    DeliverySessionOptimizer,
    DriverPreferences,
    Offer,
    PlatformAction,
    SessionState,
)


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
                    gross_payout=15.0,
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
            PlatformAction.PAUSE_WHILE_ACTIVE,
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
                gross_payout=18.0,
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


if __name__ == "__main__":
    unittest.main()
