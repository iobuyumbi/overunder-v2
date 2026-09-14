"""Build Over 2.5 picks from fixtures + team histories."""

from .config import (DEFAULT_ODDS, KELLY_FRACTION, MAX_STAKE_PCT, O25_MIN_CONFIDENCE,
                     PREMIUM_TIER)
from .rules import CHECK_NAMES, poisson_over25, run_checks, xg_forecast


def build_pick(fixture, provider, odds=DEFAULT_ODDS):
    home_ms = provider.team_matches(fixture["home"])
    away_ms = provider.team_matches(fixture["away"])
    checks = run_checks(home_ms, away_ms)
    passed = sum(checks.values())
    p25, lam_h, lam_a = poisson_over25(home_ms, away_ms)

    # blend: Poisson is the base rate, rule pass-ratio nudges it
    conf = min(0.98, p25 * (0.70 + 0.30 * passed / len(checks)))
    conf = round(conf, 3)

    ev = round(conf * (odds - 1) - (1 - conf), 3)          # per $1
    stake = 0.0 if ev <= 0 else round(min(MAX_STAKE_PCT, ev * KELLY_FRACTION), 1)
    tier = "🔥 Premium" if conf >= PREMIUM_TIER else "✅ Solid"
    lo, hi = xg_forecast(lam_h, lam_a)
    missed = [f"{CHECK_NAMES[k]} (failed)" for k, v in checks.items() if not v]

    return {
        "date": fixture["date"], "league": fixture["league"],
        "home": fixture["home"], "away": fixture["away"],
        "market": "over", "line": 2.5,
        "confidence": conf, "model_p": round(p25, 3),
        "checks_passed": passed, "checks_total": len(checks),
        "missed": missed, "ev": ev, "edge_pct": round(ev * 100, 1),
        "stake_pct": stake, "odds": odds, "tier": tier,
        "xg": [lo, hi],
    }


def predict_day(provider, day=None, odds=DEFAULT_ODDS, min_conf=O25_MIN_CONFIDENCE):
    picks = []
    for fx in provider.fixtures(day):
        p = build_pick(fx, provider, odds=odds)
        if p["confidence"] >= min_conf:
            picks.append(p)
    picks.sort(key=lambda p: -p["confidence"])
    for i, p in enumerate(picks, 1):
        p["num"] = i
    return picks
