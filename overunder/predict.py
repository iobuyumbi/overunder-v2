"""Build picks for any supported market from fixtures + team histories.

Markets: 'over' (Over 2.5), 'btts' (both teams to score), 'home' (home win).
One engine, one report, one settlement path -- not three separate scripts."""

from .config import (DEFAULT_ODDS, KELLY_FRACTION, MAX_STAKE_PCT, O25_MIN_CONFIDENCE,
                     PREMIUM_TIER)
from .rules import CHECK_NAMES, lambdas, market_probs, xg_forecast

MARKET_LABEL = {"over": "Over 2.5", "under": "Under 2.5", "btts": "BTTS",
                "no_btts": "BTTS No", "home": "Home win",
                "home_sc": "Home team to score", "away_sc": "Away team to score"}

# which of the 13 checks count as 'core' per market (for the missed-list flavor)
CORE_CHECKS = {
    "over":    ["H1", "H2", "H3", "A1", "A2", "A3", "A4", "A5", "H10", "A11", "H2H"],
    "under":   ["H1u", "H2u", "H3u", "A1u", "A2u", "A3u", "A4u", "A5u",
                "H10u", "A11u", "H2H"],
    "btts":    ["H4", "H5", "H6", "A3", "A6", "A7", "A8", "H8", "H9", "A9", "A10",
                "H11", "A12", "A13", "H12", "H2H"],
    "no_btts": ["H4n", "H5n", "H6n", "H8n", "H9n", "A3n", "A6n", "A7n", "A8n",
                "A9n", "A10n", "H2H"],
    "home":    ["H1", "H3", "H6", "H7", "S6", "A9", "A10", "H2H"],
    "home_sc": ["H1", "H6", "H7", "S6", "A9", "H11", "A12", "H2H"],
    "away_sc": ["A1", "A3", "A8", "S6", "H8", "A13", "H12", "H2H"],
}


def build_pick(fixture, provider, market="over", odds=DEFAULT_ODDS, before=None):
    # `before` = ISO date; only matches strictly before it count toward form.
    # Defaults to the fixture's own day so nothing from match day leaks in.
    before = before if before is not None else fixture.get("date")
    home_ms = provider.team_matches(fixture["home"], before=before)
    away_ms = provider.team_matches(fixture["away"], before=before)
    from .rules import run_checks
    checks = run_checks(home_ms, away_ms, market=market,
                        home_name=fixture["home"], away_name=fixture["away"])
    passed = sum(checks.values())
    probs = market_probs(home_ms, away_ms)
    p = probs[market]
    lam_h, lam_a = lambdas(home_ms, away_ms)

    def gpg(ms, venue=None, key="gf"):
        sel = [m for m in ms if venue is None or m["venue"] == venue]
        return round(sum(m[key] for m in sel) / len(sel), 2) if sel else 0.0

    conf = min(0.98, p * (0.70 + 0.30 * passed / len(checks)))
    conf = round(conf, 3)
    ev = round(conf * (odds - 1) - (1 - conf), 3)
    stake = 0.0 if ev <= 0 else round(min(MAX_STAKE_PCT, ev * KELLY_FRACTION), 1)
    tier = "🔥 Premium" if conf >= PREMIUM_TIER else "✅ Solid"
    lo, hi = xg_forecast(lam_h, lam_a)

    core = CORE_CHECKS.get(market, [])
    missed = [f"{CHECK_NAMES[k]} (failed)" for k in core if not checks[k]]

    return {
        "date": fixture["date"], "league": fixture["league"],
        "home": fixture["home"], "away": fixture["away"],
        "market": market, "label": MARKET_LABEL[market],
        "line": 2.5 if market in ("over", "under") else None,
        "confidence": conf, "model_p": round(p, 3),
        "checks_passed": passed, "checks_total": len(checks),
        "missed": missed, "ev": ev, "edge_pct": round(ev * 100, 1),
        "stake_pct": stake, "odds": odds, "tier": tier,
        "xg": [lo, hi],
        "home_attack": gpg(home_ms, "H"), "home_concede": gpg(home_ms, "H", "ga"),
        "away_attack": gpg(away_ms, "A"), "away_concede": gpg(away_ms, "A", "ga"),
        "home_gpg_all": gpg(home_ms), "away_gpg_all": gpg(away_ms),
        "home_concede_all": gpg(home_ms, None, "ga"),
        "away_concede_all": gpg(away_ms, None, "ga"),
    }


def predict_day(provider, day=None, markets=("over",), odds=DEFAULT_ODDS,
                min_conf=O25_MIN_CONFIDENCE):
    picks = []
    for fx in provider.fixtures(day):
        for mkt in markets:
            try:
                p = build_pick(fx, provider, market=mkt, odds=odds)
            except Exception:
                continue
            if p["confidence"] >= min_conf:
                picks.append(p)
    # number within each market, ordered by confidence
    for mkt in markets:
        group = sorted([p for p in picks if p["market"] == mkt],
                       key=lambda p: -p["confidence"])
        for i, p in enumerate(group, 1):
            p["num"] = i
    picks.sort(key=lambda p: (list(markets).index(p["market"]), -p["confidence"]))
    return picks
