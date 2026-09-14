"""Rules engine.

POSITIVE markets (over, btts, home, home_sc, away_sc):
  22 base checks + H2H, plus the 4/6-overall checks for btts/home_sc/away_sc.
  Weak/strong volume rules carry an early-season rate fallback.

NEGATIVE markets (under, no_btts): their own mirrored check set -- a pick is
NOT judged by the positive rules it deliberately defies:
  under   -- weak attacks, solid defences, under rates, low-activity away side,
             H2H predicate = match stayed under 2.5
  no_btts -- at least one side blanks regularly / keeps clean sheets,
             low BTTS rates, H2H predicate = at least one side failed to score

H2H: expected result in >= half of last up-to-6 meetings; 1/1 counts;
     zero meetings is a neutral pass. S7 (trend) removed.
"""

import math

from .teams import normalize

CHECK_NAMES = {
    "H1": "Home goals L3 home (7+)",
    "H2": "Home over 2.5 (4+/6 home)",
    "H3": "Home over 2.5 (L6 overall)",
    "H4": "Home BTTS (L6 home)",
    "H5": "Home BTTS (L6 overall)",
    "H6": "Home scored (4+/6 home)",
    "H7": "Home scored (4+/6 overall)",
    "H8": "Home conceded (4+/6 home)",
    "H9": "Home conceded (L3 overall)",
    "H10": "Home conceded 7+ (L3 home)",
    "H11": "Home scored (4+/6 overall)",
    "H12": "Home concedes (4+/6 overall)",
    "A1": "Away goals L3 away (7+)",
    "A2": "Away prev match 2+ goals",
    "A3": "Away scored (4+/6 away)",
    "A4": "Away over 2.5 (4+/6 away)",
    "A5": "Away over 2.5 (L6 overall)",
    "A6": "Away BTTS (L6 away)",
    "A7": "Away BTTS (L6 overall)",
    "A8": "Away scored (L6 overall)",
    "A9": "Away conceded (4+/6 away)",
    "A10": "Away conceded (L3 overall)",
    "A11": "Away conceded 7+ (L3 away)",
    "A12": "Away concedes (4+/6 overall)",
    "A13": "Away scored (4+/6 overall)",
    "H14": "Home unbeaten (4+/6 home)",
    "H15": "Home unbeaten (4+/6 overall)",
    "A14": "Away winless (4+/6 away)",
    "A15": "Away winless (4+/6 overall)",
    "S6": "Both teams active",
    "H2H": "Head-to-head pattern",
    # under 2.5 mirrors
    "H1u": "Home scored <=4 (L3 home)",
    "H2u": "Home under 2.5 (4+/6 home)",
    "H3u": "Home under 2.5 (L6 overall)",
    "H10u": "Home conceded <=2 (L3 home)",
    "A1u": "Away scored <=4 (L3 away)",
    "A2u": "Away prev match <=1 goal",
    "A3u": "Away blanked (4+/6 away)",
    "A4u": "Away under 2.5 (4+/6 away)",
    "A5u": "Away under 2.5 (L6 overall)",
    "A11u": "Away conceded <=2 (L3 away)",
    # no-btts mirrors
    "H4n": "Home BTTS <=2 of L6 home",
    "H5n": "Home BTTS <=2 of L6 overall",
    "H6n": "Home blanked (4+/6 home)",
    "H8n": "Home clean sheet (4+/6 home)",
    "H9n": "Home clean sheet (4+/6 overall)",
    "A3n": "Away blanked (4+/6 away)",
    "A6n": "Away BTTS <=2 of L6 away",
    "A7n": "Away BTTS <=2 of L6 overall",
    "A8n": "Away blanked (4+/6 overall)",
    "A9n": "Away clean sheet (4+/6 away)",
    "A10n": "Away clean sheet (4+/6 overall)",
}

H2H_PRED = {
    "over":    lambda m: m["gf"] + m["ga"] > 2.5,
    "btts":    lambda m: m["gf"] > 0 and m["ga"] > 0,
    "home":    lambda m: m["gf"] > m["ga"],
    "home_sc": lambda m: m["gf"] > 0,
    "away_sc": lambda m: m["ga"] > 0,
    "under":   lambda m: m["gf"] + m["ga"] <= 2.5,
    "no_btts": lambda m: not (m["gf"] > 0 and m["ga"] > 0),
    "over15":  lambda m: m["gf"] + m["ga"] >= 2,
    "under35": lambda m: m["gf"] + m["ga"] <= 3,
    "home_dw": lambda m: m["gf"] >= m["ga"],
}


def _last(matches, n, venue=None):
    ms = [m for m in matches if venue is None or m["venue"] == venue]
    return ms[-n:]


def _tot(m):
    return m["gf"] + m["ga"]


def _rate(ms, fn):
    return sum(1 for m in ms if fn(m)) / len(ms) if ms else 0.0


def _volume_check(ms, key, threshold=7, rate_fallback=2.0):
    if not ms:
        return False
    s = sum(m[key] for m in ms)
    return s >= threshold or (len(ms) < 3 and s / len(ms) >= rate_fallback)


