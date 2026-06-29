# Delivery Session Optimizer

This project contains a platform-agnostic decision engine for choosing the most profitable delivery offer across Uber Eats, DoorDash, Grubhub, or any other marketplace. It does not require or store driver credentials, and it should be fed by approved APIs, webhooks, user-entered offers, or another compliant data source.

If a GitHub personal access token was shared in chat or committed anywhere, revoke it immediately and create a replacement with only the repository permissions needed.

## What The System Does

The project has three layers:

- `integrations`: official API auth/signing clients and payload normalizers for Uber Eats, DoorDash, and Grubhub.
- `routing`: route providers that can enrich offers with pickup, dropoff, and return-to-zone distance.
- `calibration`: historical session learning that updates platform profiles, market expectations, and policy weights.
- `simulation`: backtesting strategies against replayed offer streams.
- `models`: normalized offers, platform profiles, driver preferences, route context, market state, and action recommendations.
- `optimizer`: a policy-driven decision engine that ranks offers and recommends app actions.

Official API reality check:

- Uber Eats Marketplace APIs support approved store/menu/order workflows through OAuth 2.0; they are not a public driver-offer feed.
- DoorDash Drive/Marketplace APIs use signed JWT authentication for approved logistics/merchant workflows; they are not a public driver-offer feed.
- Grubhub Partner APIs support merchant/POS menu and order workflows using partner keys and MAC auth; they are not a public driver-offer feed.

That means the compliant architecture is: official partner data where approved, plus manual/webhook offer ingestion where driver-offer data is not exposed by the platform.

See [Architecture](docs/ARCHITECTURE.md) and [API Integrations](docs/API_INTEGRATIONS.md) for details.

## What The Algorithm Optimizes

Each incoming offer is normalized into the same shape, then scored by expected dollars over the driver's session target:

```text
expected revenue
- mileage cost
- tolls / parking
- risk penalty
- payout volatility penalty
- confidence penalty
- bad destination / return-to-zone penalty
- lateness penalty
- option value of waiting in a hot market
- target profit for the occupied time
= offer value margin
```

The engine recommends the highest-margin acceptable offer and suggests pausing other platforms while that delivery is active.
Secondary app actions are more nuanced than all-or-nothing pausing: the recommendation can keep other apps online until pickup, accept only same-corridor add-ons, pause after pickup, or decline conflicting offers when a delivery is deadline-sensitive.

## Core Parameters

Driver/session parameters:

- `vehicle_cost_per_mile`: all-in operating cost per mile, including fuel, maintenance, tires, depreciation, and insurance allocation.
- `target_profit_per_hour`: desired net profit rate after vehicle costs.
- `minimum_net_profit`: absolute minimum net profit for any accepted offer.
- `minimum_profit_per_hour`: hard hourly floor even when the session target is lower.
- `max_offer_minutes`: maximum estimated time the driver is willing to commit to one offer.
- `max_total_miles`: maximum total miles for one offer.
- `max_pickup_miles`: maximum unpaid/low-confidence miles before pickup.
- `return_to_zone_weight`: how much to count return miles to a preferred hotspot.
- `risk_tolerance`: `0.0` is conservative, `1.0` ignores risk penalties.
- `max_deadhead_ratio`: rejects offers where pickup miles dominate paid delivery miles.
- `wait_option_value_weight`: how aggressively to decline okay orders when the market is hot.
- `payout_volatility_weight`: how strongly to discount platforms/offers with uncertain payouts.
- `destination_penalty_per_mile`: cost assigned to ending far from preferred zones.
- `lateness_penalty_per_minute`: penalty for deliveries projected past the dropoff deadline.
- `preferred_zones`: zones where ending a delivery is strategically good.

Platform parameters:

- `reliability`: confidence that displayed/estimated payout arrives as expected.
- `cancellation_risk`: probability-like penalty for platform/store/customer cancellation.
- `wait_time_buffer_minutes`: expected extra time for that platform.
- `offer_arrival_rate_per_hour`: useful for future market forecasting.
- `payout_volatility`: how uncertain the platform's displayed payout tends to be.
- `tip_transparency`: how much of a tip estimate should be trusted.
- `dispatch_confidence`: probability-like confidence that the platform/order dispatch will behave as expected.

Offer parameters:

- `gross_payout`: displayed guaranteed/estimated payout.
- `tip_estimate`: extra expected tip not already included in `gross_payout`.
- `bonus`: promo or peak pay.
- `pickup_miles`, `dropoff_miles`, `return_miles`: route burden.
- `estimated_minutes`, `pickup_wait_minutes`: time burden.
- `tolls`, `parking`: direct costs.
- `completion_probability`: chance the delivery completes and pays as expected.
- `confidence`: confidence in the normalized offer data.
- `acceptance_deadline_seconds`: how much time the user has to decide.
- `latest_dropoff_minutes`: deadline pressure for lateness penalties.
- `pickup_zone`, `dropoff_zone`: zone labels for hotspot strategy.
- `distance_to_preferred_zone_miles`: burden of ending away from the driver's preferred market.
- `stacked_count`: number of orders in a stack/batch.
- `order_complexity`: extra handling complexity.
- `is_shop_and_pay`: applies a configurable shopping penalty.

Market parameters:

- `demand_multiplier`: how strong current demand is.
- `traffic_multiplier`: multiplier on estimated time.
- `weather_risk`: increases time and failure-risk penalties.
- `courier_saturation`: high saturation reduces the value of waiting.
- `expected_offer_profit_per_hour`: market-wide expected opportunity if the driver waits.
- `platform_expected_profit_per_hour`: platform-specific expected opportunity.
- `platform_wait_minutes`: platform-specific wait buffers.
- `zone_heat`: multiplier for zones where ending a trip is good.

## CLI Example

Create `offers.json` or use [examples/offers.sample.json](examples/offers.sample.json):

```json
[
  {
    "platform": "doordash",
    "offer_id": "dd-101",
    "gross_payout": 26.5,
    "pickup_miles": 1.8,
    "dropoff_miles": 4.1,
    "estimated_minutes": 24,
    "dropoff_zone": "downtown",
    "distance_to_preferred_zone_miles": 1.2,
    "confidence": 0.92
  },
  {
    "platform": "uber_eats",
    "offer_id": "ue-88",
    "gross_payout": 19.75,
    "pickup_miles": 0.7,
    "dropoff_miles": 2.4,
    "estimated_minutes": 16,
    "completion_probability": 0.93,
    "latest_dropoff_minutes": 25,
    "confidence": 0.86
  }
]
```

Run:

```bash
delivery-optimizer \
  --offers offers.json \
  --target-hourly 25 \
  --vehicle-cost 0.45 \
  --demand-multiplier 1.2 \
  --traffic-multiplier 1.1 \
  --expected-offer-hourly 28 \
  --policy dinner_rush
```

Or from source:

```bash
PYTHONPATH=src python3 -m delivery_optimizer --offers examples/offers.sample.json --target-hourly 25 --vehicle-cost 0.45
```

## Dashboard

Run the local operations console:

```bash
PYTHONPATH=src python3 -m delivery_optimizer.dashboard --db data/demo.sqlite3
```

After package installation, the same app is available as:

```bash
delivery-dashboard --db data/demo.sqlite3
```

The dashboard seeds itself from `examples/offers.sample.json` and `examples/history.sample.json` when the database is empty. It shows live recommendations, driver profile controls, market sliders, prediction confidence, calibration, zone ranking, and strategy backtests.

It also includes a **Live Random Route Lab**. Use `Start`, `Step`, `Burst`, and `Reset` to generate random delivery-route batches in real time. Each tick shows:

- the simulated offers that appeared
- how the optimizer ranked them
- accept/decline status
- reasons for each decision
- active-delivery timing
- running profit, hourly rate, accepted count, and declined count

The lab is deterministic by seed, so the same seed recreates the same route stream for debugging.

Available policies:

- `balanced`
- `conservative`
- `aggressive`
- `dinner_rush`
- `rainy_day`

## Historical Learning

Use `delivery_optimizer.calibration.calibrate()` with records shaped like [examples/history.sample.json](examples/history.sample.json). The calibrator learns:

- platform reliability
- cancellation risk
- wait-time buffer
- payout volatility
- expected market profit per hour
- a suggested `calibrated` scoring policy

## Backtesting

Use `delivery_optimizer.simulation.BacktestSimulator` to replay offer streams against the optimizer and simpler baseline strategies such as dollars-per-mile or hourly threshold rules. This is the path for proving whether a new scoring policy would have improved a real shift before using it live.

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
