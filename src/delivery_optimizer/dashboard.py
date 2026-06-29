from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .calibration import calibrate
from .integrations.manual import offers_from_json
from .live import LiveRouteLab, live_state_to_dict
from .models import MarketState, Offer
from .optimizer import DeliverySessionOptimizer
from .prediction import SimpleStatsPredictor
from .profiles import PROFILE_PRESETS, get_profile
from .reports import build_shift_report, events_from_offers
from .store import OptimizerStore


DEFAULT_DB_PATH = Path("data/delivery_optimizer.sqlite3")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_OFFERS = PROJECT_ROOT / "examples" / "offers.sample.json"
SAMPLE_HISTORY = PROJECT_ROOT / "examples" / "history.sample.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the delivery optimizer dashboard.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    store = OptimizerStore(args.db)
    seed_demo_data(store)
    app = DashboardApp(store)
    server = ThreadingHTTPServer((args.host, args.port), app.handler_class())
    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"Delivery optimizer dashboard: {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()
    return 0


def seed_demo_data(store: OptimizerStore) -> None:
    summary = store.summary()
    if summary["offer_count"] == 0 and SAMPLE_OFFERS.exists():
        store.record_offers(offers_from_json(SAMPLE_OFFERS))
    if summary["delivery_count"] == 0 and SAMPLE_HISTORY.exists():
        store.import_history_json(SAMPLE_HISTORY)


class DashboardApp:
    def __init__(self, store: OptimizerStore) -> None:
        self.store = store
        self.live_lab = LiveRouteLab()

    def handler_class(self) -> type[BaseHTTPRequestHandler]:
        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                try:
                    if parsed.path == "/":
                        self._send_html(DASHBOARD_HTML)
                    elif parsed.path == "/api/state":
                        self._send_json(app.state(parse_qs(parsed.query)))
                    elif parsed.path == "/api/offers":
                        self._send_json({"offers": [_safe_asdict(offer) for offer in app.store.list_offers()]})
                    elif parsed.path == "/api/profiles":
                        self._send_json(app.profiles())
                    elif parsed.path == "/api/live/state":
                        self._send_json({"live": live_state_to_dict(app.live_lab.state())})
                    elif parsed.path == "/api/health":
                        self._send_json({"status": "ok", "summary": app.store.summary()})
                    else:
                        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                except Exception as error:  # pragma: no cover - surfaced through local app.
                    self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                try:
                    payload = self._read_json()
                    if parsed.path == "/api/live/reset":
                        seed = payload.get("seed")
                        state = app.live_lab.reset(int(seed) if seed not in (None, "") else None)
                        self._send_json({"live": live_state_to_dict(state)})
                    elif parsed.path == "/api/live/tick":
                        count = max(1, min(int(payload.get("count", 1)), 20))
                        event_payloads = []
                        for _ in range(count):
                            event = app.live_lab.step(
                                profile_name=str(payload.get("profile", "maximize_hourly")),
                                market=_market_from_payload(payload),
                            )
                            event_payloads.append(event.tick)
                        self._send_json(
                            {
                                "ticks": event_payloads,
                                "live": live_state_to_dict(app.live_lab.state()),
                            }
                        )
                    else:
                        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                except Exception as error:  # pragma: no cover - surfaced through local app.
                    self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length == 0:
                    return {}
                return json.loads(self.rfile.read(length).decode("utf-8"))

            def _send_html(self, html: str) -> None:
                body = html.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
                body = json.dumps(payload, default=_json_default).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler

    def profiles(self) -> dict:
        return {
            "profiles": [
                {
                    "name": profile.name,
                    "description": profile.description,
                    "policy_name": profile.policy_name,
                    "preferences": _safe_asdict(profile.preferences),
                }
                for profile in PROFILE_PRESETS.values()
            ]
        }

    def state(self, query: dict[str, list[str]]) -> dict:
        profile_name = _query_value(query, "profile", "maximize_hourly")
        profile = get_profile(profile_name)
        market = _market_from_query(query)
        offers = self.store.list_offers()
        records = self.store.list_delivery_records()
        calibration = calibrate(records) if records else None
        platform_profiles = calibration.platform_profiles if calibration else None
        optimizer = DeliverySessionOptimizer(
            preferences=profile.preferences,
            platform_profiles=platform_profiles,
            policy=profile.optimizer().policy,
        )
        recommendation = optimizer.recommend(offers, market=market)
        predictor = SimpleStatsPredictor(records)
        report = build_shift_report(
            events_from_offers(offers, market),
            optimizer,
            predictor=predictor,
        )
        return {
            "summary": self.store.summary(),
            "profile": {
                "name": profile.name,
                "description": profile.description,
                "policy_name": profile.policy_name,
            },
            "market": _safe_asdict(market),
            "recommendation": {
                "selected_offer_id": recommendation.selected.offer.offer_id if recommendation.selected else None,
                "selected_platform": recommendation.selected.offer.platform if recommendation.selected else None,
                "platform_actions": {
                    platform: action.value for platform, action in recommendation.platform_actions.items()
                },
                "ranked_offers": [_safe_asdict(scored) for scored in recommendation.ranked_offers],
            },
            "calibration": _calibration_payload(calibration),
            "predictions": [_safe_asdict(predictor.predict(offer, market)) for offer in offers],
            "zone_rankings": predictor.rank_zone_profitability(),
            "report": report.to_dict(),
        }


