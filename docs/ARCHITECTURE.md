# Architecture

The optimizer is designed around a compliant ingestion boundary: data comes from official approved integrations, webhooks, manual entry, exports, or simulation fixtures. The core engine does not need driver app credentials.

## Main Flow

```text
raw platform/manual payload
-> normalization
-> optional route enrichment
-> market/session context
-> scoring policy
-> ranked recommendation
-> platform action guidance
-> historical record for calibration/backtesting
```

## Modules

- `models.py`: shared dataclasses and enums.
- `policies.py`: named scoring policies such as `balanced`, `conservative`, `aggressive`, `dinner_rush`, and `rainy_day`.
- `optimizer.py`: expected-profit scoring, decline reasons, and platform action guidance.
- `normalization.py`: validation-oriented conversion from raw dictionaries into `Offer` objects.
- `routing.py`: route providers and offer enrichment.
- `calibration.py`: learns platform and market parameters from historical delivery records.
- `simulation.py`: replays offer events against optimizer and baseline strategies.
- `integrations/`: official API auth/signing scaffolding and payload normalizers.

## The Seven Upgrade Areas

1. Real session calibration is handled by `calibration.py`.
2. Configurable strategy models are handled by `policies.py`.
3. Route intelligence is handled by `routing.py`.
4. API client production hardening lives in `integrations/http.py` and credential classes.
5. Stronger payload validation lives in `normalization.py`.
6. Backtesting lives in `simulation.py`.
7. Smarter app actions live in `optimizer.py`.

## Scoring Components

Each offer is evaluated with:

- expected revenue
- vehicle operating cost
- direct toll/parking cost
- platform/order risk
- payout volatility
- data confidence
- destination and return-to-zone quality
- lateness pressure
- shop-and-pay burden
- opportunity value of waiting
- session reservation rate

The final `value_margin` is the expected net advantage after all costs and opportunity costs. Positive-margin offers are candidates for acceptance unless they violate hard thresholds such as maximum mileage or pickup deadhead.

## Calibration Loop

Historical records should contain estimated and actual payout, time, miles, completion status, and timestamp. The calibrator uses those records to estimate:

- reliability: completed accepted deliveries divided by accepted deliveries.
- cancellation risk: canceled or failed accepted deliveries divided by accepted deliveries.
- wait buffer: actual minutes minus estimated minutes.
- payout volatility: absolute payout error divided by displayed payout.
- platform expected hourly rate: final payout divided by actual active time.

The result can be fed back into `DeliverySessionOptimizer(platform_profiles=..., policy=...)`.

## Routing Loop

When pickup/dropoff/preferred locations are known, route enrichment can replace rough mileage estimates:

```python
from delivery_optimizer.routing import HaversineRouteProvider, enrich_offer_routes

offer = enrich_offer_routes(
    offer,
    HaversineRouteProvider(),
    current_location=current_location,
    preferred_location=home_hotspot,
)
```

`HaversineRouteProvider` is deterministic and offline. `OSRMRouteProvider` can use an OSRM-compatible HTTP endpoint for road-network estimates.

## Backtesting Loop

Backtesting lets you compare strategies before changing live behavior:

```python
from delivery_optimizer.simulation import BacktestSimulator, OptimizerStrategy, DollarsPerMileStrategy

runs = BacktestSimulator(optimizer).compare(
    events,
    [OptimizerStrategy(), DollarsPerMileStrategy(minimum=2.5)],
)
```

Use this to tune policies against actual shifts rather than guessing.
