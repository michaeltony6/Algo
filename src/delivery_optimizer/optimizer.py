from __future__ import annotations

from collections.abc import Iterable, Mapping

from .models import (
    Decision,
    DriverPreferences,
    MarketState,
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
        payout_volatility=0.12,
        tip_transparency=0.65,
        dispatch_confidence=0.88,
    ),
    "doordash": PlatformProfile(
        name="doordash",
        reliability=0.96,
        cancellation_risk=0.03,
        wait_time_buffer_minutes=4.0,
        offer_arrival_rate_per_hour=5.5,
        payout_volatility=0.07,
        tip_transparency=0.8,
        dispatch_confidence=0.92,
    ),
    "grubhub": PlatformProfile(
        name="grubhub",
        reliability=0.95,
        cancellation_risk=0.025,
        wait_time_buffer_minutes=5.0,
        offer_arrival_rate_per_hour=3.5,
        payout_volatility=0.06,
        tip_transparency=0.82,
        dispatch_confidence=0.9,
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

    def score_offer(
        self,
        offer: Offer,
        state: SessionState | None = None,
        market: MarketState | None = None,
    ) -> ScoredOffer:
        profile = self._profile_for(offer.platform)
        prefs = self.preferences
        market = market or MarketState()

        total_miles = (
            offer.pickup_miles
            + offer.dropoff_miles
            + (offer.return_miles * prefs.return_to_zone_weight)
        )
        total_minutes = self._traffic_adjusted_minutes(
            offer.estimated_minutes
            + offer.pickup_wait_minutes
            + profile.wait_time_buffer_minutes
            + market.platform_wait_minutes.get(offer.platform, market.estimated_wait_minutes * 0.15)
            + (offer.order_complexity * 2)
            + (max(offer.stacked_count - 1, 0) * 4),
            market,
        )
        hours = total_minutes / 60

        expected_revenue = self._expected_revenue(offer, profile)
        operating_cost = (total_miles * prefs.vehicle_cost_per_mile) + offer.tolls + offer.parking

        risk_penalty = self._risk_penalty(offer, profile, market, expected_revenue)
        volatility_penalty = (
            expected_revenue
            * profile.payout_volatility
            * prefs.payout_volatility_weight
            * (1 - prefs.risk_tolerance)
        )
        confidence_penalty = expected_revenue * (1 - offer.confidence) * (1 - prefs.risk_tolerance)
        destination_penalty = self._destination_penalty(offer, market)
        lateness_penalty = self._lateness_penalty(offer, total_minutes)
        shop_and_pay_penalty = prefs.shop_and_pay_penalty if offer.is_shop_and_pay else 0.0

        net_profit = (
            expected_revenue
            - operating_cost
            - risk_penalty
            - volatility_penalty
            - confidence_penalty
            - destination_penalty
            - lateness_penalty
            - shop_and_pay_penalty
        )
        profit_per_hour = net_profit / hours if hours else 0.0

        reservation_rate = self._reservation_rate(state)
        opportunity_cost = reservation_rate * hours
        option_value = self._option_value(offer, profile, market, hours, reservation_rate)
        value_margin = net_profit - opportunity_cost - option_value

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
            option_value=round(option_value, 2),
            destination_penalty=round(destination_penalty, 2),
            lateness_penalty=round(lateness_penalty, 2),
            volatility_penalty=round(volatility_penalty, 2),
            confidence_penalty=round(confidence_penalty, 2),
            value_margin=round(value_margin, 2),
            reasons=tuple(reasons),
        )

    def recommend(
        self,
        offers: Iterable[Offer],
        state: SessionState | None = None,
        market: MarketState | None = None,
    ) -> Recommendation:
        scored = tuple(
            sorted(
                (self.score_offer(offer, state, market) for offer in offers),
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

    def _expected_revenue(self, offer: Offer, profile: PlatformProfile) -> float:
        guaranteed = offer.gross_payout + offer.bonus
        visible_tip_value = offer.tip_estimate * profile.tip_transparency
        return (
            guaranteed + visible_tip_value
        ) * offer.completion_probability * profile.reliability * profile.dispatch_confidence

    def _traffic_adjusted_minutes(self, minutes: float, market: MarketState) -> float:
        weather_drag = 1 + (market.weather_risk * 0.25)
        return minutes * max(market.traffic_multiplier, 0.1) * weather_drag

    def _risk_penalty(
        self,
        offer: Offer,
        profile: PlatformProfile,
        market: MarketState,
        expected_revenue: float,
    ) -> float:
        prefs = self.preferences
        success_probability = (
            offer.completion_probability
            * profile.reliability
            * profile.dispatch_confidence
            * (1 - profile.cancellation_risk)
            * offer.confidence
            * (1 - (market.weather_risk * 0.35))
        )
        failure_risk = 1 - max(0.0, min(success_probability, 1.0))
        return expected_revenue * failure_risk * (1 - prefs.risk_tolerance)

    def _destination_penalty(self, offer: Offer, market: MarketState) -> float:
        prefs = self.preferences
        if offer.dropoff_zone and offer.dropoff_zone in prefs.preferred_zones:
            return 0.0

        zone_heat = market.zone_heat.get(offer.dropoff_zone, 1.0) if offer.dropoff_zone else 1.0
        heat_discount = max(zone_heat, 0.25)
        distance = offer.distance_to_preferred_zone_miles or (offer.return_miles * prefs.return_to_zone_weight)
        return (distance * prefs.destination_penalty_per_mile) / heat_discount

    def _lateness_penalty(self, offer: Offer, total_minutes: float) -> float:
        if offer.latest_dropoff_minutes is None or total_minutes <= offer.latest_dropoff_minutes:
            return 0.0
        return (total_minutes - offer.latest_dropoff_minutes) * self.preferences.lateness_penalty_per_minute

    def _option_value(
        self,
        offer: Offer,
        profile: PlatformProfile,
        market: MarketState,
        hours: float,
        reservation_rate: float,
    ) -> float:
        market_rate = market.platform_expected_profit_per_hour.get(
            offer.platform,
            market.expected_offer_profit_per_hour,
        )
        adjusted_rate = (
            market_rate
            * max(market.demand_multiplier, 0.1)
            / max(market.courier_saturation, 0.25)
        )
        better_offer_premium = max(0.0, adjusted_rate - reservation_rate)
        arrival_pressure = min(1.0, profile.offer_arrival_rate_per_hour * max(hours, 0.0) / 3)
        return (
            better_offer_premium
            * hours
            * arrival_pressure
            * self.preferences.wait_option_value_weight
        )

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
        paid_miles = max(offer.dropoff_miles, 0.1)
        deadhead_ratio = offer.pickup_miles / (offer.pickup_miles + paid_miles)
        if deadhead_ratio > prefs.max_deadhead_ratio:
            reasons.append("too much pickup deadhead")
        if offer.acceptance_deadline_seconds is not None and offer.acceptance_deadline_seconds < 5:
            reasons.append("decision window is too short")
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
