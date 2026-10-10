"""Rules engine.

POSITIVE markets -- rule sets are coupled so that BTTS is the literal union
of the two team-to-score markets. Frequency thresholds come from FREQ_CFG
(tunable per category via OU_FREQ; scored/conceded default to 4/6, with 2/3 fallback).
Key relationships (enforced via _EXCLUDE and the btts override block):

  home_sc  = home attack (H6SO: 6/6 scored overall)
           + AWAY defence LEAKAGE (A9 away-venue, A12 overall, conceded cat)
           + L3 volume confirmations (H1 home GF, A11 away GA)

  away_sc  = away attack (A6SO: 6/6 scored overall)
           + HOME defence LEAKAGE (H8 home-venue, H12 overall, conceded cat)
           + L3 volume confirmations (A1 away GF, H10 home GA)

  btts     = both complete home_sc AND away_sc attack/leakage paths pass.

  over     -- each team's 4-of-6 venue match totals must exceed 2.5.
  over15   -- each team's 4-of-6 venue match totals must exceed 1.5.
  under    -- each team's 4-of-6 venue match totals must be 2.5 or lower.
  home/home_dw -- compare points earned per possible point in recent home-venue
                  and away-venue histories.

NEGATIVE markets (under, under35, no_btts) -- INDEPENDENT Statarea-style
rule sets, each with its own base dict, _EXCLUDE filter, injected per-market
rules, and H2H predicate.  They are NOT lazy inverses of over/btts.
Design differences vs the positive markets:

  under  (U 2.5) -- "low-tempo, at least one side defensively solid".
      Rules centre on blank/CS frequency + LOW attack volume, NOT just
      the boolean negation of over's "both teams attack well".  Uses
      H-suffixed U-rules + A-suffixed U-rules that mirror the positive
      home/away split but for DEFENSIVE form (cs/blank categories).

  under35 (U 3.5) -- "mostly normal tempo, but nothing explosive".
      Subset of under's defensive checks + additional "no blowout" rules
      (neither side scores 4+ in recent games) and a SOFTER attack ceiling
      than under (allows 1-1, 2-0 but blocks 3-1, 2-2, etc.).  Own base
      checks, own exclude set, own H2H predicate (total <= 3).

  no_btts (BTTS:NO) -- "one side blanks, or both are mid-table low-scoring".
      Literal inverse of btts would be: NOT(home_sc AND away_sc).  Instead,
      Statarea-style no_btts has POSITIVE evidence of non-goals: blank
      frequency, CS frequency, home-team road offence shutdown, away-team
      home offence shutdown.  Uses blank/cs categories explicitly and a
      new DOM-style check but now weighted across 3 evidence tiers.

H2H: expected result in >= half of last up-to-6 meetings; 1/1 counts;
     zero meetings is a neutral pass.
"""

import math

from .config import FREQ_CFG
from .teams import normalize


