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
                     PREDICT_CACHE_TTL_HOURS, CACHE_DISABLE,
                     is_international_tournament, INTERNATIONAL_SKIP_MARKETS)
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
#
# Over/Over15 (rewritten 2026-10-03.5): symmetric attack⇄leakage pairs —
# home_sc profile (H6/H7 ATT + A9/A12 LEAK) + away_sc profile (A3/A8 ATT +
# H8/H12 LEAK) + pure over-rate 50% bars (H2/H3 + A4/A5) + H2H.
# Over 2.5 must also pass O_PATH: at least one full attack-v-leakage pair, or
# open-game evidence paired with the other team's full scoring/conceding form.
# Negative markets (under/under35/no_btts) use INDEPENDENT check IDs with
# semantic prefixes UH_/UA_/U35_/NH_/NA_/NB_ (not u/n suffix mirrors).
CORE_CHECKS = {
    "over":    ["H6", "H7", "A9", "A12",
                "A3", "A8", "H8", "H12",
                "H2", "H3", "A4", "A5", "O_PATH", "H2H"],
    "under":   ["UH_BLK", "UH_CS", "UH_BLK_O", "UH_CS_O",
                "UH_GA_L3",
                "UA_BLK", "UA_CS", "UA_BLK_O", "UA_CS_O",
                "UA_GA_L3",
                "UH_UND_O", "UA_UND_O",
                "H2H"],
    "btts":    ["H6", "H7", "A9", "A12",
                "A3", "A13", "H8", "H12", "H2H"],
    "no_btts": ["NH_BL", "NH_BL_OWN", "NH_BL_O",
                "NA_BL", "NA_BL_OWN", "NA_BL_O",
                "NH_BTTS_O", "NA_BTTS_O",
                "NB_BOTH", "NB_LAM",
                "H2H"],
    "home":    ["H6", "H7", "A9", "A12", "H14", "A16", "H16", "H2H"],
    "home_sc": ["H6", "H7", "S6", "A9", "A12", "H2H"],
    "away_sc": ["A3", "A13", "S6", "H8", "H12", "H2H"],
    "over15":  ["H6", "A9", "A12",
                "A3", "A8", "H8", "H12",
                "H2", "H3", "A4", "A5", "H2H"],
    "under35": ["UH_BLK", "UH_CS",
                "UA_BLK", "UA_CS",
                "U35_NOHI", "U35_NOAI", "U35_NOHI_O", "U35_NOAI_O",
                "UH_UND", "UA_UND", "UH_UND_O", "UA_UND_O",
                "H2H"],
    "home_dw": ["H6", "H7", "A9", "A12",
                "H14", "H15", "A14", "A15", "A17", "A18", "H2H"],
}

# These scored/conceded patterns are eligibility requirements, not soft votes
# in the confidence blend. FREQ_CFG supplies the active per-category bars.
REQUIRED_MARKET_CHECKS = {
    "home": ("H6", "H7", "A9", "A12", "H14", "A16"),
    "home_dw": ("H6", "H7", "A9", "A12", "H14", "A14"),
    "home_sc": ("H6", "H7", "A9", "A12"),
    "away_sc": ("A3", "A13", "H8", "H12"),
    "btts": ("H6", "H7", "H8", "H12", "A3", "A13", "A9", "A12"),
}