def _query_value(query: dict[str, list[str]], key: str, default: str) -> str:
    values = query.get(key)
    return values[0] if values else default


def _market_from_query(query: dict[str, list[str]]) -> MarketState:
    return MarketState(
        demand_multiplier=float(_query_value(query, "demand", "1.15")),
        traffic_multiplier=float(_query_value(query, "traffic", "1.05")),
        weather_risk=float(_query_value(query, "weather", "0.0")),
        courier_saturation=float(_query_value(query, "saturation", "1.0")),
        expected_offer_profit_per_hour=float(_query_value(query, "expectedHourly", "28")),
    )


def _market_from_payload(payload: dict) -> MarketState:
    return MarketState(
        demand_multiplier=float(payload.get("demand", 1.15)),
        traffic_multiplier=float(payload.get("traffic", 1.05)),
        weather_risk=float(payload.get("weather", 0.0)),
        courier_saturation=float(payload.get("saturation", 1.0)),
        expected_offer_profit_per_hour=float(payload.get("expectedHourly", 28)),
    )


def _calibration_payload(calibration: object | None) -> dict:
    if calibration is None:
        return {"sample_size": 0, "platform_profiles": {}, "notes": []}
    return {
        "sample_size": calibration.sample_size,
        "platform_profiles": {
            platform: _safe_asdict(profile)
            for platform, profile in calibration.platform_profiles.items()
        },
        "market_state": _safe_asdict(calibration.market_state),
        "suggested_policy": _safe_asdict(calibration.suggested_policy),
        "notes": list(calibration.notes),
    }


def _safe_asdict(value: object) -> object:
    return json.loads(json.dumps(asdict(value), default=_json_default))