def _build_check_names(freq):
    """Build the check-name lookup table DYNAMICALLY from FREQ_CFG.

    This ensures the 'Missed' list in every pick block shows the REAL
    thresholds (4+/6, 5+/6, or 6+/6) that the rule engine actually used,
    not a hardcoded '4+/6'.  Freq categories map as follows:

      scored    -> H6, H7, A3, A8, A13
      conceded  -> H8, H12, A9, A12
      over      -> H2, A4
      blank     -> A18, NH_BL, NA_BL, UH_BLK, UA_BLK  (positive no-btts / under evidence)
      win       -> H16
      cs        -> (clean sheet freq category: NH_CS_H, NH_CS_A, NA_CS_H, NA_CS_A,
                    UH_CS_HV, UH_CS_OV, UA_CS_AV, UA_CS_OV)
      btts_game -> HB, AB
      nowin     -> A14, A15, A16

    NOTE: negative-market checks NO LONGER have 'u' / 'n' suffix that would
    make them look like inverses of positive-market IDs. They now have
    semantic prefixes:
      UH_*  = under-market, home side evidence
      UA_*  = under-market, away side evidence
      U35_* = under35, extra blowout / low-ceiling checks
      NH_*  = no-btts, home side blank / cs evidence
      NA_*  = no-btts, away side blank / cs evidence
      NB_*  = no-btts, bilateral evidence (both sides low scoring)
    """
    s = freq["scored"]["full"]
    c = freq["conceded"]["full"]
    o = freq["over"]["full"]
    b = freq["blank"]["full"]
    w = freq["win"]["full"]
    x = freq["cs"]["full"]
    t = freq["btts_game"]["full"]
    n = freq["nowin"]["full"]

    return {
        # Positive markets (kept unchanged for backcompat in missed-check labels)
        "H1": "Home goals L3 home (7+)",
        "H2": f"Home over 2.5 ({o}+/6 home)",
        "H2R": "Home over 2.5 (2+/3 recent home)",
        "O15_HV": "Home over 1.5 (4+/6 at home)",
        "O15_AV": "Away over 1.5 (4+/6 away)",
        "H3": "Home over 2.5 (L6 overall, >=50%)",
        "H4": "Home BTTS (L6 home, >=50%)",
        "H5": "Home BTTS (L6 overall, >=50%)",
        "H6": f"Home scored ({s}+/6 home)",
        "H7": f"Home scored ({s}+/6 overall)",
        "H6S": "Home scored (6/6 at home)",
        "H6SO": "Home scored (6/6 overall)",
        "H8": f"Home conceded ({c}+/6 home)",
        "H10": "Home conceded 7+ (L3 home)",
        "H12": f"Home concedes ({c}+/6 overall)",
        "H14": "Home form: 4W/6 or unbeaten 5/6 home",
        "H15": "Home form: 4W/6 or unbeaten 5/6 overall",
        "H16": f"Home win ({w}+/6 home)",
        "H17": "Home conceded <=2 (L3 home)",
        "A1": "Away goals L3 away (7+)",
        "A3": f"Away scored ({s}+/6 away)",
        "A4": f"Away over 2.5 ({o}+/6 away)",
        "A4R": "Away over 2.5 (2+/3 recent away)",
        "A5": "Away over 2.5 (L6 overall, >=50%)",
        "A6": "Away BTTS (L6 away, >=50%)",
        "A7": "Away BTTS (L6 overall, >=50%)",
        "A8": f"Away scored ({s}+/6 overall)",
        "A9": f"Away conceded ({c}+/6 away)",
        "A11": "Away conceded 7+ (L3 away)",
        "A12": f"Away concedes ({c}+/6 overall)",
        "A13": f"Away scored ({s}+/6 overall)",
        "A6S": "Away scored (6/6 away)",
        "A6SO": "Away scored (6/6 overall)",
        "A14": f"Away winless ({n}+/6 away)",
        "A15": f"Away winless ({n}+/6 overall)",
        "A16": f"Away no win ({n}+/6 away)",
        "A17": "Away scored <=4 (L3 away)",
        "A18": f"Away blanked ({b}+/6 away)",
        "S6": "Both teams active",
        "H2H": "Head-to-head pattern",
        "HP50": "Home points form at home (50%+)",
        "HP_EDGE": "Home points form stronger than away away-form",
        "HP_NOT_WORSE": "Home points form at least as strong as away away-form",
        "AP_LT50": "Away points form away (below 50%)",
        "HB": f"Home BTTS game ({t}+/6 home)",
        "AB": f"Away BTTS game ({t}+/6 away)",
        "O_PATH": "Over evidence: attack vs leaky defence or open-game form",
        # --- UNDER (U 2.5): independent, home-defence / away-defence oriented ---
        "UH_BLK":   f"Home at home blanks ({b}+/6 home)",
        "UH_BLK_O": f"Home overall blanks ({b}+/6 overall)",
        "UH_CS":    f"Home at home clean sheet ({x}+/6 home)",
        "UH_CS_O":  f"Home overall clean sheet ({x}+/6 overall)",
        "UH_GF_L3": "Home at home GF <=4 (L3 home)",
        "UH_GA_L3": "Home at home GA <=2 (L3 home)",
        "UH_UND":   f"Home at home under 2.5 ({o}+/6 home)",
        "UH_UND_O": f"Home overall under 2.5 ({o}+/6 overall)",
        "UA_BLK":   f"Away on road blanks ({b}+/6 away)",
        "UA_BLK_O": f"Away overall blanks ({b}+/6 overall)",
        "UA_CS":    f"Away on road clean sheet ({x}+/6 away)",
        "UA_CS_O":  f"Away overall clean sheet ({x}+/6 overall)",
        "UA_GF_L3": "Away on road GF <=4 (L3 away)",
        "UA_GA_L3": "Away on road GA <=2 (L3 away)",
        "UA_UND":   f"Away on road under 2.5 ({o}+/6 away)",
        "UA_UND_O": f"Away overall under 2.5 ({o}+/6 overall)",
        # --- UNDER35 (U 3.5): subset + no-blowout extra rules ---
        "U35_NOHI": "No 4+ goal home game L6 home",
        "U35_NOAI": "No 4+ goal away game L6 away",
        "U35_NOHI_O": "No 4+ goal home game L6 overall",
        "U35_NOAI_O": "No 4+ goal away game L6 overall",
        "U35_GF_CAP": "Home GF never >3 in last 6 home",
        "U35_GA_CAP": "Away GA never >3 in last 6 away",
        # --- NO-BTTS: positive evidence of zero-goal half on one or both sides ---
        "NH_BL":    f"Home at home blanks opponent's goals ({x}+/6 home -> away 0gf)",
        "NH_BL_O":  f"Home overall blanks opponent's goals ({x}+/6 overall)",
        "NH_BL_OWN":f"Home at home shut out themselves ({b}+/6 home -> home 0gf)",
        "NH_BTTS_L3":"Home home BTTS <=1 of L3",
        "NH_BTTS_L6":"Home home BTTS <=2 of L6",
        "NH_BTTS_O": "Home overall BTTS <=2 of L6",
        "NA_BL":    f"Away on road blanks opponent's goals ({x}+/6 away)",
        "NA_BL_O":  f"Away overall blanks opponent's goals ({x}+/6 overall)",
        "NA_BL_OWN":f"Away on road shut out themselves ({b}+/6 away)",
        "NA_BTTS_L3":"Away road BTTS <=1 of L3",
        "NA_BTTS_L6":"Away road BTTS <=2 of L6",
        "NA_BTTS_O": "Away overall BTTS <=2 of L6",
        "NB_BOTH":  "Both sides have >= 2 blanks L6 venue (BTTS impossible on 1 side)",
        "NB_LAM":   "Both Poisson lambdas < 1.0 combined < 1.8 (goals unlikely)",
    }