def build_pick(fixture, provider, market="over", odds=DEFAULT_ODDS, before=None,
               include_gate_audit=False):
    """If include_gate_audit=True, the returned dict gains audit_* fields:
      - audit_required_failed: list[str] of REQUIRED check IDs that failed
      - audit_optional_failed: list[str] of CORE (non-required) check IDs that failed
      - audit_over_path_failed: bool, True if market=="over" and over_path_passes returned False
      - audit_all_checks: {check_id: bool} full run_checks dict (for custom drill-down)
    Used by `fixture-audit` so users can see exactly why a market was gated out.
    """
    before = before if before is not None else fixture.get("date")
    home_ms = provider.team_matches(fixture["home"], before=before)
    away_ms = provider.team_matches(fixture["away"], before=before)
    lam_h, lam_a = lambdas(home_ms, away_ms)
    from .rules import over_path_passes, run_checks
    checks = run_checks(home_ms, away_ms, market=market,
                        home_name=fixture["home"], away_name=fixture["away"],
                        lam_h=lam_h, lam_a=lam_a)
    over_path_passed = (over_path_passes(home_ms, away_ms, checks)
                        if market == "over" else True)
    required = list(REQUIRED_MARKET_CHECKS.get(market, ()))
    required_set = set(required)
    required_checks_passed = all(checks[k] for k in required)
    passed = sum(checks.values())
    probs = market_probs(home_ms, away_ms)
    p = probs[market]

    def gpg(ms, venue=None, key="gf"):
        sel = [m for m in ms if venue is None or m["venue"] == venue]
        return round(sum(m[key] for m in sel) / len(sel), 2) if sel else 0.0

    total = len(checks)
    check_ratio = round(passed / total, 3) if total else 0.0
    conf = min(0.98, p * (0.70 + 0.30 * check_ratio)) if total else 0.0
    conf = round(conf, 3)
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
    missed = [f"{CHECK_NAMES[k]} (failed)" for k in core
              if (not over_path_passed if k == "O_PATH" else not checks[k])]

    line_by_market = {"over": 2.5, "under": 2.5, "over15": 1.5,
                      "under35": 3.5, "btts": None, "no_btts": None,
                      "home": None, "home_sc": None, "away_sc": None,
                      "home_dw": None}
    out = {
        "date": fixture["date"], "league": fixture["league"],
        "home": fixture["home"], "away": fixture["away"],
        "market": market, "label": MARKET_LABEL[market],
        "rules_version": RULES_VERSION,
        "line": line_by_market.get(market),
        "confidence": conf, "model_p": round(p, 3),
        "checks_passed": passed, "checks_total": total,
        "check_ratio": check_ratio,
        "over_path_passed": over_path_passed,
        "required_checks_passed": required_checks_passed,
        "missed": missed, "ev": ev, "edge_pct": round(ev * 100, 1),
        "stake_pct": stake, "odds": odds_v, "tier": tier,
        "xg": [lo, hi],
        "home_attack": gpg(home_ms, "H"), "home_concede": gpg(home_ms, "H", "ga"),
        "away_attack": gpg(away_ms, "A"), "away_concede": gpg(away_ms, "A", "ga"),
        "home_gpg_all": gpg(home_ms), "away_gpg_all": gpg(away_ms),
        "home_concede_all": gpg(home_ms, None, "ga"),
        "away_concede_all": gpg(away_ms, None, "ga"),
    }
    if include_gate_audit:
        req_fail = [cid for cid in required if not checks.get(cid, False)]
        opt_fail = [cid for cid in core
                    if cid not in required_set and cid != "O_PATH"
                    and not checks.get(cid, False)]
        out["audit_required_failed"] = req_fail
        out["audit_optional_failed"] = opt_fail
        out["audit_over_path_failed"] = (market == "over"
                                         and not over_path_passed)
        out["audit_all_checks"] = dict(checks)
    return out


