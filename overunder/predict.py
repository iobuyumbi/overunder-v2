"""Build Over 2.5 picks from fixtures + team histories.

Symmetry-aware filtering:
  1. VETOES (hard blocks V1/V2/V3) — drop pick outright, no exceptions
  2. FOUR-LEG CONSISTENCY — scoring legs (H,A) AND opponent-concession legs
     (D,E) must both show strength. A Poisson hot lambda with cold defence
     legs is a false positive ('streak meets wall' loss).
  3. Blended confidence — Poisson base, weighted by leg-consistency ratio,
     not just raw check count.
"""

from .config import (DEFAULT_ODDS, KELLY_FRACTION, MAX_STAKE_PCT, O25_MIN_CONFIDENCE,
                     PREMIUM_TIER)
from .rules import (CHECK_NAMES, VETO_KEYS, any_veto_failed, poisson_over25,
                    run_checks, xg_forecast)

SCORING_LEGS = ("H1", "H2", "H3", "H4", "A1", "A2", "A3", "A4")
DEFENCE_LEGS = ("D1", "D2", "D3", "D4", "E1", "E2", "E3", "E4")
FORM_GATES   = ("S1", "S2", "S3")


def _leg_ratio(checks, keys):
    vals = [checks[k] for k in keys if k in checks]
    return sum(vals) / len(vals) if vals else 0.0


def build_pick(fixture, provider, odds=DEFAULT_ODDS):
    home_ms = provider.team_matches(fixture["home"])
    away_ms = provider.team_matches(fixture["away"])
    checks = run_checks(home_ms, away_ms)
    vetoed = any_veto_failed(checks)
    veto_reasons = [CHECK_NAMES[k] for k in VETO_KEYS if not checks.get(k, True)]

    passed = sum(checks.values())
    p25, lam_h, lam_a = poisson_over25(home_ms, away_ms)

    scoring_r = _leg_ratio(checks, SCORING_LEGS)
    defence_r = _leg_ratio(checks, DEFENCE_LEGS)
    form_r    = _leg_ratio(checks, FORM_GATES)
    leg_consistency = (0.40 * scoring_r + 0.40 * defence_r + 0.20 * form_r)

    # Penalise imbalance: e.g. scoring=1.0 defence=0.2 -> mean 0.6 -> penalty
    # pushes it low, so a one-sided profile never looks confident.
    imbalance = abs(scoring_r - defence_r)
    consistency = max(0.0, leg_consistency * (1.0 - 0.5 * imbalance))

    # Base = Poisson, nudge = leg-consistency. Vetoed = floor the confidence
    # so callers can still see it but predict_day will drop via threshold + flag.
    base = p25 if not vetoed else max(0.05, p25 * 0.35)
    conf = min(0.98, base * (0.55 + 0.45 * consistency))
    conf = round(conf, 3)

    ev = round(conf * (odds - 1) - (1 - conf), 3)
    stake = 0.0 if (ev <= 0 or vetoed) else round(min(MAX_STAKE_PCT, ev * KELLY_FRACTION), 1)
    tier = "🔥 Premium" if (conf >= PREMIUM_TIER and not vetoed) else "✅ Solid"
    lo, hi = xg_forecast(lam_h, lam_a)
    missed = [f"{CHECK_NAMES[k]} (failed)" for k, v in checks.items() if not v]

    leg_breakdown = {
        "scoring": round(scoring_r, 2),
        "defence": round(defence_r, 2),
        "form":    round(form_r, 2),
        "imbalance": round(imbalance, 2),
    }

    return {
        "date": fixture["date"], "league": fixture["league"],
        "home": fixture["home"], "away": fixture["away"],
        "market": "over", "line": 2.5,
        "confidence": conf, "model_p": round(p25, 3),
        "checks_passed": passed, "checks_total": len(checks),
        "missed": missed, "ev": ev, "edge_pct": round(ev * 100, 1),
        "stake_pct": stake, "odds": odds, "tier": tier,
        "xg": [lo, hi],
        "vetoed": vetoed,
        "veto_reasons": veto_reasons,
        "legs": leg_breakdown,
    }


def predict_day(provider, day=None, odds=DEFAULT_ODDS, min_conf=O25_MIN_CONFIDENCE):
    picks = []
    for fx in provider.fixtures(day):
        p = build_pick(fx, provider, odds=odds)
        if p["vetoed"]:
            continue
        if p["confidence"] < min_conf:
            continue
        picks.append(p)
    picks.sort(key=lambda p: -p["confidence"])
    for i, p in enumerate(picks, 1):
        p["num"] = i
    return picks