CHECK_NAMES = _build_check_names(FREQ_CFG)

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
    meetings.sort(key=lambda m: m.get("date", ""), reverse=True)
    meetings = meetings[:6]
    n = len(meetings)
    if n == 0:
        return True
    hits = sum(1 for m in meetings if pred(m))
    return hits * 2 >= n


def _venue_or(venue_ms, overall_ms, min_venue=3):
    """When a venue split has fewer than min_venue matches (typical for
    international teams that play most games at neutral / away venues),
    fall back to the team's overall history instead.  Venue form inferred
    from 0-2 matches is pure noise; overall form is strictly more
    informative than an all-False result."""
    if len(venue_ms) >= min_venue:
        return venue_ms
    return overall_ms


def _freq_cat(cat, ms, fn):
    """Category-tunable frequency rule.  Thresholds come from FREQ_CFG[cat]
    via env OU_FREQ (see config._parse_freq_thresholds):
         full  = numerator out of the last 6 (if len >= 6)
         short = numerator out of the last 3 (if 3 <= len < 6)
       len < 3  -> False (not enough evidence)."""
    cfg = FREQ_CFG.get(cat, {"full": 4, "short": 2})
    n = len(ms)
    if n >= 6:
        return sum(1 for m in ms[-6:] if fn(m)) >= cfg["full"]
    if n >= 3:
        return sum(1 for m in ms[-3:] if fn(m)) >= cfg["short"]
    return False


def _venue_4_of_6(ms, venue, predicate):
    """Venue-OR version: 4-of-6 venue-equivalent rate (~66.7%).

    For teams with sparse venue splits (national teams, neutral-venue
    tournaments, newly-promoted sides), fall back to overall L6 form via
    _venue_or.  The 4/6 = 66.7% bar is then scaled PROPORTIONALLY to the
    actual sample size (matching _strong_unbeaten):
      6 matches -> 4+    5 matches -> 4+    4 matches -> 3+    3 matches -> 2+
    This fixes international fixtures (England v Czech, Spain v Croatia)
    where the home venue split has 0-2 matches but overall L6 form clearly
    shows high-scoring or high-BTTS form."""
    overall = _last(ms, 6)
    recent_raw = _last(ms, 6, venue)
    recent = _venue_or(recent_raw, overall, 3)
    n = len(recent)
    if n >= 6:
        return sum(1 for m in recent if predicate(m)) >= 4
    if n >= 5:
        return sum(1 for m in recent if predicate(m)) >= 4
    if n >= 4:
        return sum(1 for m in recent if predicate(m)) >= 3
    if n >= 3:
        return sum(1 for m in recent if predicate(m)) >= 2
    return False


def _freq4(ms, fn):
    """Legacy wrapper: scored-conceded-over-blank default category = 4/6, 2/3."""
    return _freq_cat("scored", ms, fn)


def _freq3(ms, fn):
    """Legacy wrapper: win category = 3/6, 2/3."""
    return _freq_cat("win", ms, fn)


def _freq5(ms, fn):
    """Legacy wrapper: clean-sheet category = 5/6, 3/3."""
    return _freq_cat("cs", ms, fn)


def _strong_unbeaten(ms):
    """Acceptable home form: 4+ wins in 6 outright (2/3rds), OR unbeaten in
    5 of 6 (draws still count) when wins come with draws.

    Scales proportionally for smaller sample sizes (national teams often
    only have 3 matches after the _venue_or fallback kicks in)."""
    if not ms:
        return False
    wins_n = sum(1 for m in ms if m["gf"] > m["ga"])
    unbeaten_n = sum(1 for m in ms if m["gf"] >= m["ga"])
    n = len(ms)
    if n >= 6:
        return wins_n >= 4 or unbeaten_n >= 5
    if n >= 3:
        win_thr = max(1, round(4 * n / 6))
        unb_thr = max(1, round(5 * n / 6))
        return wins_n >= win_thr or unbeaten_n >= unb_thr
    return False


def _points_pct(ms):
    """Earned league points as a share of maximum points from recent matches."""
    if len(ms) < 3:
        return None
    points = sum(3 if m["gf"] > m["ga"] else 1 if m["gf"] == m["ga"] else 0
                 for m in ms[-6:])
    return points / (3 * len(ms[-6:]))


