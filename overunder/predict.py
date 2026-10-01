"""Build picks for any supported market from fixtures + team histories.

Markets (10 total): over (Over 2.5), over15 (Over 1.5), under (Under 2.5),
under35 (Under 3.5), btts, no_btts, home, home_sc, away_sc, home_dw.

Confidence is a blended score: 70% Poisson market-probability * 30% rule-check
pass-ratio, clamped to <= 0.98.  The pure check_ratio (= passed / total) is
also exposed for inspection.  Gates come from config.MARKET_MIN_CONF.

One engine, one report, one settlement path."""

from .config import (DEFAULT_ODDS, KELLY_FRACTION, MARKET_MIN_CONF, MAX_STAKE_PCT,
                     O25_MIN_CONFIDENCE, PREMIUM_TIER, MARKET_PREMIUM, MARKET_SOLID,
                     RULES_VERSION, CACHE_DIR, FREQ_CFG,
                     LEAGUE_AVG_HOME_GOALS, LEAGUE_AVG_AWAY_GOALS,
                     PREDICT_CACHE_TTL_HOURS, CACHE_DISABLE)
from .rules import CHECK_NAMES, lambdas, market_probs, xg_forecast
from .teams import normalize
import json
import os
import time as _time

MARKET_LABEL = {"over": "Over 2.5", "under": "Under 2.5", "btts": "BTTS",
                "no_btts": "BTTS No", "home": "Home win",
                "home_sc": "Home team to score", "away_sc": "Away team to score",
                "over15": "Over 1.5", "under35": "Under 3.5",
                "home_dw": "Home or draw"}

