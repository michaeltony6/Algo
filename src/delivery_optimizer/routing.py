from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import urlopen

from .models import Location, Offer


@dataclass(frozen=True)
class RouteEstimate:
    distance_miles: float
    duration_minutes: float
    provider: str
    confidence: float = 0.8
    polyline: str | None = None


class RouteProvider(Protocol):
    def route(self, origin: Location, destination: Location) -> RouteEstimate:
        ...


class HaversineRouteProvider:
    def __init__(self, speed_mph: float = 22.0, circuity: float = 1.25) -> None:
        self.speed_mph = speed_mph
        self.circuity = circuity

    def route(self, origin: Location, destination: Location) -> RouteEstimate:
        straight_line = haversine_miles(origin, destination)
        distance = straight_line * self.circuity
        duration = (distance / max(self.speed_mph, 1.0)) * 60
        return RouteEstimate(
            distance_miles=round(distance, 2),
            duration_minutes=round(duration, 1),
            provider="haversine",
            confidence=0.55,
        )


class OSRMRouteProvider:
    def __init__(self, base_url: str = "https://router.project-osrm.org") -> None:
        self.base_url = base_url.rstrip("/")

    def route(self, origin: Location, destination: Location) -> RouteEstimate:
        coordinates = f"{origin.longitude},{origin.latitude};{destination.longitude},{destination.latitude}"
        query = urlencode({"overview": "false", "alternatives": "false", "steps": "false"})
        with urlopen(f"{self.base_url}/route/v1/driving/{coordinates}?{query}", timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        routes = payload.get("routes") or []
        if not routes:
            raise ValueError("OSRM did not return a route")
        route = routes[0]
        return RouteEstimate(
            distance_miles=round(float(route["distance"]) / 1609.344, 2),
            duration_minutes=round(float(route["duration"]) / 60, 1),
            provider="osrm",
            confidence=0.9,
        )


def enrich_offer_routes(
    offer: Offer,
    provider: RouteProvider,
    current_location: Location | None = None,
    preferred_location: Location | None = None,
) -> Offer:
    pickup_miles = offer.pickup_miles
    dropoff_miles = offer.dropoff_miles
    return_miles = offer.return_miles
    estimated_minutes = offer.estimated_minutes
    distance_to_preferred_zone_miles = offer.distance_to_preferred_zone_miles
    confidence = offer.confidence

    if current_location and offer.pickup_location:
        pickup_route = provider.route(current_location, offer.pickup_location)
        pickup_miles = pickup_route.distance_miles
        estimated_minutes = max(estimated_minutes, pickup_route.duration_minutes + offer.pickup_wait_minutes)
        confidence = min(confidence, pickup_route.confidence)
    if offer.pickup_location and offer.dropoff_location:
        dropoff_route = provider.route(offer.pickup_location, offer.dropoff_location)
        dropoff_miles = dropoff_route.distance_miles
        estimated_minutes = max(estimated_minutes, dropoff_route.duration_minutes + offer.pickup_wait_minutes)
        confidence = min(confidence, dropoff_route.confidence)
    if preferred_location and offer.dropoff_location:
        return_route = provider.route(offer.dropoff_location, preferred_location)
        return_miles = return_route.distance_miles
        distance_to_preferred_zone_miles = return_route.distance_miles
        confidence = min(confidence, return_route.confidence)

    return replace(
        offer,
        pickup_miles=pickup_miles,
        dropoff_miles=dropoff_miles,
        return_miles=return_miles,
        estimated_minutes=round(estimated_minutes, 1),
        distance_to_preferred_zone_miles=distance_to_preferred_zone_miles,
        confidence=confidence,
    )


def haversine_miles(origin: Location, destination: Location) -> float:
    radius_miles = 3958.7613
    lat1 = math.radians(origin.latitude)
    lat2 = math.radians(destination.latitude)
    delta_lat = math.radians(destination.latitude - origin.latitude)
    delta_lon = math.radians(destination.longitude - origin.longitude)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return radius_miles * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