# Design: attack⇄leakage pairs are the high-signal evidence union, NOT the
# noisy "every-attack-streak" set.
#
# DESIGN NOTE for over / over15 (rewritten 2026-10-03.7):
#   Over now pairs attack evidence the SAME WAY btts does: each half of the
#   union is a to_score profile (home_sc or away_sc) which is "attack of one
#   side ⇄ leakage of the other side".
#     Home half (home_sc profile): home scoring + A9/A12 (AWAY LEAKAGE)
#     Away half (away_sc profile): away scoring + H8/H12 (HOME LEAKAGE)
#   Pure-over rate evidence (H2/H3/A4/A5 = 50% Over 2.5 bars) is KEPT.
#
#   EXCLUDED from Over (counts removed from denominator to clean signal):
#     (a) conceded-volume streak noise (H10/A11) — weak one-sided filters.
#     (b) standalone BTTS-rate checks (HB/AB/H5/A7) are not total-goal evidence.
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
#
# NEGATIVE-MARKET exclude sets:
#   under   drops the "mirror image" attack-oriented checks that have no
#     bearing on low-tempo fixtures.  For example: H1 (home GF ≥7 L3)
#     would make the check list inconsistent because under fires on LOW
#     scoring, so we exclude anything that measures high-scoring evidence
#     on the positive side.
#   under35 inherits most of under's exclude set, but DOES NOT exclude
#     H1/A1 (moderate attack volume is fine for under35; we only block
#     BLOWOUT checks via the dedicated U35_* set, which is always
#     evaluated so it's always in the denominator regardless of exclude).
#   no_btts drops any checks that measure OVER patterns, since BTTS-No is
#     about zero-goal halves, not "fewer than 3 goals total".
_EXCLUDE = {
    "over":    {"H4", "A6",
                # conceded-volume streak noise: weak one-sided filters
                "H1", "A1", "H10", "A11",
                # BTTS-rate / BTTS-game evidence = BTTS domain, NOT Over
                # (Over cares about TOTAL goals >= 3, not "goals on both sides");
                # NB BTTS itself excludes ALL 8 of H2/H3/H4/H5/A4/A5/A6/A7 + streaks
                "HB", "AB", "H5", "A7"},
    "over15":  {"H4", "H7", "A6", "A11", "H10",
                # Same BTTS-pattern cleanup as Over 2.5: BTTS-rate is not Over signal
                "HB", "AB", "H5", "A7"},
    "btts":    {"H2", "H3", "H4", "H5", "A4", "A5", "A6", "A7",
                "A11", "H10"},
    "home":    {"H2", "H3", "H4", "H5", "H8", "H10", "A1", "A3",
                "A4", "A5", "A6", "A7", "A11", "H17"},
    "home_sc": {"H2", "H3", "H4", "H5", "H8", "H10", "A3",
                "A4", "A5", "A6", "A7", "A11"},
    "away_sc": {"H2", "H3", "H4", "H5", "H6", "H7",
                "A4", "A5", "A6", "A7", "A9", "A11", "H10"},
    "home_dw": {"H2", "H3", "H4", "H5", "H8", "H10", "A1", "A3",
                "A4", "A5", "A6", "A7", "A11", "H17"},
    "under":   {"UH_GF_L3", "UA_GF_L3"},
    "under35": {"U35_GF_CAP", "U35_GA_CAP"},
    "no_btts": {"NH_BTTS_L3", "NA_BTTS_L3",
                # exclude btts-rate measures that double-count NB_BOTH logic
                "NH_BTTS_L6", "NA_BTTS_L6"},
}


def _under_checks(home_ms, away_ms, lam_h, lam_a):
    """INDEPENDENT under (U 2.5) check set.

    STATAREA-STYLE LOGIC (not an inverse of over's check set):
      * under fires on DEFENSIVE form (cs/blank categories) plus LOW attack
        volume, not "fewer than 3 goals this fixture".
      * Both sides are modelled symmetrically (unlike over which has heavy
        home-attack bias). Each side has 8 evidence categories:
          [venue blank] [overall blank] [venue clean-sheet] [overall clean-sheet]
          [L3 goals-for cap] [L3 goals-against cap]
          [venue under-rate] [overall under-rate]
      * That's 16 base checks total, minus _EXCLUDE["under"] drops the
        GF-cap and venue-rate (because venue-rate is partially redundant
        with blank+cs, making it a weak 3rd+ duplicate).
      * Expected denom ~ 14.
    """
    h3h = _last(home_ms, 3, "H")
    a3a = _last(away_ms, 3, "A")
    h6 = _last(home_ms, 6)
    a6 = _last(away_ms, 6)
    h6H = _venue_or(_last(home_ms, 6, "H"), h6, 3)
    a6A = _venue_or(_last(away_ms, 6, "A"), a6, 3)
    under_m = lambda m: _tot(m) <= 2.5
    return {
        "S6":       len(home_ms) >= 3 and len(away_ms) >= 3,
        # Home side
        "UH_BLK":   _freq_cat("blank", h6H, lambda m: m["gf"] == 0),
        "UH_BLK_O": _freq_cat("blank", h6,  lambda m: m["gf"] == 0),
        "UH_CS":    _freq_cat("cs",    h6H, lambda m: m["ga"] == 0),
        "UH_CS_O":  _freq_cat("cs",    h6,  lambda m: m["ga"] == 0),
        "UH_GF_L3": _low_volume_check(h3h, "gf", 4, 1.0),
        "UH_GA_L3": _low_volume_check(h3h, "ga", 2, 0.7),
        "UH_UND":   _freq_cat("over",  h6H, under_m),
        "UH_UND_O": _freq_cat("over",  h6,  under_m),
        # Away side
        "UA_BLK":   _freq_cat("blank", a6A, lambda m: m["gf"] == 0),
        "UA_BLK_O": _freq_cat("blank", a6,  lambda m: m["gf"] == 0),
        "UA_CS":    _freq_cat("cs",    a6A, lambda m: m["ga"] == 0),
        "UA_CS_O":  _freq_cat("cs",    a6,  lambda m: m["ga"] == 0),
        "UA_GF_L3": _low_volume_check(a3a, "gf", 4, 1.0),
        "UA_GA_L3": _low_volume_check(a3a, "ga", 2, 0.7),
        "UA_UND":   _freq_cat("over",  a6A, under_m),
        "UA_UND_O": _freq_cat("over",  a6,  under_m),
    }


