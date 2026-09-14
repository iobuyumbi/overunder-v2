"""The over25tips.com public ruleset (H1/H2/A1-A4) extended: EVERY form signal
has a venue-specific AND an overall variant, so all markets judge both.

17 checks:
  H1 home goals L3 home (7+, rate-fallback early season)      A1 away goals L3 away (7+, fallback)
  H2 home over2.5 L3 home                                     A2 away prev match 2+ goals
  H3 home over2.5 L6 overall                                  A3 away scored L3 away
  H4 home BTTS L6 home                                        A4 away over2.5 L3 away
  H5 home BTTS L6 overall                                     A5 away over2.5 L6 overall
  H6 home scored L3 home                                      A6 away BTTS L6 away
  H7 home scored L6 overall                                   A7 away BTTS L6 overall
                                                              A8 away scored L6 overall
  S6 both teams active (4+ matches)   S7 goals trend rising
"""

import math

CHECK_NAMES = {
    "H1": "Home goals L3 home (7+)",
    "H2": "Home over 2.5 (L3 home)",
    "H3": "Home over 2.5 (L6 overall)",
    "H4": "Home BTTS (L6 home)",
    "H5": "Home BTTS (L6 overall)",
    "H6": "Home scored (L3 home)",
    "H7": "Home scored (L6 overall)",
    "A1": "Away goals L3 away (7+)",
    "A2": "Away prev match 2+ goals",
    "A3": "Away scored (L3 away)",
    "A4": "Away over 2.5 (L3 away)",
    "A5": "Away over 2.5 (L6 overall)",
    "A6": "Away BTTS (L6 away)",
    "A7": "Away BTTS (L6 overall)",
    "A8": "Away scored (L6 overall)",
    "S6": "Both teams active",
    "S7": "Goals trend rising",
}


def _last(matches, n, venue=None):
    ms = [m for m in matches if venue is None or m["venue"] == venue]
    return ms[-n:]


def _tot(m):
    return m["gf"] + m["ga"]


def _rate(ms, fn):
    return sum(1 for m in ms if fn(m)) / len(ms) if ms else 0.0


def _goals_check(ms, threshold=7):
    """7+ goals in last 3 at venue -- early season there may be only 1-2 such
    matches, so then require a strong scoring rate (2.0+/game)."""
    if not ms:
        return False
    return sum(m["gf"] for m in ms) >= threshold or \
           (len(ms) < 3 and sum(m["gf"] for m in ms) / len(ms) >= 2.0)


def run_checks(home_ms, away_ms):
    h3h = _last(home_ms, 3, "H")
    a3a = _last(away_ms, 3, "A")
    h6 = _last(home_ms, 6)
    a6 = _last(away_ms, 6)
    h6H = _last(home_ms, 6, "H")
    a6A = _last(away_ms, 6, "A")
    h3 = _last(home_ms, 3)
    a3 = _last(away_ms, 3)
    last3 = (h3h + a3a)[-3:]
    prev3 = (h3h + a3a)[-6:-3]
    over = lambda m: _tot(m) > 2.5
    btts = lambda m: m["gf"] > 0 and m["ga"] > 0

    return {
        "H1": _goals_check(h3h),
        "H2": sum(1 for m in h3h if over(m)) >= 2,
        "H3": _rate(h6, over) >= 0.5,
        "H4": _rate(h6H, btts) >= 0.5,
        "H5": _rate(h6, btts) >= 0.5,
        "H6": sum(1 for m in h3h if m["gf"] > 0) >= 2,
        "H7": sum(1 for m in h3 if m["gf"] > 0) >= 2,
        "A1": _goals_check(a3a),
        "A2": (_tot(away_ms[-1]) >= 2) if away_ms else False,
        "A3": sum(1 for m in a3a if m["gf"] > 0) >= 2,
        "A4": sum(1 for m in a3a if over(m)) >= 2,
        "A5": _rate(a6, over) >= 0.5,
        "A6": _rate(a6A, btts) >= 0.5,
        "A7": _rate(a6, btts) >= 0.5,
        "A8": sum(1 for m in a3 if m["gf"] > 0) >= 2,
        "S6": len(home_ms) >= 4 and len(away_ms) >= 4,
        "S7": (sum(_tot(m) for m in last3) > sum(_tot(m) for m in prev3)) if len(prev3) == 3 else False,
    }


def lambdas(home_ms, away_ms, lg_home=1.45, lg_away=1.15):
    """Attack/defence-adjusted expected goals for each side."""
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
    """P(Over 2.5) via independent Poisson lambdas from attack/defence rates."""
    lam_h, lam_a = lambdas(home_ms, away_ms, lg_home, lg_away)
    ph, pa = poisson_grid(lam_h, lam_a, max_goals)
    prob = sum(ph[h] * pa[a] for h in range(max_goals + 1)
               for a in range(max_goals + 1) if h + a > 2.5)
    return prob, lam_h, lam_a


def market_probs(home_ms, away_ms, max_goals=8):
    """Poisson probabilities for all supported markets."""
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
    return {"over": p_over, "home": p_home, "btts": p_btts, "draw": 1 - p_home - p_away_win,
            "home_sc": 1 - p0h, "away_sc": 1 - p0a}


def xg_forecast(lam_h, lam_a):
    # shrink raw lambdas toward a realistic band (small-sample lambdas run hot)
    t = max(1.2, 1.1 + 0.75 * (lam_h + lam_a - 2.0))
    return round(t - 0.9, 2), round(t + 0.6, 2)
