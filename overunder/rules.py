"""Rules engine.

POSITIVE markets -- rule sets are coupled so that BTTS is the literal union
of the two team-to-score markets.  Key relationships (also enforced in code
via _EXCLUDE and the btts override block):

  home_sc  = home attack (H6/H7 via _freq4 4/6)
           + AWAY defence LEAKAGE in 4/6 (A9 away-venue, A12 overall)
           + L3 volume confirmations (H1 home GF, A11 away GA)

  away_sc  = away attack (A3/A13 via _freq4 4/6)
           + HOME defence LEAKAGE in 4/6 (H8 home-venue, H12 overall)
           + L3 volume confirmations (A1 away GF, H10 home GA)

  btts     = home_sc  U  away_sc   (literal set union: same checks, merged)
             Both sides must score regularly AND both defences must leak.

  over     -- attack-vs-defence complementarity: home attack pairs with
             away leakage (A9/A11), away attack pairs with home leakage
             (H8/H10), plus volatile sides (HB/AB = score AND concede in
             the same games) and the proven over patterns (H2/H3/A4/A5)
  over15   -- inherits over's set
  home     -- home dominance (H16 wins 3+/6) + acceptable-form rule
             (H14/H15: 4 wins in 6 OR unbeaten 5/6) + home solidity (H17)
             + away no-win (A16) + away leaks (A9/A12)
  home_dw  -- home's evidence but draw-friendly: winless-away (A14/A15),
             weak away attack (A17/A18)

NEGATIVE markets (under, no_btts): mirrored check set; no_btts has the
dominance rule (DOM): one side keeps clean sheets OR the other blanks 50%+.
under35 shares under's check set but uses its own H2H predicate (total<=3).

H2H: expected result in >= half of last up-to-6 meetings; 1/1 counts;
     zero meetings is a neutral pass.
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
    "H10": "Home conceded 7+ (L3 home)",
    "H12": "Home concedes (4+/6 overall)",
    "H14": "Home form: 4W/6 or unbeaten 5/6 home",
    "H15": "Home form: 4W/6 or unbeaten 5/6 overall",
    "H16": "Home win (3+/6 home)",
    "H17": "Home conceded <=2 (L3 home)",
    "A1": "Away goals L3 away (7+)",
    "A3": "Away scored (4+/6 away)",
    "A4": "Away over 2.5 (4+/6 away)",
    "A5": "Away over 2.5 (L6 overall)",
    "A6": "Away BTTS (L6 away)",
    "A7": "Away BTTS (L6 overall)",
    "A8": "Away scored (4+/6 overall)",
    "A9": "Away conceded (4+/6 away)",
    "A11": "Away conceded 7+ (L3 away)",
    "A12": "Away concedes (4+/6 overall)",
    "A13": "Away scored (4+/6 overall)",
    "A14": "Away winless (4+/6 away)",
    "A15": "Away winless (4+/6 overall)",
    "A16": "Away no win (4+/6 away)",
    "A17": "Away scored <=4 (L3 away)",
    "A18": "Away blanked (4+/6 away)",
    "S6": "Both teams active",
    "H2H": "Head-to-head pattern",
    "HB": "Home BTTS game (3+/6 home)",
    "AB": "Away BTTS game (3+/6 away)",
    # under 2.5 mirrors
    "H1u": "Home scored <=4 (L3 home)",
    "H2u": "Home under 2.5 (4+/6 home)",
    "H3u": "Home under 2.5 (L6 overall)",
    "H10u": "Home conceded <=2 (L3 home)",
    "A1u": "Away scored <=4 (L3 away)",
    "A3u": "Away blanked (4+/6 away)",
    "A4u": "Away under 2.5 (4+/6 away)",
    "A5u": "Away under 2.5 (L6 overall)",
    "A11u": "Away conceded <=2 (L3 away)",
    # no-btts mirrors
    "H4n": "Home BTTS <=2 of L6 home",
    "H5n": "Home BTTS <=2 of L6 overall",
    "H6n": "Home blanked (4+/6 home)",
    "H8n": "Home clean sheet (5+/6 home)",
    "H9n": "Home clean sheet (5+/6 overall)",
    "A3n": "Away blanked (4+/6 away)",
    "A6n": "Away BTTS <=2 of L6 away",
    "A7n": "Away BTTS <=2 of L6 overall",
    "A8n": "Away blanked (4+/6 overall)",
    "A9n": "Away clean sheet (5+/6 away)",
    "A10n": "Away clean sheet (5+/6 overall)",
    "DOM": "One side dominant (CS or blank 50%+)",
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


def _freq3(ms, fn):
    """Halved frequency rule: outcome in 3+ of last 6 (or 2+ of last 3)."""
    n = len(ms)
    if n >= 6:
        return sum(1 for m in ms[-6:] if fn(m)) >= 3
    if n >= 3:
        return sum(1 for m in ms[-3:] if fn(m)) >= 2
    return False


def _freq5(ms, fn):
    """Tightened frequency rule: outcome in 5+ of last 6 (or 3+ of last 3).
    Used for conceding evidence -- leakage must be near-constant."""
    n = len(ms)
    if n >= 6:
        return sum(1 for m in ms[-6:] if fn(m)) >= 5
    if n >= 3:
        return sum(1 for m in ms[-3:] if fn(m)) >= 3
    return False


def _strong_unbeaten(ms):
    """Acceptable home form: 4+ wins in 6 outright, OR unbeaten in 5 of 6
    when wins come with draws (a draw-heavy host still qualifies)."""
    if not ms:
        return False
    wins = _rate(ms, lambda m: m["gf"] > m["ga"])
    unbeaten = _rate(ms, lambda m: m["gf"] >= m["ga"])
    return wins >= 4 / 6 or unbeaten >= 5 / 6


# Base checks that are irrelevant -- or actively harmful -- evidence for a
# given positive market. They are computed for everyone else, then dropped
# from these markets' sets (shrinking the confidence denominator on purpose:
# confidence should reflect relevant evidence only).
#
# DESIGN NOTE for the three scoring markets:
#   home_sc drops its OWN conceded checks (H8/H10 irrelevant: home doesn't
#     need to concede to merely SCORE) and drops the opponent's attack
#     evidence (A1/A3-A7 only needed for over/away markets).  It KEEPS
#     the AWAY concede evidence (A9/A11) -- which is exactly what makes
#     home likely to score vs this opponent.
#   away_sc is the mirror: drops AWAY concede (A9/A11) and home attack
#     (H1/H2-H7), KEEPS HOME concede (H8/H10) so away is likely to score.
#   btts drops NONE of the concede/scoring base checks -- it needs BOTH
#     attacks firing AND BOTH defences leaking.  It only drops the over/
#     BTTS-rate pattern checks (H2/H3/H4/H5 and A4-A7) because those are
#     already captured implicitly by requiring both halves to fire.
_EXCLUDE = {
    "over":    {"H4", "H7", "A6"},
    "over15":  {"H4", "H7", "A6"},
    "btts":    {"H2", "H3", "H4", "H5", "A4", "A5", "A6", "A7",
                "H1", "A11", "A1", "H10"},
    "home":    {"H2", "H3", "H4", "H5", "H8", "H10", "A1", "A3",
                "A4", "A5", "A6", "A7", "A11", "H17"},
    "home_sc": {"H2", "H3", "H4", "H5", "H8", "H10", "A1", "A3",
                "A4", "A5", "A6", "A7", "H1", "A11"},
    "away_sc": {"H1", "H2", "H3", "H4", "H5", "H6", "H7",
                "A4", "A5", "A6", "A7", "A9", "A11", "A1", "H10"},
    "home_dw": {"H2", "H3", "H4", "H5", "H8", "H10", "A1", "A3",
                "A4", "A5", "A6", "A7"},
}


def _negative_checks(home_ms, away_ms, check_set, away_name, h2h_market):
    h3h = _last(home_ms, 3, "H")
    a3a = _last(away_ms, 3, "A")
    h6 = _last(home_ms, 6)
    a6 = _last(away_ms, 6)
    h6H = _last(home_ms, 6, "H")
    a6A = _last(away_ms, 6, "A")
    checks = {"S6": len(home_ms) >= 4 and len(away_ms) >= 4}
    if check_set == "under":
        under = lambda m: _tot(m) <= 2.5
        checks.update({
            "H1u": _low_volume_check(h3h, "gf", 4, 1.0),
            "H2u": _freq4(h6H, under),
            "H3u": _rate(h6, under) >= 0.5,
            "H10u": _low_volume_check(h3h, "ga", 2, 0.7),
            "A1u": _low_volume_check(a3a, "gf", 4, 1.0),
            "A3u": _freq4(a6A, lambda m: m["gf"] == 0),
            "A4u": _freq4(a6A, under),
            "A5u": _rate(a6, under) >= 0.5,
            "A11u": _low_volume_check(a3a, "ga", 2, 0.7),
        })
    elif check_set == "no_btts":
        btts = lambda m: m["gf"] > 0 and m["ga"] > 0
        checks.update({
            "H4n": sum(1 for m in h6H if btts(m)) <= 2,
            "H5n": sum(1 for m in h6 if btts(m)) <= 2,
            "H6n": _freq4(h6H, lambda m: m["gf"] == 0),
            "H8n": _freq5(h6H, lambda m: m["ga"] == 0),
            "H9n": _freq5(h6, lambda m: m["ga"] == 0),
            "A3n": _freq4(a6A, lambda m: m["gf"] == 0),
            "A6n": sum(1 for m in a6A if btts(m)) <= 2,
            "A7n": sum(1 for m in a6 if btts(m)) <= 2,
            "A8n": _freq4(a6, lambda m: m["gf"] == 0),
            "A9n": _freq5(a6A, lambda m: m["ga"] == 0),
            "A10n": _freq5(a6, lambda m: m["ga"] == 0),
            "DOM": (_rate(h6, lambda m: m["ga"] == 0) >= 0.5 or
                    _rate(a6, lambda m: m["gf"] == 0) >= 0.5),
        })
    checks["H2H"] = h2h_check(home_ms, h2h_market, away_name)
    return checks


def run_checks(home_ms, away_ms, market=None, home_name="", away_name=""):
    # under35 shares under's mirrored check set but keeps its own H2H predicate
    if market in ("under", "no_btts", "under35"):
        check_set = "under" if market == "under35" else market
        return _negative_checks(home_ms, away_ms, check_set, away_name,
                                h2h_market=market)

    h3h = _last(home_ms, 3, "H")
    a3a = _last(away_ms, 3, "A")
    h6 = _last(home_ms, 6)
    a6 = _last(away_ms, 6)
    h6H = _last(home_ms, 6, "H")
    a6A = _last(away_ms, 6, "A")
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
        "A3": _freq4(a6A, lambda m: m["gf"] > 0),
        "A4": _freq4(a6A, over),
        "A5": _rate(a6, over) >= 0.5,
        "A6": _rate(a6A, btts) >= 0.5,
        "A7": _rate(a6, btts) >= 0.5,
        "A9": _freq4(a6A, lambda m: m["ga"] > 0),
        "A11": _volume_check(a3a, "ga"),
        "S6": len(home_ms) >= 4 and len(away_ms) >= 4,
    }
    # drop base checks that don't count as evidence for this market
    if market in _EXCLUDE:
        for k in _EXCLUDE[market]:
            checks.pop(k, None)

    if market in ("over", "over15"):
        # attack-vs-defence complementarity + volatile sides; A8 completes
        # the away-scoring picture for the away-attack vs home-defence pair
        checks.update({
            "A8": _freq4(a6, lambda m: m["gf"] > 0),
            "HB": sum(1 for m in h6H if m["gf"] > 0 and m["ga"] > 0) >= 3,
            "AB": sum(1 for m in a6A if m["gf"] > 0 and m["ga"] > 0) >= 3,
        })
    elif market == "btts":
        # btts = home_sc U away_sc -- the full union:
        #   * home attack + away leakage (home_sc profile: H6/H7 4/6 + A9/A11/A12)
        #   * away attack + home leakage (away_sc profile: A3/A13 4/6 + H8/H10/H12)
        # Base checks already provide A9/A11 and H8/H10 via _freq4; we add the
        # venue+overall conceded rates (A12/H12 at 4/6) and explicitly compute
        # overall scoring (H7/A13) using the same _freq4 bar as venue checks.
        checks.update({
            "H6": _freq4(h6H, lambda m: m["gf"] > 0),
            "H7": _freq4(h6, lambda m: m["gf"] > 0),
            "A3": _freq4(a6A, lambda m: m["gf"] > 0),
            "A13": _freq4(a6, lambda m: m["gf"] > 0),
            "A12": sum(1 for m in a6 if m["ga"] > 0) >= 4,
            "H12": sum(1 for m in h6 if m["ga"] > 0) >= 4,
        })
    elif market == "home":
        # dominance + acceptable form + away no-win + leaks
        checks.update({
            "A12": sum(1 for m in a6 if m["ga"] > 0) >= 4,
            "H14": _strong_unbeaten(h6H),
            "H15": _strong_unbeaten(h6),
            "H16": _freq3(h6H, lambda m: m["gf"] > m["ga"]),   # wins 3+/6 home
            "A16": _freq4(a6A, lambda m: m["gf"] <= m["ga"]),  # away loses OR draws away
        })
    elif market == "home_sc":
        # home_sc: home attack (_freq4 4/6) + AWAY concedes (venue 4/6 via base A9,
        # venue volume via A11, plus overall A12 at 4/6).
        checks["A12"] = sum(1 for m in a6 if m["ga"] > 0) >= 4
        checks["H6"] = _freq4(h6H, lambda m: m["gf"] > 0)
        checks["H7"] = _freq4(h6, lambda m: m["gf"] > 0)
    elif market == "away_sc":
        # away_sc: away attack (_freq4 4/6) + HOME concedes (venue 4/6 via base H8,
        # venue volume via H10, plus overall H12 at 4/6).
        checks.update({
            "A3": _freq4(a6A, lambda m: m["gf"] > 0),
            "A13": _freq4(a6, lambda m: m["gf"] > 0),
            "H12": sum(1 for m in h6 if m["ga"] > 0) >= 4,
        })
    elif market == "home_dw":
        # home's evidence but draw-friendly: winless (not loss-heavy) away
        checks.update({
            "A12": sum(1 for m in a6 if m["ga"] > 0) >= 4,
            "H14": _strong_unbeaten(h6H),
            "H15": _strong_unbeaten(h6),
            "H17": _low_volume_check(h3h, "ga", 2, 0.7),
            "A14": _freq4(a6A, lambda m: m["gf"] <= m["ga"]),  # winless away
            "A15": _freq4(a6, lambda m: m["gf"] <= m["ga"]),   # winless overall
            "A17": _low_volume_check(a3a, "gf", 4, 1.0),
            "A18": _freq4(a6A, lambda m: m["gf"] == 0),
        })
    if market:
        checks["H2H"] = h2h_check(home_ms, market, away_name)
    return checks


def lambdas(home_ms, away_ms, lg_home=1.45, lg_away=1.15):
    def avg(ms, venue, key, fallback):
        sel = [m for m in ms if m["venue"] == venue]
        return (sum(m[key] for m in sel) / len(sel)) if sel else fallback

    atk_h = max(0.4, avg(home_ms, "H", "gf", lg_home) / lg_home)
    dfc_h = max(0.4, avg(home_ms, "H", "ga", lg_away) / lg_away)
    atk_a = max(0.4, avg(away_ms, "A", "gf", lg_away) / lg_away)
    dfc_a = max(0.4, avg(away_ms, "A", "ga", lg_home) / lg_home)
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