def _low_volume_check(ms, key, max_total, rate_fallback):
    """Mirror of _volume_check: WEAK output (under/no_btts markets)."""
    if not ms:
        return False
    s = sum(m[key] for m in ms)
    return s <= max_total or (len(ms) < 3 and s / len(ms) <= rate_fallback)


def h2h_check(home_ms, market, away_name):
    pred = H2H_PRED.get(market)
    if not pred or not away_name:
        return False
    tgt = normalize(away_name)
    meetings = [m for m in home_ms
                if m.get("opp") and normalize(m["opp"]) == tgt]
    meetings = meetings[-6:]
    n = len(meetings)
    if n == 0:
        return True
    hits = sum(1 for m in meetings if pred(m))
    return hits * 2 >= n


def _freq4(ms, fn):
    """Doubled frequency rule: outcome in 4+ of last 6; when fewer than 6
    matches exist, fall back to 2+ of the last 3 (needs at least 3)."""
    n = len(ms)
    if n >= 6:
        return sum(1 for m in ms[-6:] if fn(m)) >= 4
    if n >= 3:
        return sum(1 for m in ms[-3:] if fn(m)) >= 2
    return False


def _negative_checks(home_ms, away_ms, market, away_name):
    h3h = _last(home_ms, 3, "H")
    a3a = _last(away_ms, 3, "A")
    h6 = _last(home_ms, 6)
    a6 = _last(away_ms, 6)
    h6H = _last(home_ms, 6, "H")
    a6A = _last(away_ms, 6, "A")
    h3 = _last(home_ms, 3)
    a3 = _last(away_ms, 3)
    checks = {"S6": len(home_ms) >= 4 and len(away_ms) >= 4}
    if market == "under":
        under = lambda m: _tot(m) <= 2.5
        checks.update({
            "H1u": _low_volume_check(h3h, "gf", 4, 1.0),   # weak home attack
            "H2u": _freq4(h6H, under),
            "H3u": _rate(h6, under) >= 0.5,
            "H10u": _low_volume_check(h3h, "ga", 2, 0.7),  # solid home defence
            "A1u": _low_volume_check(a3a, "gf", 4, 1.0),
            "A2u": (_tot(away_ms[-1]) <= 1) if away_ms else False,
            "A3u": _freq4(a6A, lambda m: m["gf"] == 0),
            "A4u": _freq4(a6A, under),
            "A5u": _rate(a6, under) >= 0.5,
            "A11u": _low_volume_check(a3a, "ga", 2, 0.7),
        })
    elif market == "no_btts":
        btts = lambda m: m["gf"] > 0 and m["ga"] > 0
        checks.update({
            "H4n": sum(1 for m in h6H if btts(m)) <= 2,
            "H5n": sum(1 for m in h6 if btts(m)) <= 2,
            "H6n": _freq4(h6H, lambda m: m["gf"] == 0),
            "H8n": _freq4(h6H, lambda m: m["ga"] == 0),
            "H9n": _freq4(h6, lambda m: m["ga"] == 0),
            "A3n": _freq4(a6A, lambda m: m["gf"] == 0),
            "A6n": sum(1 for m in a6A if btts(m)) <= 2,
            "A7n": sum(1 for m in a6 if btts(m)) <= 2,
            "A8n": _freq4(a6, lambda m: m["gf"] == 0),
            "A9n": _freq4(a6A, lambda m: m["ga"] == 0),
            "A10n": _freq4(a6, lambda m: m["ga"] == 0),
        })
    checks["H2H"] = h2h_check(home_ms, market, away_name)
    return checks


