# Delivery Session Optimizer

This project contains a first-pass algorithm for choosing the most profitable delivery offer across Uber Eats, DoorDash, Grubhub, or any other marketplace. It does not require or store driver credentials, and it should be fed by approved APIs, user-entered offers, or another compliant data source.

If a GitHub personal access token was shared in chat or committed anywhere, revoke it immediately and create a replacement with only the repository permissions needed.

## What The Algorithm Optimizes

Each incoming offer is normalized into the same shape, then scored by expected dollars over the driver's session target:

```text
expected revenue
- mileage cost
- tolls / parking
- risk penalty
- target profit for the occupied time
= offer value margin
```

The engine recommends the highest-margin acceptable offer and suggests pausing other platforms while that delivery is active.

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

Platform parameters:

- `reliability`: confidence that displayed/estimated payout arrives as expected.
- `cancellation_risk`: probability-like penalty for platform/store/customer cancellation.
- `wait_time_buffer_minutes`: expected extra time for that platform.
- `offer_arrival_rate_per_hour`: useful for future market forecasting.

Offer parameters:

- `gross_payout`: displayed guaranteed/estimated payout.
- `tip_estimate`: extra expected tip not already included in `gross_payout`.
- `bonus`: promo or peak pay.
- `pickup_miles`, `dropoff_miles`, `return_miles`: route burden.
- `estimated_minutes`, `pickup_wait_minutes`: time burden.
- `tolls`, `parking`: direct costs.
- `completion_probability`: chance the delivery completes and pays as expected.

## CLI Example

Create `offers.json`:

```json
[
  {
    "platform": "doordash",
    "offer_id": "dd-101",
    "gross_payout": 18.5,
    "pickup_miles": 1.8,
    "dropoff_miles": 4.1,
    "estimated_minutes": 24
  },
  {
    "platform": "uber_eats",
    "offer_id": "ue-88",
    "gross_payout": 13.75,
    "pickup_miles": 0.7,
    "dropoff_miles": 2.4,
    "estimated_minutes": 16,
    "completion_probability": 0.93
  }
]
```

Run:

```bash
delivery-optimizer --offers offers.json --target-hourly 25 --vehicle-cost 0.45
```

Or from source:

```bash
PYTHONPATH=src python3 -m delivery_optimizer --offers offers.json --target-hourly 25 --vehicle-cost 0.45
```

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