# which checks count as 'core' per market (for the missed-list flavor).
# Every key here MUST exist in that market's check dict in rules.run_checks.
# DESIGN NOTE: btts = home_sc U away_sc (literal set union in run_checks)
#   home_sc CORE_CHECKS + away_sc CORE_CHECKS minus S6 overlap = btts CORE_CHECKS
CORE_CHECKS = {
    "over":    ["H1", "A1", "H6", "A3", "A8", "A9", "H8", "A11", "H10",
                "HB", "AB", "H2", "A4", "H2H"],
    "under":   ["H1u", "H2u", "H3u", "A1u", "A3u", "A4u", "A5u",
                "H10u", "A11u", "H2H"],
    "btts":    ["H6", "H7", "A9", "A12",
                "A3", "A13", "H8", "H12", "H2H"],
    "no_btts": ["H4n", "H5n", "H6n", "H8n", "H9n", "A3n", "A6n", "A7n", "A8n",
                "A9n", "A10n", "DOM", "H2H"],
    "home":    ["H6", "H7", "H16",
                "A9", "A12", "A16", "H14", "H15", "H2H"],
    "home_sc": ["H6", "H7", "S6", "A9", "A12", "H2H"],
    "away_sc": ["A3", "A13", "S6", "H8", "H12", "H2H"],
    "over15":  ["H2", "H3", "A3", "A4", "A5", "A8", "HB", "AB", "H2H"],
    "under35": ["H1u", "H2u", "H3u", "A1u", "A3u", "A4u", "A5u",
                "H10u", "A11u", "H2H"],
    "home_dw": ["H6", "H7", "A9", "A12",
                "H14", "H15", "A14", "A15", "A17", "A18", "H2H"],
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

    total = len(checks)
    check_ratio = round(passed / total, 3) if total else 0.0
    # Confidence = blended score: Poisson probability p (70% weight) scaled by
    # rule-check pass ratio (30% weight), clamped so no pick claims perfection.
    conf = min(0.98, p * (0.70 + 0.30 * check_ratio)) if total else 0.0
    conf = round(conf, 3)
    # Resolve odds: scalar applies to all markets, dict is per-market lookup.
    if isinstance(odds, dict):
        odds_v = float(odds.get(market, DEFAULT_ODDS))
    else:
        odds_v = float(odds)
    ev = round(conf * (odds_v - 1) - (1 - conf), 3)
    stake = 0.0 if ev <= 0 else round(min(MAX_STAKE_PCT, ev * KELLY_FRACTION), 1)
    tier_bar = MARKET_PREMIUM.get(market, PREMIUM_TIER)
    tier = "🔥 Premium" if conf >= tier_bar else "✅ Solid"
    lo, hi = xg_forecast(lam_h, lam_a)

    core = CORE_CHECKS.get(market, [])
    missed = [f"{CHECK_NAMES[k]} (failed)" for k in core if not checks[k]]

    line_by_market = {"over": 2.5, "under": 2.5, "over15": 1.5,
                      "under35": 3.5, "btts": None, "no_btts": None,
                      "home": None, "home_sc": None, "away_sc": None,
                      "home_dw": None}
    return {
        "date": fixture["date"], "league": fixture["league"],
        "home": fixture["home"], "away": fixture["away"],
        "market": market, "label": MARKET_LABEL[market],
        "line": line_by_market.get(market),
        "confidence": conf, "model_p": round(p, 3),
        "checks_passed": passed, "checks_total": total,
        "check_ratio": check_ratio,
        "missed": missed, "ev": ev, "edge_pct": round(ev * 100, 1),
        "stake_pct": stake, "odds": odds_v, "tier": tier,
        "xg": [lo, hi],
        "home_attack": gpg(home_ms, "H"), "home_concede": gpg(home_ms, "H", "ga"),
        "away_attack": gpg(away_ms, "A"), "away_concede": gpg(away_ms, "A", "ga"),
        "home_gpg_all": gpg(home_ms), "away_gpg_all": gpg(away_ms),
        "home_concede_all": gpg(home_ms, None, "ga"),
        "away_concede_all": gpg(away_ms, None, "ga"),
    }


def predict_day(provider, day=None, markets=("over",), odds=DEFAULT_ODDS,
                min_conf=O25_MIN_CONFIDENCE, market_min_conf=None,
                league_caution=None):
    """market_min_conf: per-market gates; defaults to config.MARKET_MIN_CONF.
    Pass an empty dict to use the flat min_conf only (backtests, demos).

    league_caution: optional (pair_stats, blocked) from leagues.caution_sets().
    Matching picks are TAGGED with a `league_caution` warning ("our patterns
    don't suit this match") -- never skipped. LIVE runs only: backtests must
    not pass this (the caution list is computed from results that did not
    exist at the time -> lookahead bias).

    ON-DISK RERUN CACHE: if the same (day, fixtures, markets, odds) is
    requested within PREDICT_CACHE_TTL_HOURS (default: fixture HTML TTL), the
    second+ run returns instantly without re-querying team histories or the
    rule engine.  Disable entirely with OU_CACHE_DISABLE=1."""
    mmc = MARKET_MIN_CONF if market_min_conf is None else market_min_conf
    # -- cache lookup (deterministic signature of this predict_day invocation)
    day_actual = day or _time.strftime("%Y-%m-%d")
    caution_sig = ()
    if league_caution:
        pair_stats, blocked = league_caution
        caution_sig = (tuple(sorted(pair_stats)), tuple(sorted(blocked)))
    if not CACHE_DISABLE:
        try:
            fixtures = provider.fixtures(day)
        except Exception:
            fixtures = []
        fx_sig = tuple(sorted(
            (normalize(fx["home"]), normalize(fx["away"]),
             fx.get("league", "")) for fx in fixtures))
        mkts_sig = tuple(sorted(markets))
        odds_sig = tuple(sorted(odds.items())) if isinstance(odds, dict) \
            else tuple(odds) if isinstance(odds, (list, tuple)) else (odds,)
        mmc_sig = tuple(sorted(mmc.items()))
        prem_sig = tuple(sorted(MARKET_PREMIUM.items()))
        solid_sig = tuple(sorted(MARKET_SOLID.items()))
        freq_sig = tuple(sorted((k, v["full"], v["short"])
                                for k, v in FREQ_CFG.items()))
        tunables_sig = (PREMIUM_TIER, KELLY_FRACTION, MAX_STAKE_PCT,
                        LEAGUE_AVG_HOME_GOALS, LEAGUE_AVG_AWAY_GOALS,
                        DEFAULT_ODDS)
        cache_key = (day_actual, fx_sig, mkts_sig, odds_sig, min_conf, mmc_sig,
                     prem_sig, solid_sig, freq_sig, tunables_sig, RULES_VERSION, caution_sig,
                     type(provider).__name__)
        cache_path = os.path.join(CACHE_DIR, f"predict_day_{day_actual}.json")
        ttl = PREDICT_CACHE_TTL_HOURS * 3600
        import hashlib
        key_hash = hashlib.sha1(json.dumps(cache_key, sort_keys=True)
                                 .encode("utf-8")).hexdigest()
        if os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as f:
                    cache_bucket = json.load(f)
                rec = cache_bucket.get(key_hash)
                if rec:
                    age = _time.time() - rec.get("t", 0)
                    if 0 <= age <= ttl:
                        return rec["picks"]
            except (json.JSONDecodeError, OSError, ValueError, KeyError):
                pass
    else:
        fixtures = provider.fixtures(day)

    # dedupe fixtures: some day pages list the same match twice (two
    # competition rows), which would otherwise emit identical picks twice
    seen_fx, uniq_fx = set(), []
    for fx in fixtures:
        k = (normalize(fx["home"]), normalize(fx["away"]), fx.get("league", ""))
        if k not in seen_fx:
            seen_fx.add(k)
            uniq_fx.append(fx)
    fixtures = uniq_fx

    picks = []
    for fx in fixtures:
        for mkt in markets:
            try:
                p = build_pick(fx, provider, market=mkt, odds=odds)
            except Exception:
                continue
            thr = mmc.get(mkt) or min_conf
            # Solid filter is ONLY active in production mode, meaning the
            # caller did NOT pass an explicit market_min_conf override
            # (empty dict = demo/backtest flat-gate; custom dict = per-market
            # experiment where caller's thr is already the intended floor).
            if market_min_conf is None:
                solid_thr = MARKET_SOLID.get(mkt, thr)
            else:
                solid_thr = thr
            if p["confidence"] >= solid_thr:
                if league_caution:
                    from .leagues import league_key
                    pair_stats, blocked = league_caution
                    lgk = league_key(fx.get("league"))
                    if lgk in blocked:
                        p["league_caution"] = (
                            "manually flagged league -- "
                            "our patterns may not suit this match")
                    elif (lgk, mkt) in pair_stats:
                        g = pair_stats[(lgk, mkt)]
                        p["league_caution"] = (
                            f"{mkt} in this league: {g['w']}W-{g['l']}L "
                            f"{g['profit']:+.1f}u lately -- "
                            f"our patterns may not suit this match")
                picks.append(p)
    # number within each market, ordered by confidence
    for mkt in markets:
        group = sorted([p for p in picks if p["market"] == mkt],
                       key=lambda p: -p["confidence"])
        for i, p in enumerate(group, 1):
            p["num"] = i
    picks.sort(key=lambda p: (list(markets).index(p["market"]), -p["confidence"]))

    # -- cache persist (same deterministic signature)
    if not CACHE_DISABLE:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            try:
                with open(cache_path, encoding="utf-8") as f:
                    cache_bucket = json.load(f)
                if not isinstance(cache_bucket, dict):
                    cache_bucket = {}
            except (json.JSONDecodeError, OSError, ValueError):
                cache_bucket = {}
            # prune expired records opportunistically
            now = _time.time()
            pruned = {k: v for k, v in cache_bucket.items()
                      if 0 <= now - v.get("t", now + 1) <= ttl}
            pruned[key_hash] = {"t": int(now), "picks": picks}
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(pruned, f)
        except OSError:
            pass
    return picks