def run_checks(home_ms, away_ms, market=None, home_name="", away_name=""):
    # under35 shares under's mirrored set; home_dw shares home's extras
    if market in ("under", "no_btts", "under35"):
        neg = "under" if market == "under35" else market
        return _negative_checks(home_ms, away_ms, neg, away_name)

    h3h = _last(home_ms, 3, "H")
    a3a = _last(away_ms, 3, "A")
    h6 = _last(home_ms, 6)
    a6 = _last(away_ms, 6)
    h6H = _last(home_ms, 6, "H")
    a6A = _last(away_ms, 6, "A")
    h3 = _last(home_ms, 3)
    a3 = _last(away_ms, 3)
    over = lambda m: _tot(m) > 2.5
    btts = lambda m: m["gf"] > 0 and m["ga"] > 0

    checks = {
        "H1": _volume_check(h3h, "gf"),
        "H2": _freq4(h6H, over),
        "H3": _rate(h6, over) >= 0.5,
        "H4": _rate(h6H, btts) >= 0.5,
        "H5": _rate(h6, btts) >= 0.5,
        "H6": _freq4(h6H, lambda m: m["gf"] > 0),
        "H7": _freq4(h6, lambda m: m["gf"] > 0),
        "H8": _freq4(h6H, lambda m: m["ga"] > 0),
        "H10": _volume_check(h3h, "ga"),
        "A1": _volume_check(a3a, "gf"),
        "A2": (_tot(away_ms[-1]) >= 2) if away_ms else False,
        "A3": _freq4(a6A, lambda m: m["gf"] > 0),
        "A4": _freq4(a6A, over),
        "A5": _rate(a6, over) >= 0.5,
        "A6": _rate(a6A, btts) >= 0.5,
        "A7": _rate(a6, btts) >= 0.5,
        "A9": _freq4(a6A, lambda m: m["ga"] > 0),
        "A11": _volume_check(a3a, "ga"),
        "S6": len(home_ms) >= 4 and len(away_ms) >= 4,
    }
    if market in ("btts", "home", "home_sc", "away_sc", "home_dw"):
        # overall 4/6 reliability rules (the doubled forms of the old 2/3 rules)
        checks["A12"] = sum(1 for m in a6 if m["ga"] > 0) >= 4
        checks["A13"] = sum(1 for m in a6 if m["gf"] > 0) >= 4
        checks["H12"] = sum(1 for m in h6 if m["ga"] > 0) >= 4
    if market in ("home", "home_dw"):
        # result-stability rules: the host doesn't lose, the visitor doesn't win
        checks["H14"] = _freq4(h6H, lambda m: m["gf"] >= m["ga"])   # unbeaten at home
        checks["H15"] = _freq4(h6, lambda m: m["gf"] >= m["ga"])    # unbeaten overall
        checks["A14"] = _freq4(a6A, lambda m: m["gf"] <= m["ga"])   # winless away
        checks["A15"] = _freq4(a6, lambda m: m["gf"] <= m["ga"])    # winless overall
    if market:
        checks["H2H"] = h2h_check(home_ms, market, away_name)
    return checks


def lambdas(home_ms, away_ms, lg_home=1.45, lg_away=1.15):
    def avg(ms, venue, key):
        sel = [m for m in ms if m["venue"] == venue]
        return (sum(m[key] for m in sel) / len(sel)) if sel else (lg_home if key == "gf" else 1.3)

    atk_h = max(0.4, avg(home_ms, "H", "gf") / lg_home)
    dfc_h = max(0.4, avg(home_ms, "H", "ga") / lg_away)
    atk_a = max(0.4, avg(away_ms, "A", "gf") / lg_away)
    dfc_a = max(0.4, avg(away_ms, "A", "ga") / lg_home)
    return (min(3.8, max(0.3, lg_home * atk_h * dfc_a)),
            min(3.2, max(0.2, lg_away * atk_a * dfc_h)))


def poisson_grid(lam_h, lam_a, max_goals=8):
    ph = [math.exp(-lam_h) * lam_h ** h / math.factorial(h) for h in range(max_goals + 1)]
    pa = [math.exp(-lam_a) * lam_a ** a / math.factorial(a) for a in range(max_goals + 1)]
    return ph, pa


def poisson_over25(home_ms, away_ms,
                   lg_home=1.45, lg_away=1.15, max_goals=8):
    lam_h, lam_a = lambdas(home_ms, away_ms, lg_home, lg_away)
    ph, pa = poisson_grid(lam_h, lam_a, max_goals)
    prob = sum(ph[h] * pa[a] for h in range(max_goals + 1)
               for a in range(max_goals + 1) if h + a > 2.5)
    return prob, lam_h, lam_a


def market_probs(home_ms, away_ms, max_goals=8):
    lam_h, lam_a = lambdas(home_ms, away_ms)
    ph, pa = poisson_grid(lam_h, lam_a, max_goals)
    p_over = sum(ph[h] * pa[a] for h in range(max_goals + 1)
                 for a in range(max_goals + 1) if h + a > 2.5)
    p_home = sum(ph[h] * pa[a] for h in range(max_goals + 1)
                 for a in range(max_goals + 1) if h > a)
    p0h, p0a = ph[0], pa[0]
    p_btts = 1 - p0h - p0a + ph[0] * pa[0]
    p_away_win = sum(ph[h] * pa[a] for h in range(max_goals + 1)
                     for a in range(max_goals + 1) if h < a)
    p_le2 = sum(ph[h] * pa[a] for h in range(max_goals + 1)
                for a in range(max_goals + 1) if h + a <= 2)   # 0-2 goals
    p_ge2 = 1 - p_le2 + ph[0] * pa[0] * 0  # placeholder, computed below
    p0 = ph[0] * pa[0]
    p1 = ph[1] * pa[0] + ph[0] * pa[1]
    p_over15 = 1 - p0 - p1
    p_under35 = sum(ph[h] * pa[a] for h in range(max_goals + 1)
                    for a in range(max_goals + 1) if h + a <= 3)
    return {"over": p_over, "under": 1 - p_over, "home": p_home, "btts": p_btts,
            "no_btts": 1 - p_btts, "draw": 1 - p_home - p_away_win,
            "home_sc": 1 - p0h, "away_sc": 1 - p0a,
            "over15": p_over15, "under35": p_under35,
            "home_dw": 1 - p_away_win}


def xg_forecast(lam_h, lam_a):
    t = max(1.2, 1.1 + 0.75 * (lam_h + lam_a - 2.0))
    return round(t - 0.9, 2), round(t + 0.6, 2)
