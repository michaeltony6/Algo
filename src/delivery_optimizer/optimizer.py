from __future__ import annotations

from collections.abc import Iterable, Mapping

from .models import (
    Decision,
    DriverPreferences,
    Offer,
    PlatformAction,
    PlatformProfile,
    Recommendation,
    ScoredOffer,
    SessionState,
)


DEFAULT_PLATFORM_PROFILES: dict[str, PlatformProfile] = {
    "uber_eats": PlatformProfile(
        name="uber_eats",
        reliability=0.93,
        cancellation_risk=0.04,
        wait_time_buffer_minutes=3.0,
        offer_arrival_rate_per_hour=5.0,
    ),
    "doordash": PlatformProfile(
        name="doordash",
        reliability=0.96,
        cancellation_risk=0.03,
        wait_time_buffer_minutes=4.0,
        offer_arrival_rate_per_hour=5.5,
    ),
    "grubhub": PlatformProfile(
        name="grubhub",
        reliability=0.95,
        cancellation_risk=0.025,
        wait_time_buffer_minutes=5.0,
        offer_arrival_rate_per_hour=3.5,
    ),
}


class DeliverySessionOptimizer:
    """Rank delivery offers by expected net value over the driver's session target."""

    def __init__(
        self,
        preferences: DriverPreferences | None = None,
        platform_profiles: Mapping[str, PlatformProfile] | None = None,
    ) -> None:
        self.preferences = preferences or DriverPreferences()
        self.platform_profiles = dict(DEFAULT_PLATFORM_PROFILES)
        if platform_profiles:
            self.platform_profiles.update(platform_profiles)

    def score_offer(self, offer: Offer, state: SessionState | None = None) -> ScoredOffer:
        profile = self._profile_for(offer.platform)
        prefs = self.preferences

        total_miles = (
            offer.pickup_miles
            + offer.dropoff_miles
            + (offer.return_miles * prefs.return_to_zone_weight)
        )
        total_minutes = (
            offer.estimated_minutes
            + offer.pickup_wait_minutes
            + profile.wait_time_buffer_minutes
        )
        hours = total_minutes / 60

        expected_revenue = (
            offer.gross_payout + offer.tip_estimate + offer.bonus
        ) * offer.completion_probability * profile.reliability
        operating_cost = (total_miles * prefs.vehicle_cost_per_mile) + offer.tolls + offer.parking

        combined_failure_risk = 1 - (
            offer.completion_probability * profile.reliability * (1 - profile.cancellation_risk)
        )
        risk_penalty = expected_revenue * combined_failure_risk * (1 - prefs.risk_tolerance)

        net_profit = expected_revenue - operating_cost - risk_penalty
        profit_per_hour = net_profit / hours if hours else 0.0

        reservation_rate = self._reservation_rate(state)
        opportunity_cost = reservation_rate * hours
        value_margin = net_profit - opportunity_cost

        reasons = self._decline_reasons(
            offer=offer,
            net_profit=net_profit,
            profit_per_hour=profit_per_hour,
            total_miles=total_miles,
            total_minutes=total_minutes,
            value_margin=value_margin,
        )
        decision = Decision.DECLINE if reasons else Decision.ACCEPT

        return ScoredOffer(
            offer=offer,
            decision=decision,
            expected_revenue=round(expected_revenue, 2),
            operating_cost=round(operating_cost, 2),
            risk_penalty=round(risk_penalty, 2),
            opportunity_cost=round(opportunity_cost, 2),
            net_profit=round(net_profit, 2),
            profit_per_hour=round(profit_per_hour, 2),
            total_miles=round(total_miles, 2),
            total_minutes=round(total_minutes, 1),
            value_margin=round(value_margin, 2),
            reasons=tuple(reasons),
        )

    def recommend(
        self,
        offers: Iterable[Offer],
        state: SessionState | None = None,
    ) -> Recommendation:
        scored = tuple(
            sorted(
                (self.score_offer(offer, state) for offer in offers),
                key=lambda scored_offer: (
                    scored_offer.decision == Decision.ACCEPT,
                    scored_offer.value_margin,
                    scored_offer.profit_per_hour,
                    scored_offer.net_profit,
                ),
                reverse=True,
            )
        )
        selected = next((offer for offer in scored if offer.decision == Decision.ACCEPT), None)
        platform_actions = self._platform_actions(scored, selected)
        return Recommendation(
            selected=selected,
            ranked_offers=scored,
            platform_actions=platform_actions,
        )

    def _profile_for(self, platform: str) -> PlatformProfile:
        return self.platform_profiles.get(platform, PlatformProfile(name=platform))

    def _reservation_rate(self, state: SessionState | None) -> float:
        prefs = self.preferences
        base_rate = max(prefs.target_profit_per_hour, prefs.minimum_profit_per_hour)
        if state is None or state.goal_minutes <= state.elapsed_minutes:
            return base_rate

        remaining_hours = (state.goal_minutes - state.elapsed_minutes) / 60
        target_total_profit = prefs.target_profit_per_hour * (state.goal_minutes / 60)
        remaining_profit_needed = target_total_profit - state.net_profit_so_far
        catch_up_rate = remaining_profit_needed / remaining_hours
        return max(base_rate, catch_up_rate)

    def _decline_reasons(
        self,
        offer: Offer,
        net_profit: float,
        profit_per_hour: float,
        total_miles: float,
        total_minutes: float,
        value_margin: float,
    ) -> list[str]:
        prefs = self.preferences
        reasons: list[str] = []
        if net_profit < prefs.minimum_net_profit:
            reasons.append("below minimum net profit")
        if profit_per_hour < prefs.minimum_profit_per_hour:
            reasons.append("below minimum hourly profit")
        if value_margin < 0:
            reasons.append("below session target rate")
        if total_minutes > prefs.max_offer_minutes:
            reasons.append("too much time committed")
        if total_miles > prefs.max_total_miles:
            reasons.append("too many total miles")
        if offer.pickup_miles > prefs.max_pickup_miles:
            reasons.append("pickup is too far")
        return reasons

    def _platform_actions(
        self,
        scored: tuple[ScoredOffer, ...],
        selected: ScoredOffer | None,
    ) -> dict[str, PlatformAction]:
        platforms = {offer.offer.platform for offer in scored}
        if selected is None:
            return {platform: PlatformAction.KEEP_ONLINE for platform in platforms}
        return {
            platform: (
                PlatformAction.ACCEPT_SELECTED
                if platform == selected.offer.platform
                else PlatformAction.PAUSE_WHILE_ACTIVE
            )
            for platform in platforms
        }