def predict_day(provider, day=None, markets=("over",), odds=DEFAULT_ODDS,
                min_conf=O25_MIN_CONFIDENCE, market_min_conf=None,
                league_caution=None, show_all=False):
    """market_min_conf: per-market gates; defaults to config.MARKET_MIN_CONF.
    Pass an empty dict to use the flat min_conf only (backtests, demos).

    league_caution: optional (pair_stats, blocked) from leagues.caution_sets().
    Matching picks are TAGGED with a `league_caution` warning ("our patterns
    don't suit this match") -- never skipped. LIVE runs only: backtests must
    not pass this (the caution list is computed from results that did not
    exist at the time -> lookahead bias).

    show_all: if True, return EVERY (fixture, market) combination with a
    `verdict` field explaining PASS vs GATE, and `gate_reasons` listing the
    exact block cause.  No confidence gate, no international skip.  This
    lets the user manually decide which picks to take from the full card.

    ON-DISK RERUN CACHE: if the same (day, fixtures, markets, odds) is
    requested within PREDICT_CACHE_TTL_HOURS (default: fixture HTML TTL), the
    second+ run returns instantly without re-querying team histories or the
    rule engine.  Disable entirely with OU_CACHE_DISABLE=1.  show_all bypasses
    the cache (its purpose is diagnostic inspection, not hot-reruns)."""
    mmc = MARKET_MIN_CONF if market_min_conf is None else market_min_conf
    day_actual = day or _time.strftime("%Y-%m-%d")
    caution_sig = ()
    if league_caution:
        pair_stats, blocked = league_caution
        caution_sig = (tuple(sorted(pair_stats)), tuple(sorted(blocked)))
    if not show_all and not CACHE_DISABLE:
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

    seen_fx, uniq_fx = set(), []
    for fx in fixtures:
        k = (normalize(fx["home"]), normalize(fx["away"]), fx.get("league", ""))
        if k not in seen_fx:
            seen_fx.add(k)
            uniq_fx.append(fx)
    fixtures = uniq_fx

    picks = []
    for fx in fixtures:
        league = fx.get("league", "")
        is_intl = is_international_tournament(league)
        for mkt in markets:
            if not show_all and is_intl and mkt in INTERNATIONAL_SKIP_MARKETS:
                continue
            try:
                p = build_pick(fx, provider, market=mkt, odds=odds,
                               include_gate_audit=show_all)
            except Exception:
                if show_all:
                    p = {
                        "date": fx.get("date", day_actual),
                        "league": league, "home": fx.get("home"),
                        "away": fx.get("away"), "market": mkt,
                        "label": MARKET_LABEL.get(mkt, mkt),
                        "confidence": 0.0, "model_p": 0.0,
                        "checks_passed": 0, "checks_total": 0,
                        "check_ratio": 0.0, "over_path_passed": False,
                        "required_checks_passed": False, "missed": [],
                        "ev": 0.0, "edge_pct": 0.0, "stake_pct": 0.0,
                        "odds": (float(odds.get(mkt, DEFAULT_ODDS))
                                 if isinstance(odds, dict) else float(odds)),
                        "tier": "build_pick error", "xg": [0.0, 0.0],
                        "home_attack": 0, "home_concede": 0,
                        "away_attack": 0, "away_concede": 0,
                        "home_gpg_all": 0, "away_gpg_all": 0,
                        "home_concede_all": 0, "away_concede_all": 0,
                        "audit_build_error": True,
                    }
                else:
                    continue
            thr = mmc.get(mkt) or min_conf
            if market_min_conf is None:
                solid_thr = MARKET_SOLID.get(mkt, thr)
            else:
                solid_thr = thr
            gate_reasons = []
            if not p.get("required_checks_passed", False):
                rf = p.get("audit_required_failed")
                if rf:
                    gate_reasons.append("required checks failed: "
                                        + ", ".join(rf))
                else:
                    gate_reasons.append("required checks failed")
            if mkt == "over" and not p.get("over_path_passed", True):
                gate_reasons.append("over_path check failed")
            if p["confidence"] < solid_thr:
                gate_reasons.append(
                    "conf {:.3f} < gate {:.3f} ({})".format(
                        p["confidence"], solid_thr,
                        "market default solid thr"
                        if market_min_conf is None else "caller thr"))
            if is_intl and mkt in INTERNATIONAL_SKIP_MARKETS:
                gate_reasons.append("OU_INTERNATIONAL_SKIP (hard-skip env)")
            if p.get("audit_build_error"):
                gate_reasons.append("build_pick exception (team data missing?)")
            passed = not gate_reasons
            if show_all:
                p["verdict"] = "PASS" if passed else "GATE"
                p["gate_reasons"] = gate_reasons
                p["solid_threshold"] = solid_thr
                p["conf_gate_pass"] = p["confidence"] >= solid_thr
            if not show_all and not passed:
                continue
            if league_caution:
                from .leagues import league_key
                pair_stats2, blocked2 = league_caution
                lgk = league_key(fx.get("league"))
                if lgk in blocked2:
                    tag = (
                        "manually flagged league -- our patterns don't "
                        "suit this competition; reduce stake or skip")
                    if is_intl:
                        tag = (
                            "international tournament + manually flagged "
                            "league -- avoid this match entirely unless "
                            "you have a strong contrary opinion")
                    p["league_caution"] = tag
                elif (lgk, mkt) in pair_stats2:
                    g = pair_stats2[(lgk, mkt)]
                    reasons = g.get("caution_reasons") or []
                    if reasons:
                        health_tag = (
                            "CAUTION: {} in this league (60-day: "
                            "{}W-{}L {:.1f}% win% {:+.1f}u) -- {}. "
                            "Reduce stake or skip if unsure."
                            .format(mkt, g["w"], g["l"], g["win_pct"],
                                    g["profit"], "; ".join(reasons)))
                    else:
                        health_tag = (
                            "{} in this league: {}W-{}L {:+.1f}u lately -- "
                            "our patterns may not suit this match"
                            .format(mkt, g["w"], g["l"], g["profit"]))
                    if is_intl:
                        p["league_caution"] = (
                            "international tournament + league-health "
                            "warning for {}: {}. Poor fit overall; "
                            "reduce stake or skip."
                            .format(mkt, health_tag))
                    else:
                        p["league_caution"] = health_tag
                elif is_intl:
                    p["league_caution"] = (
                        "international tournament -- poor ROI track "
                        "record on this competition; reduce stake or "
                        "skip if unsure")
            elif is_intl:
                p["league_caution"] = (
                    "international tournament -- poor ROI track "
                    "record on this competition; reduce stake or "
                    "skip if unsure")
            picks.append(p)
    for mkt in markets:
        group = sorted([p for p in picks if p["market"] == mkt],
                       key=lambda p: -p["confidence"])
        for i, p in enumerate(group, 1):
            p["num"] = i
    picks.sort(key=lambda p: (list(markets).index(p["market"]), -p["confidence"]))

    if not show_all and not CACHE_DISABLE:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            try:
                with open(cache_path, encoding="utf-8") as f:
                    cache_bucket = json.load(f)
                if not isinstance(cache_bucket, dict):
                    cache_bucket = {}
            except (json.JSONDecodeError, OSError, ValueError):
                cache_bucket = {}
            now = _time.time()
            pruned = {k: v for k, v in cache_bucket.items()
                      if 0 <= now - v.get("t", now + 1) <= ttl}
            pruned[key_hash] = {"t": int(now), "picks": picks}
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(pruned, f)
        except OSError:
            pass
    return picks