def _json_default(value: object) -> object:
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Delivery Profit Console</title>
  <style>
    :root {
      --ink: #17201c;
      --muted: #65716b;
      --line: #d9dfda;
      --paper: #f7f8f5;
      --panel: #ffffff;
      --green: #197a4d;
      --blue: #2b638f;
      --gold: #b87716;
      --red: #b13f38;
      --shadow: 0 14px 40px rgba(23, 32, 28, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--paper);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    button, select, input { font: inherit; }
    button {
      height: 34px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 6px;
      padding: 0 11px;
      font-weight: 800;
      cursor: pointer;
    }
    button.primary { background: var(--green); border-color: var(--green); color: #fff; }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
    }
    aside {
      border-right: 1px solid var(--line);
      background: #eef2ed;
      padding: 18px;
      position: sticky;
      top: 0;
      height: 100vh;
    }
    main { padding: 18px; }
    .brand { font-weight: 800; font-size: 18px; margin-bottom: 18px; }
    .field { margin-bottom: 14px; }
    label { display: block; font-size: 12px; font-weight: 700; color: var(--muted); margin-bottom: 6px; }
    select, input {
      width: 100%;
      height: 38px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 6px;
      padding: 0 10px;
    }
    input[type="range"] { padding: 0; }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(130px, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .metric, .panel, .offer {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .metric { padding: 12px; min-height: 82px; }
    .metric .label { color: var(--muted); font-size: 12px; font-weight: 700; }
    .metric .value { font-size: 25px; font-weight: 800; margin-top: 4px; }
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr);
      gap: 14px;
      align-items: start;
    }
    .panel { padding: 14px; margin-bottom: 14px; }
    .panel h2 {
      margin: 0 0 10px;
      font-size: 16px;
      line-height: 1.2;
    }
    .offers { display: grid; gap: 10px; }
    .offer {
      padding: 12px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      border-left: 5px solid var(--line);
    }
    .offer.accept { border-left-color: var(--green); }
    .offer.decline { border-left-color: var(--red); }
    .platform { font-weight: 800; text-transform: uppercase; font-size: 12px; color: var(--muted); }
    .offer-id { font-size: 18px; font-weight: 800; margin-top: 2px; }
    .pill {
      display: inline-flex;
      align-items: center;
      height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      background: #e8eee9;
      font-size: 12px;
      font-weight: 800;
      color: var(--ink);
      margin: 4px 4px 0 0;
      white-space: nowrap;
    }
    .pill.accept { background: #d9f0e5; color: var(--green); }
    .pill.decline { background: #f5dddd; color: var(--red); }
    .money { font-size: 22px; font-weight: 850; text-align: right; }
    .sub { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .bar-row { display: grid; grid-template-columns: 120px minmax(0, 1fr) 60px; align-items: center; gap: 8px; margin: 8px 0; }
    .bar-track { height: 9px; background: #e8ece8; border-radius: 999px; overflow: hidden; }
    .bar { height: 100%; background: var(--blue); width: 0%; }
    .map {
      height: 210px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background:
        linear-gradient(90deg, rgba(23,32,28,.05) 1px, transparent 1px),
        linear-gradient(rgba(23,32,28,.05) 1px, transparent 1px),
        #f4f6f2;
      background-size: 28px 28px;
      position: relative;
      overflow: hidden;
    }
    .map svg { position: absolute; inset: 0; width: 100%; height: 100%; }
    .route { fill: none; stroke: var(--blue); stroke-width: 5; stroke-linecap: round; }
    .heat { fill: var(--gold); opacity: .22; }
    .dot { fill: var(--green); stroke: #fff; stroke-width: 3; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 8px 6px; border-bottom: 1px solid var(--line); text-align: left; }
    th { color: var(--muted); font-size: 12px; }
    .status { color: var(--muted); font-size: 12px; margin-top: 8px; }
    .control-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin: 8px 0 12px;
    }
    .control-row input {
      width: 92px;
      height: 34px;
    }
    .live-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(90px, 1fr));
      gap: 8px;
      margin-bottom: 10px;
    }
    .live-stat {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 9px;
      background: #fbfcfa;
    }
    .live-stat .label { color: var(--muted); font-size: 11px; font-weight: 800; }
    .live-stat .value { font-size: 18px; font-weight: 850; margin-top: 2px; }
    .timeline {
      display: grid;
      gap: 8px;
      max-height: 360px;
      overflow: auto;
      padding-right: 4px;
    }
    .tick {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fbfcfa;
    }
    .tick-head {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: center;
      font-weight: 850;
      margin-bottom: 6px;
    }
    .decision-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .mini-offer {
      border: 1px solid var(--line);
      border-left: 4px solid var(--line);
      border-radius: 7px;
      padding: 8px;
      background: #fff;
      min-width: 0;
    }
    .mini-offer.accept { border-left-color: var(--green); }
    .mini-offer.decline { border-left-color: var(--red); }
    .mini-offer .title {
      font-weight: 850;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    @media (max-width: 980px) {
      .app { grid-template-columns: 1fr; }
      aside { position: static; height: auto; }
      .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .layout { grid-template-columns: 1fr; }
      .live-grid, .decision-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="brand">Delivery Profit Console</div>
      <div class="field">
        <label for="profile">Driver Profile</label>
        <select id="profile"></select>
      </div>
      <div class="field">
        <label for="demand">Demand</label>
        <input id="demand" type="range" min="0.6" max="2.2" step="0.05" value="1.15">
      </div>
      <div class="field">
        <label for="traffic">Traffic</label>
        <input id="traffic" type="range" min="0.8" max="1.8" step="0.05" value="1.05">
      </div>
      <div class="field">
        <label for="weather">Weather Risk</label>
        <input id="weather" type="range" min="0" max="1" step="0.05" value="0">
      </div>
      <div class="field">
        <label for="saturation">Courier Saturation</label>
        <input id="saturation" type="range" min="0.4" max="1.8" step="0.05" value="1">
      </div>
      <div class="field">
        <label for="expectedHourly">Expected Market Hourly</label>
        <input id="expectedHourly" type="number" min="10" max="80" step="1" value="28">
      </div>
      <div class="status" id="status">Loading</div>
    </aside>
    <main>
      <section class="metric-grid" id="metrics"></section>
      <section class="layout">
        <div>
          <div class="panel">
            <h2>Live Random Route Lab</h2>
            <div class="control-row">
              <button id="liveToggle" class="primary" type="button">Start</button>
              <button id="liveStep" type="button">Step</button>
              <button id="liveBurst" type="button">Burst</button>
              <button id="liveReset" type="button">Reset</button>
              <label for="liveSeed" style="margin:0">Seed</label>
              <input id="liveSeed" type="number" value="42">
            </div>
            <div class="live-grid" id="liveStats"></div>
            <div class="sub" id="liveNow">Waiting for first generated route batch.</div>
            <div class="timeline" id="liveTimeline"></div>
          </div>
          <div class="panel">
            <h2>Offer Stack</h2>
            <div class="offers" id="offers"></div>
          </div>
          <div class="panel">
            <h2>Strategy Backtest</h2>
            <table id="strategies"></table>
          </div>
        </div>
        <div>
          <div class="panel">
            <h2>Market Map</h2>
            <div class="map" aria-label="Route and market heat visualization">
              <svg viewBox="0 0 480 220" role="img">
                <circle class="heat" cx="105" cy="78" r="56"></circle>
                <circle class="heat" cx="328" cy="124" r="74"></circle>
                <path class="route" d="M72 168 C130 82, 206 162, 280 92 S392 92, 430 46"></path>
                <circle class="dot" cx="72" cy="168" r="9"></circle>
                <circle class="dot" cx="280" cy="92" r="9"></circle>
                <circle class="dot" cx="430" cy="46" r="9"></circle>
              </svg>
            </div>
          </div>
          <div class="panel">
            <h2>Predictions</h2>
            <div id="predictions"></div>
          </div>
          <div class="panel">
            <h2>Zone Ranking</h2>
            <table id="zones"></table>
          </div>
          <div class="panel">
            <h2>Calibration</h2>
            <div id="calibration"></div>
          </div>
        </div>
      </section>
    </main>
  </div>
  <script>
    const controls = ["profile", "demand", "traffic", "weather", "saturation", "expectedHourly"];
    const $ = (id) => document.getElementById(id);
    let liveTimer = null;

    async function loadProfiles() {
      const response = await fetch("/api/profiles");
      const data = await response.json();
      $("profile").innerHTML = data.profiles.map((profile) =>
        `<option value="${profile.name}">${profile.name.replaceAll("_", " ")}</option>`
      ).join("");
    }

    async function refresh() {
      const params = new URLSearchParams();
      controls.forEach((id) => params.set(id === "profile" ? "profile" : id, $(id).value));
      $("status").textContent = "Refreshing";
      const response = await fetch(`/api/state?${params.toString()}`);
      const data = await response.json();
      render(data);
      $("status").textContent = `Synced ${new Date().toLocaleTimeString()}`;
    }

    function livePayload(extra = {}) {
      return {
        profile: $("profile").value || "maximize_hourly",
        demand: Number($("demand").value),
        traffic: Number($("traffic").value),
        weather: Number($("weather").value),
        saturation: Number($("saturation").value),
        expectedHourly: Number($("expectedHourly").value),
        ...extra
      };
    }

    async function liveState() {
      const response = await fetch("/api/live/state");
      const data = await response.json();
      renderLive(data.live);
    }

    async function liveTick(count = 1) {
      const response = await fetch("/api/live/tick", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(livePayload({ count }))
      });
      const data = await response.json();
      renderLive(data.live);
    }

    async function liveReset() {
      const response = await fetch("/api/live/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seed: $("liveSeed").value })
      });
      const data = await response.json();
      renderLive(data.live);
    }

    function toggleLive() {
      if (liveTimer) {
        clearInterval(liveTimer);
        liveTimer = null;
        $("liveToggle").textContent = "Start";
        return;
      }
      liveTick();
      liveTimer = setInterval(() => liveTick(), 1400);
      $("liveToggle").textContent = "Stop";
    }

    function render(data) {
      const selected = data.recommendation.selected_offer_id || "Wait";
      $("metrics").innerHTML = [
        metric("Selected", selected),
        metric("Profile", data.profile.name.replaceAll("_", " ")),
        metric("Offers", data.summary.offer_count),
        metric("History", data.summary.delivery_count),
        metric("Best Strategy", data.report.best_strategy_name.replaceAll("_", " "))
      ].join("");

      $("offers").innerHTML = data.recommendation.ranked_offers.map((scored) => {
        const offer = scored.offer;
        const action = data.recommendation.platform_actions[offer.platform] || "keep_online";
        const reasons = scored.reasons.length ? scored.reasons.join(", ") : "clears active policy";
        return `<article class="offer ${scored.decision}">
          <div>
            <div class="platform">${offer.platform.replaceAll("_", " ")}</div>
            <div class="offer-id">${offer.offer_id}</div>
            <span class="pill ${scored.decision}">${scored.decision}</span>
            <span class="pill">${action.replaceAll("_", " ")}</span>
            <span class="pill">${scored.policy_name}</span>
            <div class="sub">${reasons}</div>
          </div>
          <div>
            <div class="money">$${scored.net_profit.toFixed(2)}</div>
            <div class="sub">${scored.profit_per_hour.toFixed(2)}/hr</div>
            <div class="sub">${scored.total_miles.toFixed(1)} mi · ${scored.total_minutes.toFixed(1)} min</div>
          </div>
        </article>`;
      }).join("");

      $("strategies").innerHTML = table(
        ["Strategy", "Profit", "Hourly", "Accepted", "Declined"],
        data.report.strategy_runs.map((run) => [
          run.strategy_name.replaceAll("_", " "),
          `$${run.gross_profit.toFixed(2)}`,
          `$${run.profit_per_hour.toFixed(2)}`,
          run.accepted_count,
          run.declined_count
        ])
      );

      $("predictions").innerHTML = data.predictions.map((prediction) => `
        <div class="bar-row">
          <div>${prediction.offer_id}</div>
          <div class="bar-track"><div class="bar" style="width:${Math.round(prediction.confidence * 100)}%"></div></div>
          <div>$${prediction.predicted_final_payout.toFixed(2)}</div>
        </div>
        <div class="sub">${prediction.predicted_actual_minutes.toFixed(1)} min · cancel ${Math.round(prediction.cancellation_risk * 100)}% · better offer ${Math.round(prediction.better_offer_probability * 100)}%</div>
      `).join("");

      $("zones").innerHTML = table(
        ["Zone", "Hourly"],
        data.zone_rankings.length ? data.zone_rankings.map((row) => [row[0], `$${row[1].toFixed(2)}`]) : [["No zone history", "$0.00"]]
      );

      $("calibration").innerHTML = `
        <div class="sub">Sample size ${data.calibration.sample_size}</div>
        ${Object.entries(data.calibration.platform_profiles).map(([platform, profile]) => `
          <div class="bar-row">
            <div>${platform.replaceAll("_", " ")}</div>
            <div class="bar-track"><div class="bar" style="width:${Math.round(profile.reliability * 100)}%"></div></div>
            <div>${Math.round(profile.reliability * 100)}%</div>
          </div>
        `).join("")}
      `;
    }

    function renderLive(live) {
      $("liveStats").innerHTML = [
        liveStat("Tick", live.tick),
        liveStat("Clock", `${live.elapsed_minutes.toFixed(1)}m`),
        liveStat("Profit", `$${live.net_profit.toFixed(2)}`),
        liveStat("Hourly", `$${live.profit_per_hour.toFixed(2)}`),
        liveStat("Accepted", live.accepted_count),
        liveStat("Declined", live.declined_count)
      ].join("");

      const latest = live.events.length ? live.events[live.events.length - 1] : null;
      $("liveNow").textContent = latest
        ? `Tick ${latest.tick}: ${latest.status.replaceAll("_", " ")} · selected ${latest.selected_offer_id || "none"} · active until ${latest.active_until_minute.toFixed(1)}m`
        : "Waiting for first generated route batch.";

      $("liveTimeline").innerHTML = live.events.slice().reverse().map((event) => {
        const ranked = event.recommendation.ranked_offers.slice(0, 3);
        return `<div class="tick">
          <div class="tick-head">
            <span>Tick ${event.tick} · ${event.timestamp_minutes.toFixed(1)}m</span>
            <span class="pill ${event.status === "accepted" ? "accept" : "decline"}">${event.status.replaceAll("_", " ")}</span>
          </div>
          <div class="sub">Selected ${event.selected_offer_id || "none"} · batch ${event.batch.length} routes · profit $${event.realized_profit.toFixed(2)}</div>
          <div class="decision-grid">
            ${ranked.map((scored) => {
              const offer = scored.offer;
              const reasons = scored.reasons.length ? scored.reasons.join(", ") : "clears policy";
              return `<div class="mini-offer ${scored.decision}">
                <div class="title">${offer.offer_id}</div>
                <div class="sub">${offer.platform.replaceAll("_", " ")} · ${offer.pickup_zone} to ${offer.dropoff_zone}</div>
                <span class="pill ${scored.decision}">${scored.decision}</span>
                <span class="pill">$${scored.net_profit.toFixed(2)}</span>
                <div class="sub">${scored.profit_per_hour.toFixed(2)}/hr · ${scored.total_miles.toFixed(1)} mi</div>
                <div class="sub">${reasons}</div>
              </div>`;
            }).join("")}
          </div>
        </div>`;
      }).join("");
    }

    function metric(label, value) {
      return `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div></div>`;
    }

    function liveStat(label, value) {
      return `<div class="live-stat"><div class="label">${label}</div><div class="value">${value}</div></div>`;
    }

    function table(headers, rows) {
      return `<thead><tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody>`;
    }

    loadProfiles().then(() => {
      controls.forEach((id) => $(id).addEventListener("input", refresh));
      $("liveToggle").addEventListener("click", toggleLive);
      $("liveStep").addEventListener("click", () => liveTick());
      $("liveBurst").addEventListener("click", () => liveTick(8));
      $("liveReset").addEventListener("click", liveReset);
      refresh();
      liveState();
    });
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