def _under35_checks(home_ms, away_ms, lam_h, lam_a):
    """INDEPENDENT under35 (U 3.5) check set.

    Shares under's defensive focus but:
      * ALLOWS moderate attack volume (1-1, 2-0, 0-2 are fine)
      * BANS blowouts via dedicated U35_* ceiling checks (no 4+ goals in
        any single recent game for either side at their venue)
      * Expected denom ~ 14.
    """
    h6 = _last(home_ms, 6)
    a6 = _last(away_ms, 6)
    h6H = _venue_or(_last(home_ms, 6, "H"), h6, 3)
    a6A = _venue_or(_last(away_ms, 6, "A"), a6, 3)
    u35 = lambda m: _tot(m) <= 3
    checks = {
        "S6":         len(home_ms) >= 3 and len(away_ms) >= 3,
        # Shared defensive core with under: blank + cs evidence
        "UH_BLK":   _freq_cat("blank", h6H, lambda m: m["gf"] == 0),
        "UH_CS":    _freq_cat("cs",    h6H, lambda m: m["ga"] == 0),
        "UH_UND_O": _freq_cat("over",  h6,  u35),
        "UA_BLK":   _freq_cat("blank", a6A, lambda m: m["gf"] == 0),
        "UA_CS":    _freq_cat("cs",    a6A, lambda m: m["ga"] == 0),
        "UA_UND_O": _freq_cat("over",  a6,  u35),
        # Under35-unique: blowout bans.  These are NOT part of under,
        # because a 4-0 fixture is under(2.5)? NO.  Under(3.5)? NO.
        # So banning 4+ goal games is STRONGER evidence for under35 than
        # for under(2.5) -- hence a separate, dedicated rule class.
        "U35_NOHI":   not any(m["gf"] + m["ga"] >= 5 for m in h6H),
        "U35_NOAI":   not any(m["gf"] + m["ga"] >= 5 for m in a6A),
        "U35_NOHI_O": not any(m["gf"] + m["ga"] >= 5 for m in h6),
        "U35_NOAI_O": not any(m["gf"] + m["ga"] >= 5 for m in a6),
        # Goal-volume caps per half (individually, not summed):
        # Fixture can't be over(3.5) if neither side individually exceeds 3.
        "U35_GF_CAP": not any(m["gf"] > 3 for m in h6H),
        "U35_GA_CAP": not any(m["ga"] > 3 for m in a6A),
        # Rate-based evidence: most recent venue games under(3.5) overall
        "UH_UND":     _freq_cat("over", h6H, u35),
        "UA_UND":     _freq_cat("over", a6A, u35),
    }
    return checks


