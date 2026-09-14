"""Unified prediction rules — Symmetry Principle.

Core thesis (every market = scoring forces + conceding forces):
  Over 2.5 needs ALL FOUR of:
    Home scores at home    (H checks)
    Away concedes on road  (D checks — away DEFENCE is LEAKY)
    Away scores on road    (A checks)
    Home concedes at home  (E checks — home DEFENCE is EXPOSED)

If any leg fails, the "scoring streak meets a defensive wall" pattern
produces a false positive. Check windows match the profile we settled on:
  Venue-specific = last 5    (reduced from 6; tighter signal)
  Overall form   = last 10   (maintained; broader context)
  Veto window    = last 2-3  (hot/cold streaks)

Check list (20 total — 4 scoring legs × venue/overall + form gates + vetoes):

  SCORING SIDE (classic over25tips profile — venue L5 / overall L10)
    H1  Home GF in L5 home            >= 10
    H2  Home L5 home: 3+ games over 2.5
    H3  Home GF rate (L10 overall)    >= 1.5/match
    H4  Home: 5+ of L10 over 2.5

    A1  Away GF in L5 away            >= 8
    A2  Away L5 away: 3+ games over 2.5
    A3  Away GF rate (L10 overall)    >= 1.3/match
    A4  Away: 5+ of L10 over 2.5

  SYMMETRY / OPPONENT-CONCESSION SIDE (Defence Gate — leaky mode)
  These are the checks that prevent 'scoring streak vs defensive wall' losses.
    D1  Away GA in L5 away             >= 10   (away leaks on road)
    D2  Away L5 away: 3+ games BTTS-yes
    D3  Away GA rate (L10 overall)     >= 1.5/match
    D4  Away: conceded in 8+ of L10

    E1  Home GA in L5 home             >= 8    (home leaks at venue)
    E2  Home L5 home: 3+ games BTTS-yes
    E3  Home GA rate (L10 overall)     >= 1.3/match
    E4  Home: conceded in 8+ of L10

  FORM / ACTIVITY GATES
    S1  Both teams have >= 10 matches in sample  (data reliability)
    S2  BTTS rate L10 >= 50% for home
    S3  BTTS rate L10 >= 50% for away

  VETOES (hard blocks — ANY failing removes pick from contention)
    V1  Scoring drought: either team GF=0 in both L2 venue
    V2  Defensive wall:  either team GA=0 in both L2 venue
    V3  Cold streak:     either team total<=2 in both L2 venue
"""

import math

VENUE_N = 5
OVERALL_N = 10
VETO_N = 2

CHECK_NAMES = {
    "H1": f"Home goals L{VENUE_N} home (>=10)",
    "H2": f"Home over 2.5 L{VENUE_N} home (3+)",
    "H3": f"Home GF rate L{OVERALL_N} overall (>=1.5)",
    "H4": f"Home over 2.5 L{OVERALL_N} overall (5+)",
    "A1": f"Away goals L{VENUE_N} away (>=8)",
    "A2": f"Away over 2.5 L{VENUE_N} away (3+)",
    "A3": f"Away GF rate L{OVERALL_N} overall (>=1.3)",
    "A4": f"Away over 2.5 L{OVERALL_N} overall (5+)",
    "D1": f"Away conceded L{VENUE_N} away — leaky (>=10)",
    "D2": f"Away BTTS-yes L{VENUE_N} away (3+)",
    "D3": f"Away GA rate L{OVERALL_N} overall — leaky (>=1.5)",
    "D4": f"Away conceded 8+ of L{OVERALL_N}",
    "E1": f"Home conceded L{VENUE_N} home — exposed (>=8)",
    "E2": f"Home BTTS-yes L{VENUE_N} home (3+)",
    "E3": f"Home GA rate L{OVERALL_N} overall — exposed (>=1.3)",
    "E4": f"Home conceded 8+ of L{OVERALL_N}",
    "S1": f"Both teams sample >= {OVERALL_N} matches",
    "S2": f"Home BTTS rate L{OVERALL_N} >= 50%",
    "S3": f"Away BTTS rate L{OVERALL_N} >= 50%",
    "V1": "No scoring drought (GF=0 in L2 venue)",
    "V2": "No defensive wall (GA=0 in L2 venue)",
    "V3": "No cold streak (tot<=2 in L2 venue)",
}

VETO_KEYS = ("V1", "V2", "V3")


def _last(matches, n, venue=None):
    ms = [m for m in matches if venue is None or m["venue"] == venue]
    return ms[-n:]


def _tot(m):
    return m["gf"] + m["ga"]


def _rate(ms, fn):
    return sum(1 for m in ms if fn(m)) / len(ms) if ms else 0.0


def _count(ms, fn):
    return sum(1 for m in ms if fn(m))


def _all(ms, fn):
    return len(ms) > 0 and all(fn(m) for m in ms)