import argparse
import sys
import os # already imported, but good to ensure

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate picks for a given day and markets.")
    parser.add_argument("--day", help="Date in YYYY-MM-DD format (defaults to today).")
    parser.add_argument("--markets", nargs="+", default=["over"],
                        help="Markets to predict (e.g., over home_sc btts).")
    parser.add_argument("--odds", type=float, default=DEFAULT_ODDS,
                        help="Default odds for EV calculation.")
    parser.add_argument("--min-conf", type=float, default=O25_MIN_CONFIDENCE,
                        help="Minimum confidence for a pick to be emitted.")
    parser.add_argument("--market-min-conf", type=json.loads,
                        help="""JSON string of per-market min conf (e.g., '{"home": 0.82}').""")
    parser.add_argument("--no-cache", action="store_true",
                        help="Disable all caching for this run.")

    args = parser.parse_args()

    # Override CACHE_DISABLE if --no-cache is used
    if args.no_cache:
        from overunder import config
        config.CACHE_DISABLE = True

    from .providers import SoccerbaseProvider
    provider = SoccerbaseProvider()

    picks = predict_day(
        provider,
        day=args.day,
        markets=args.markets,
        odds=args.odds,
        min_conf=args.min_conf,
        market_min_conf=args.market_min_conf
    )

    json.dump(picks, sys.stdout, indent=2)