def _no_btts_checks(home_ms, away_ms, lam_h, lam_a):
    """INDEPENDENT no-btts (BTTS: NO) check set.

    NOT the boolean inverse of btts.  Statarea-style logic: NO BTTS means
    "at least one side will fail to score" — positive evidence of that:
      * Each side's venue blank-rate (opponents shut out at venue)
      * Each side's venue OWN shutout-rate (they themselves blanked)
      * Each side's venue BTTS ceiling (<= 2 of L6, <= 1 of L3)
      * Bilateral rule NB_BOTH: both sides blank >= 2 in L6 venue
        (this is the real smoking gun: 0-0 / 1-0 / 0-1 archetype)
      * NB_LAM: composite Poisson check: combined (lam_h + lam_a) < 1.8
        AND each lambda < 1.0.
    Expected denom ~ 14.
    """
    h3h = _last(home_ms, 3, "H")
    a3a = _last(away_ms, 3, "A")
    h6 = _last(home_ms, 6)
    a6 = _last(away_ms, 6)
    h6H = _venue_or(_last(home_ms, 6, "H"), h6, 3)
    a6A = _venue_or(_last(away_ms, 6, "A"), a6, 3)
    btts_m = lambda m: m["gf"] > 0 and m["ga"] > 0
    home_blanks = sum(1 for m in h6H if m["gf"] == 0)
    away_blanks = sum(1 for m in a6A if m["gf"] == 0)
    checks = {
        "S6": len(home_ms) >= 3 and len(away_ms) >= 3,
        # Home venue / overall evidence that away team scores zero (CS)
        "NH_BL":     _freq_cat("cs",   h6H, lambda m: m["ga"] == 0),
        "NH_BL_O":   _freq_cat("cs",   h6,  lambda m: m["ga"] == 0),
        # Home venue / overall evidence that home team scores zero (blanked)
        "NH_BL_OWN": _freq_cat("blank", h6H, lambda m: m["gf"] == 0),
        # BTTS ceilings for home venue + overall
        "NH_BTTS_L3": sum(1 for m in h3h if btts_m(m)) <= 1,
        "NH_BTTS_L6": sum(1 for m in h6H if btts_m(m)) <= 2,
        "NH_BTTS_O":  sum(1 for m in h6  if btts_m(m)) <= 2,
        # Away venue / overall evidence that home team scores zero (CS)
        "NA_BL":     _freq_cat("cs",   a6A, lambda m: m["ga"] == 0),
        "NA_BL_O":   _freq_cat("cs",   a6,  lambda m: m["ga"] == 0),
        # Away venue / overall evidence that away team scores zero (blanked)
        "NA_BL_OWN": _freq_cat("blank", a6A, lambda m: m["gf"] == 0),
        # BTTS ceilings for away venue + overall
        "NA_BTTS_L3": sum(1 for m in a3a if btts_m(m)) <= 1,
        "NA_BTTS_L6": sum(1 for m in a6A if btts_m(m)) <= 2,
        "NA_BTTS_O":  sum(1 for m in a6  if btts_m(m)) <= 2,
        # Bilateral composite rules (not present in any other market)
        "NB_BOTH":   (home_blanks >= 2 and away_blanks >= 2),
        "NB_LAM":    (lam_h < 1.0 and lam_a < 1.0 and (lam_h + lam_a) < 1.8),
    }
    return checks


def home_sc_leak_path_passes(checks):
    """Home scoring evidence paired with the away side's conceding record."""
    home_attack = (checks.get("H6SO", False) if "H6SO" in checks else
                   checks.get("H6", False) and checks.get("H7", False))
    return bool(home_attack
                and checks.get("A9", False) and checks.get("A12", False))


def away_sc_leak_path_passes(checks):
    """Away scoring evidence paired with the home side's conceding record."""
    away_attack = (checks.get("A6SO", False) if "A6SO" in checks else
                   checks.get("A3", False) and checks.get("A13", checks.get("A8", False)))
    return bool(away_attack
                and checks.get("H8", False) and checks.get("H12", False))


def over_attack_leak_path_passes(checks):
    """A scoring profile paired with the opposing team's leakage profile.

    The non-scoring team's own attack and the scoring team's own defence are
    deliberately not required for this route: one side can produce all three
    goals while the opponent's defensive record supplies the matchup evidence.
    """
    return (home_sc_leak_path_passes(checks)
            or away_sc_leak_path_passes(checks))


def over_path_passes(home_ms, away_ms, checks):
    """Require Over 2.5 to have a coherent venue+overall evidence path.

    Either a full attack faces the opposing side's full leakage profile, or
    open-game history for one team is paired with full scoring or conceding
    evidence from the other. The component frequency rules use FREQ_CFG.
    """
    h6 = _last(home_ms, 6)
    a6 = _last(away_ms, 6)
    h6H = _venue_or(_last(home_ms, 6, "H"), h6, 3)
    a6A = _venue_or(_last(away_ms, 6, "A"), a6, 3)
    btts = lambda m: m["gf"] > 0 and m["ga"] > 0
    attack_leak_path = over_attack_leak_path_passes(checks)
    home_open = (
        _freq_cat("btts_game", h6H, btts) and
        _freq_cat("btts_game", h6, btts))
    away_open = (
        _freq_cat("btts_game", a6A, btts) and
        _freq_cat("btts_game", a6, btts))
    away_evidence = ((checks["A3"] and checks["A8"]) or
                     (checks["A9"] and checks["A12"]))
    home_evidence = ((checks["H6"] and checks["H7"]) or
                     (checks["H8"] and checks["H12"]))
    return bool(
        attack_leak_path or
        (home_open and away_evidence) or
        (away_open and home_evidence))