def run_checks(home_ms, away_ms):
    """Symmetric checks + vetoes. Veto-keys failing should HARD-block a pick."""

    hv  = _last(home_ms, VENUE_N,   "H")
    av  = _last(away_ms, VENUE_N,   "A")
    ho  = _last(home_ms, OVERALL_N)
    ao  = _last(away_ms, OVERALL_N)
    hv2 = _last(home_ms, VETO_N,    "H")
    av2 = _last(away_ms, VETO_N,    "A")

    checks = {}

    checks["H1"] = sum(m["gf"] for m in hv) >= 10
    checks["H2"] = _count(hv, lambda m: _tot(m) > 2.5) >= 3
    checks["H3"] = (sum(m["gf"] for m in ho) / len(ho) >= 1.5) if ho else False
    checks["H4"] = _count(ho, lambda m: _tot(m) > 2.5) >= 5

    checks["A1"] = sum(m["gf"] for m in av) >= 8
    checks["A2"] = _count(av, lambda m: _tot(m) > 2.5) >= 3
    checks["A3"] = (sum(m["gf"] for m in ao) / len(ao) >= 1.3) if ao else False
    checks["A4"] = _count(ao, lambda m: _tot(m) > 2.5) >= 5

    checks["D1"] = sum(m["ga"] for m in av) >= 10
    checks["D2"] = _count(av, lambda m: m["gf"] > 0 and m["ga"] > 0) >= 3
    checks["D3"] = (sum(m["ga"] for m in ao) / len(ao) >= 1.5) if ao else False
    checks["D4"] = _count(ao, lambda m: m["ga"] >= 1) >= 8

    checks["E1"] = sum(m["ga"] for m in hv) >= 8
    checks["E2"] = _count(hv, lambda m: m["gf"] > 0 and m["ga"] > 0) >= 3
    checks["E3"] = (sum(m["ga"] for m in ho) / len(ho) >= 1.3) if ho else False
    checks["E4"] = _count(ho, lambda m: m["ga"] >= 1) >= 8

    checks["S1"] = len(home_ms) >= OVERALL_N and len(away_ms) >= OVERALL_N
    checks["S2"] = _rate(ho, lambda m: m["gf"] > 0 and m["ga"] > 0) >= 0.5
    checks["S3"] = _rate(ao, lambda m: m["gf"] > 0 and m["ga"] > 0) >= 0.5

    checks["V1"] = not (
        _all(hv2, lambda m: m["gf"] == 0) or _all(av2, lambda m: m["gf"] == 0)
    )
    checks["V2"] = not (
        _all(hv2, lambda m: m["ga"] == 0) or _all(av2, lambda m: m["ga"] == 0)
    )
    checks["V3"] = not (
        _all(hv2, lambda m: _tot(m) <= 2) or _all(av2, lambda m: _tot(m) <= 2)
    )

    return checks


def any_veto_failed(checks):
    """True if any hard-block veto tripped — callers should drop the pick."""
    return any(not checks.get(k, True) for k in VETO_KEYS)


def poisson_over25(home_ms, away_ms,
                   lg_home=1.45, lg_away=1.15, max_goals=8):
    """P(Over 2.5) via independent Poisson lambdas from attack/defence rates.

    Symmetric normalization:
      atk_h = home GF/h   / lg_home   (home attack strength)
      dfc_h = home GA/h   / lg_away   (home defence weakness)
      atk_a = away GF/a   / lg_away   (away attack strength)
      dfc_a = away GA/a   / lg_home   (away defence weakness)
      lambda_H = lg_home * atk_h * dfc_a   (home vs away's leaky road defence)
      lambda_A = lg_away * atk_a * dfc_h   (away vs home's leaky venue defence)
    """

    def avg(ms, venue, key, fallback_val, fallback_cnt):
        sel = [m for m in ms if m["venue"] == venue]
        if len(sel) >= fallback_cnt:
            return sum(m[key] for m in sel) / len(sel)
        return fallback_val

    atk_h = max(0.4, avg(home_ms, "H", "gf", lg_home, 3) / lg_home)
    dfc_h = max(0.4, avg(home_ms, "H", "ga", 1.3,    3) / lg_away)
    atk_a = max(0.4, avg(away_ms, "A", "gf", lg_away, 3) / lg_away)
    dfc_a = max(0.4, avg(away_ms, "A", "ga", 1.3,    3) / lg_home)

    lam_h = min(3.8, max(0.3, lg_home * atk_h * dfc_a))
    lam_a = min(3.2, max(0.2, lg_away * atk_a * dfc_h))

    prob = 0.0
    for h in range(max_goals + 1):
        ph = math.exp(-lam_h) * lam_h ** h / math.factorial(h)
        for a in range(max_goals + 1):
            if h + a > 2.5:
                pa = math.exp(-lam_a) * lam_a ** a / math.factorial(a)
                prob += ph * pa
    return prob, lam_h, lam_a


def xg_forecast(lam_h, lam_a):
    t = max(1.2, 1.1 + 0.75 * (lam_h + lam_a - 2.0))
    return round(t - 0.9, 2), round(t + 0.6, 2)
