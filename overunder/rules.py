"""The over25tips.com public ruleset (H1/H2/A1-A4) + supporting checks,
plus a Poisson goals model. Rules produce the 'Profile: N/13 checks passed'
that mirrors the classic report format.

Check list (13):
  H1  home goals in last 3 home >= 7
  H2  2+ of last 3 home over 2.5
  A1  away goals in last 3 away >= 7
  A2  away previous match total >= 2
  A3  away scored in 2+ of last 3
  A4  2+ of last 3 away over 2.5
  S1  home scored in 2+ of last 3
  S2  home over2.5 rate (last 6) >= 50%
  S3  away over2.5 rate (last 6) >= 50%
  S4  home BTTS rate (last 6) >= 50%
  S5  away BTTS rate (last 6) >= 50%
  S6  both teams active (played recently / no long gaps)
  S7  combined goals trend rising (last 3 totals >= previous 3)
"""

import math

CHECK_NAMES = {
    "H1": "Home goals L3 home (7+)",
    "H2": "Home over 2.5 (L3 home)",
    "A1": "Away goals L3 away (7+)",
    "A2": "Away prev match 2+ goals",
    "A3": "Away scored (L3)",
    "A4": "Away over 2.5 (L3 away)",
    "S1": "Home scored (L3)",
    "S2": "Home over 2.5 (L6)",
    "S3": "Away over 2.5 (L6)",
    "S4": "Home BTTS (L6)",
    "S5": "Away BTTS (L6)",
    "S6": "Both teams active",
    "S7": "Goals trend rising",
}


def _last(matches, n, venue=None):
    ms = [m for m in matches if venue is None or m["venue"] == venue]
    return ms[-n:]


def _tot(m):
    return m["gf"] + m["ga"]


def run_checks(home_ms, away_ms):
    h3h = _last(home_ms, 3, "H")
    a3a = _last(away_ms, 3, "A")
    h6 = _last(home_ms, 6)
    a6 = _last(away_ms, 6)
    a3 = _last(away_ms, 3)
    h3 = _last(home_ms, 3)
    last3 = (h3h + a3a)[-3:]
    prev3 = (h3h + a3a)[-6:-3]

    def rate(ms, fn):
        return sum(1 for m in ms if fn(m)) / len(ms) if ms else 0.0

    checks = {
        "H1": sum(m["gf"] for m in h3h) >= 7,
        "H2": sum(1 for m in h3h if _tot(m) > 2.5) >= 2,
        "A1": sum(m["gf"] for m in a3a) >= 7,
        "A2": (_tot(away_ms[-1]) >= 2) if away_ms else False,
        "A3": sum(1 for m in a3 if m["gf"] > 0) >= 2,
        "A4": sum(1 for m in a3a if _tot(m) > 2.5) >= 2,
        "S1": sum(1 for m in h3 if m["gf"] > 0) >= 2,
        "S2": rate(h6, lambda m: _tot(m) > 2.5) >= 0.5,
        "S3": rate(a6, lambda m: _tot(m) > 2.5) >= 0.5,
        "S4": rate(h6, lambda m: m["gf"] > 0 and m["ga"] > 0) >= 0.5,
        "S5": rate(a6, lambda m: m["gf"] > 0 and m["ga"] > 0) >= 0.5,
        "S6": len(home_ms) >= 6 and len(away_ms) >= 6,
        "S7": (sum(_tot(m) for m in last3) > sum(_tot(m) for m in prev3)) if len(prev3) == 3 else False,
    }
    return checks


def poisson_over25(home_ms, away_ms,
                   lg_home=1.45, lg_away=1.15, max_goals=8):
    """P(Over 2.5) via independent Poisson lambdas from attack/defence rates."""

    def avg(ms, venue, key):
        sel = [m for m in ms if m["venue"] == venue]
        return (sum(m[key] for m in sel) / len(sel)) if sel else (lg_home if key == "gf" else 1.3)

    atk_h = max(0.4, avg(home_ms, "H", "gf") / lg_home)
    dfc_h = max(0.4, avg(home_ms, "H", "ga") / lg_away)
    atk_a = max(0.4, avg(away_ms, "A", "gf") / lg_away)
    dfc_a = max(0.4, avg(away_ms, "A", "ga") / lg_home)

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
    # shrink raw lambdas toward a realistic band (small-sample lambdas run hot)
    t = max(1.2, 1.1 + 0.75 * (lam_h + lam_a - 2.0))
    return round(t - 0.9, 2), round(t + 0.6, 2)