def run_checks(home_ms, away_ms, market=None, home_name="", away_name="",
               lam_h=None, lam_a=None):
    # CHECK-ID ASYMMETRY DOC -- scored-category base count (why home=2, away=1, away=3):
    #   Home attack (scored): H6 venue + H7 overall  = 2 checks IN BASE DICT.
    #     Home venue = fixture host; home attack form ALWAYS relevant regardless of
    #     market, so base H6+H7 are included unconditionally for all markets.
    #   Away attack (scored): A3 venue             = 1 check IN BASE DICT.
    #     A8  overall -- injected for over/over15 branches only (below).
    #     A13 overall -- injected for btts/away_sc branches only (below).
    #   Net:
    #     + home_sc (home to score):    uses H6+H7 (both base).  2 checks.
    #     + away_sc (away to score):   uses A3 (base) + A13 (below).  2 checks.
    #     + over/over15:                uses H6+H7+A3 (base) + A8 (below).  4 checks.
    #     + btts (= home_sc U away_sc): uses H6+H7+A3 (base) + A13 (below). 4 checks.
    #   Rationale: away attack overall form (A8/A13) is expensive evidence for
    #   markets that don't require "both sides fire" (e.g. home only cares
    #   about home dominance, not if away scored well elsewhere); injecting it
    #   per-market lets each check_ratio reflect only the evidence relevant to that
    #   market.  Home attack overall is universally relevant because home is
    #   always the fixture host at their own stadium.
    #
    # Negative markets (under/under35/no_btts) have INDEPENDENT builders.
    # They do NOT share _negative_checks / do NOT short-circuit here anymore.
    if lam_h is None or lam_a is None:
        lam_h, lam_a = lambdas(home_ms, away_ms)

    if market == "under":
        checks = _under_checks(home_ms, away_ms, lam_h, lam_a)
        checks["UH_UND"] = _venue_4_of_6(
            home_ms, "H", lambda m: _tot(m) <= 2.5)
        checks["UA_UND"] = _venue_4_of_6(
            away_ms, "A", lambda m: _tot(m) <= 2.5)
        checks["H2H"] = h2h_check(home_ms, "under", away_name)
        if market in _EXCLUDE:
            for k in _EXCLUDE[market]:
                checks.pop(k, None)
        return checks
    if market == "under35":
        checks = _under35_checks(home_ms, away_ms, lam_h, lam_a)
        checks["H2H"] = h2h_check(home_ms, "under35", away_name)
        if market in _EXCLUDE:
            for k in _EXCLUDE[market]:
                checks.pop(k, None)
        return checks
    if market == "no_btts":
        checks = _no_btts_checks(home_ms, away_ms, lam_h, lam_a)
        checks["H2H"] = h2h_check(home_ms, "no_btts", away_name)
        if market in _EXCLUDE:
            for k in _EXCLUDE[market]:
                checks.pop(k, None)
        return checks

    h3h = _last(home_ms, 3, "H")
    a3a = _last(away_ms, 3, "A")
    h6 = _last(home_ms, 6)
    a6 = _last(away_ms, 6)
    h6H_raw = _last(home_ms, 6, "H")
    a6A_raw = _last(away_ms, 6, "A")
    h6H = _venue_or(h6H_raw, h6, 3)
    a6A = _venue_or(a6A_raw, a6, 3)
    over = lambda m: _tot(m) > 2.5
    btts = lambda m: m["gf"] > 0 and m["ga"] > 0

    checks = {
        "H1": _volume_check(h3h, "gf"),
        "H2": _freq_cat("over", h6H, over),
        "H3": _rate(h6, over) >= 0.5,
        "H4": _rate(h6H, btts) >= 0.5,
        "H5": _rate(h6, btts) >= 0.5,
        "H6": _freq_cat("scored", h6H, lambda m: m["gf"] > 0),
        "H7": _freq_cat("scored", h6, lambda m: m["gf"] > 0),
        "H8": _freq_cat("conceded", h6H, lambda m: m["ga"] > 0),
        "H10": _volume_check(h3h, "ga"),
        "A1": _volume_check(a3a, "gf"),
        "A3": _freq_cat("scored", a6A, lambda m: m["gf"] > 0),
        "A4": _freq_cat("over", a6A, over),
        "A5": _rate(a6, over) >= 0.5,
        "A6": _rate(a6A, btts) >= 0.5,
        "A7": _rate(a6, btts) >= 0.5,
        "A9": _freq_cat("conceded", a6A, lambda m: m["ga"] > 0),
        "A11": _volume_check(a3a, "ga"),
        "S6": len(home_ms) >= 3 and len(away_ms) >= 3,
    }
    # drop base checks that don't count as evidence for this market
    if market in _EXCLUDE:
        for k in _EXCLUDE[market]:
            checks.pop(k, None)

    if market in ("over", "over15"):
        # attack⇄leakage pairing, MATCHING btts symmetric union profile:
        #   Home half (home_sc profile): H6/H7 home ATTACK  + A9/A12 AWAY LEAKAGE
        #   Away half (away_sc profile): A3/A8 away ATTACK  + H8/H12 HOME LEAKAGE
        # Base checks already give us H6/H7, A3, H8, A9. We inject the
        #   overall rates (A8 away scored overall, H12 home conceded overall,
        #   A12 away conceded overall) so each half has venue+overall pairs,
        #   identical to the to_score markets' architecture.
        # Pure-over rate (H2/H3/A4/A5 = 50% O2.5 bars) comes through from the
        #   base dict and is KEPT — it's Over-specific signal, not BTTS noise.
        checks.update({
            "A8":  _freq_cat("scored",   a6, lambda m: m["gf"] > 0),
            "H12": _freq_cat("conceded", h6, lambda m: m["ga"] > 0),
            "A12": _freq_cat("conceded", a6, lambda m: m["ga"] > 0),
        })
        # Over25Tips' H2/A4 short-window trend: 2+ of each team's last 3
        # venue games went over 2.5. Keep these as optional evidence; the
        # established 4-of-6 venue gates below remain the eligibility rule.
        checks["H2R"] = (len(h3h) == 3 and
                         sum(1 for m in h3h if _tot(m) > 2.5) >= 2)
        checks["A4R"] = (len(a3a) == 3 and
                         sum(1 for m in a3a if _tot(m) > 2.5) >= 2)
        if market == "over":
            checks["H2"] = _venue_4_of_6(
                home_ms, "H", lambda m: _tot(m) > 2.5)
            checks["A4"] = _venue_4_of_6(
                away_ms, "A", lambda m: _tot(m) > 2.5)
        else:
            checks["O15_HV"] = _venue_4_of_6(
                home_ms, "H", lambda m: _tot(m) > 1.5)
            checks["O15_AV"] = _venue_4_of_6(
                away_ms, "A", lambda m: _tot(m) > 1.5)
    elif market == "btts":
        # BTTS is the intersection of the two team-to-score markets:
        #   home_sc: H6SO (6/6 overall) + A9/A12 (away concedes venue+overall)
        #   away_sc: A6SO (6/6 overall) + H8/H12 (home concedes venue+overall)
        # Venue scoring rates remain optional supporting evidence, not extra
        # requirements beyond both directional score paths.
        checks.update({
            "H6": _venue_4_of_6(home_ms, "H", lambda m: m["gf"] > 0),
            "H7": _freq_cat("scored", h6, lambda m: m["gf"] > 0),
            "A3": _venue_4_of_6(away_ms, "A", lambda m: m["gf"] > 0),
            "A13": _freq_cat("scored", a6, lambda m: m["gf"] > 0),
            "A12": _freq_cat("conceded", a6, lambda m: m["ga"] > 0),
            "H12": _freq_cat("conceded", h6, lambda m: m["ga"] > 0),
            "H6SO": len(h6) == 6 and all(m["gf"] > 0 for m in h6),
            "A6SO": len(a6) == 6 and all(m["gf"] > 0 for m in a6),
        })
    elif market == "home":
        # Compare points-per-match at each team's venue rather than win counts.
        # _venue_or fallback: national teams play <3 home/away venue matches
        # in a calendar window; fall back to overall L6 so points-pct computes.
        hp = _points_pct(_venue_or(_last(home_ms, 6, "H"), h6, 3))
        ap = _points_pct(_venue_or(_last(away_ms, 6, "A"), a6, 3))
        checks.update({
            "A12": _freq_cat("conceded", a6, lambda m: m["ga"] > 0),
            # Preserve the original home-win evidence alongside points form.
            "H14": _strong_unbeaten(h6H),
            "H15": _strong_unbeaten(h6),
            "H16": _freq_cat("win", h6H, lambda m: m["gf"] > m["ga"]),
            "A16": _freq_cat("nowin", a6A, lambda m: m["gf"] <= m["ga"]),
            "HP50": hp is not None and hp >= 0.50,
            "HP_EDGE": hp is not None and ap is not None and hp > ap,
            "HP_NOT_WORSE": hp is not None and ap is not None and hp >= ap,
            "AP_LT50": ap is not None and ap < 0.50,
        })
    elif market == "home_sc":
        # Home scoring markets require the home team to score in all six recent
        # matches overall; opponent leakage remains required at venue and overall.
        checks.pop("H6", None)
        checks.pop("H7", None)
        checks["A12"] = _freq_cat("conceded", a6, lambda m: m["ga"] > 0)
        checks["H6SO"] = len(h6) == 6 and all(m["gf"] > 0 for m in h6)
    elif market == "away_sc":
        # Away scoring markets require the away team to score in all six recent
        # matches overall; opponent leakage remains required at venue and overall.
        checks.pop("A3", None)
        checks.pop("A8", None)
        checks.pop("A13", None)
        checks.update({
            "A6SO": len(a6) == 6 and all(m["gf"] > 0 for m in a6),
            "H12": _freq_cat("conceded", h6, lambda m: m["ga"] > 0),
        })
    elif market == "home_dw":
        # For 1X, home points form can equal the away points form.
        # _venue_or fallback for sparse venue data (national teams).
        hp = _points_pct(_venue_or(_last(home_ms, 6, "H"), h6, 3))
        ap = _points_pct(_venue_or(_last(away_ms, 6, "A"), a6, 3))
        checks.update({
            "A12": _freq_cat("conceded", a6, lambda m: m["ga"] > 0),
            # Keep the previous unbeaten / away-no-win evidence as well as
            # the newer venue points-form checks.
            "H14": _strong_unbeaten(h6H),
            "H15": _strong_unbeaten(h6),
            "A14": _freq_cat("nowin", a6A, lambda m: m["gf"] <= m["ga"]),
            "A15": _freq_cat("nowin", a6, lambda m: m["gf"] <= m["ga"]),
            "HP50": hp is not None and hp >= 0.50,
            "HP_EDGE": hp is not None and ap is not None and hp > ap,
            "HP_NOT_WORSE": hp is not None and ap is not None and hp >= ap,
            "AP_LT50": ap is not None and ap < 0.50,
            "H17": _low_volume_check(h3h, "ga", 2, 0.7),
            "A17": _low_volume_check(a3a, "gf", 4, 1.0),
            "A18": _freq_cat("blank", a6A, lambda m: m["gf"] == 0),
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
