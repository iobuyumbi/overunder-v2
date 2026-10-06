"""League health: track leagues where our patterns keep losing and CAUTION
on them -- never block.

compute_health() reads settled history over a trailing window, groups results
by (league, market), and flags a pair as CAUTION once it has enough sample and
is unprofitable at the recorded odds. Live prediction (cmd_predict) tags those
picks with a `league_caution` warning ("our patterns don't suit this match")
but still emits them -- the user decides. Backtests never apply this at all
(it is computed from results that would not have existed at the time ->
lookahead bias).

Manual overrides (env, comma-separated league names):
  OU_LEAGUE_BLOCK="League A,League B"   always caution, all markets
  OU_LEAGUE_ALLOW="League C"            never auto-caution (protected)
  OU_LEAGUE_AVOID_DISABLE=1             turn the whole caution system off
"""

import datetime
import html
import json
import os
import time

from .config import (DATA_DIR, LEAGUE_HEALTH_WINDOW_DAYS,
                     LEAGUE_HEALTH_MIN_PICKS, LEAGUE_HEALTH_DEV_PCT,
                     LEAGUE_HEALTH_FLOOR_PCT, MARKET_BASELINE_WIN_PCT,
                     LEAGUE_BLOCK, LEAGUE_ALLOW)
from . import history as hist


def league_key(name):
    """Case/entity-insensitive league identity for matching fixtures to history."""
    return html.unescape(name or "").strip().casefold()


def health_path():
    return os.path.join(DATA_DIR, "league_health.json")


def compute_health(window_days=None, min_picks=None, today=None):
    """{league_key: {market: {n, w, l, win_pct, baseline, dev_pct, profit,
    caution, caution_reasons}}} over the trailing window.

    Caution gate (ANY of these triggers, provided n >= min_picks and league
    is NOT in OU_LEAGUE_ALLOW):
      1. profit < 0                                   -- money loser
      2. win_pct <= baseline - LEAGUE_HEALTH_DEV_PCT  -- "doesn't go with us"
      3. win_pct <= LEAGUE_HEALTH_FLOOR_PCT           -- absolute loser floor

    Reasons are recorded so predict/report can say EXACTLY why the pick is
    cautioned (user workflow: "calculate loses deviating from our picks and
    say they dont go with us well").
    """
    window_days = LEAGUE_HEALTH_WINDOW_DAYS if window_days is None else window_days
    min_picks = LEAGUE_HEALTH_MIN_PICKS if min_picks is None else min_picks
    today = today or datetime.date.today().isoformat()
    cutoff = (datetime.date.fromisoformat(today)
              - datetime.timedelta(days=window_days)).isoformat()
    health = {}
    for rec in hist._load()["settled"]:
        if rec.get("result") not in ("W", "L"):
            continue                                # voids / pending don't count
        if rec.get("date", "9999") < cutoff:
            continue                                # trailing window only
        lg = league_key(rec.get("league"))
        if not lg:
            continue
        mk = rec.get("market", "?")
        g = health.setdefault(lg, {}).setdefault(
            mk, {"n": 0, "w": 0, "l": 0, "profit": 0.0})
        g["n"] += 1
        g["w" if rec["result"] == "W" else "l"] += 1
        g["profit"] = round(g["profit"] + (rec.get("profit") or 0.0), 2)
    allow = {league_key(x) for x in LEAGUE_ALLOW}
    for lg, mkts in health.items():
        for mkt, g in mkts.items():
            n = g["n"]
            g["win_pct"] = round(100 * g["w"] / n, 1) if n else 0.0
            baseline = MARKET_BASELINE_WIN_PCT.get(mkt)
            g["baseline"] = baseline
            g["dev_pct"] = round(g["win_pct"] - baseline, 1) if baseline else None
            reasons = []
            triggered = False
            if n >= min_picks and lg not in allow:
                if g["profit"] < 0:
                    reasons.append("unprofitable (profit {:+.2f}u on {} picks)"
                                   .format(g["profit"], n))
                    triggered = True
                if baseline is not None:
                    if g["win_pct"] <= baseline - LEAGUE_HEALTH_DEV_PCT:
                        reasons.append(
                            "win-rate deviates {:.1f}pp below our {:>5.1f}% "
                            "target for {} (actual {:.1f}%) -- doesn't go "
                            "with our picks well"
                            .format(baseline - g["win_pct"], baseline, mkt,
                                    g["win_pct"]))
                        triggered = True
                if g["win_pct"] <= LEAGUE_HEALTH_FLOOR_PCT:
                    reasons.append(
                        "win-rate {:.1f}% is below the {:.0f}% absolute "
                        "caution floor"
                        .format(g["win_pct"], LEAGUE_HEALTH_FLOOR_PCT))
                    triggered = True
            g["caution_reasons"] = reasons
            g["caution"] = triggered
    return health


def save_health(health, window_days=None, min_picks=None):
    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {
        "computed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": (LEAGUE_HEALTH_WINDOW_DAYS if window_days is None
                        else window_days),
        "min_picks": LEAGUE_HEALTH_MIN_PICKS if min_picks is None else min_picks,
        "leagues": health,
    }
    with open(health_path(), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return health_path()


def load_health():
    """Leagues dict from the last saved computation; {} if missing/corrupt."""
    try:
        with open(health_path(), encoding="utf-8") as f:
            d = json.load(f)
        leagues = d.get("leagues", {})
        return leagues if isinstance(leagues, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def caution_sets(health=None):
    """(pair_stats, blocked): pair_stats = {(league_key, market): stats} for
    pairs to caution on, blocked = {league_key} to caution on entirely
    (manual OU_LEAGUE_BLOCK)."""
    health = load_health() if health is None else health
    pair_stats = {(lg, mk): g for lg, mkts in health.items()
                  for mk, g in mkts.items()
                  if isinstance(g, dict) and g.get("caution")}
    blocked = {league_key(x) for x in LEAGUE_BLOCK}
    return pair_stats, blocked
