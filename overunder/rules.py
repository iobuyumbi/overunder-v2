"""Rules engine.

POSITIVE markets -- rule sets are coupled so that BTTS is the literal union
of the two team-to-score markets. Frequency thresholds come from FREQ_CFG
(tunable per category via OU_FREQ; scored/conceded default to 4/6, with 2/3 fallback).
Key relationships (enforced via _EXCLUDE and the btts override block):

  home_sc  = home attack (H6/H7, scored category)
           + AWAY defence LEAKAGE (A9 away-venue, A12 overall, conceded cat)
           + L3 volume confirmations (H1 home GF, A11 away GA)

  away_sc  = away attack (A3/A13, scored category)
           + HOME defence LEAKAGE (H8 home-venue, H12 overall, conceded cat)
           + L3 volume confirmations (A1 away GF, H10 home GA)

  btts     = both teams must score regularly and concede regularly in their
             venue and overall histories (each uses the configured frequency threshold).

  over     -- needs a full scoring attack facing a full opponent leakage
             profile, OR open-game form paired with the other side's full
             scoring or conceding profile. Also uses Over-rate checks.
  over15   -- uses the same venue+overall scoring/leak checks, plus Over-rate checks
  home     -- home dominance (H16, win category) + acceptable-form rule
             (H14/H15: 4 wins/6 OR unbeaten 5/6) + home solidity (H17)
             + away no-win (A16, nowin cat) + away leaks (A9/A12)
  over   (O 2.5) -- requires one coherent attack/leak or open-game path;
             component checks include H6/H7/A3/A8 scoring, H8/H12/A9/A12
             conceding, H2/H3/A4/A5 Over rates, and H2H.
  over15 (O 1.5) -- same symmetric attack⇄leakage Over profile minus the
             H7-strong-attack and overall-venue over-rate bars (Over1.5 fires
             on more ordinary attack evidence, so those are over-filtering).

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
        "H3": "Home over 2.5 (L6 overall, >=50%)",
        "H4": "Home BTTS (L6 home, >=50%)",
        "H5": "Home BTTS (L6 overall, >=50%)",
        "H6": f"Home scored ({s}+/6 home)",
        "H7": f"Home scored ({s}+/6 overall)",
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
        "A5": "Away over 2.5 (L6 overall, >=50%)",
        "A6": "Away BTTS (L6 away, >=50%)",
        "A7": "Away BTTS (L6 overall, >=50%)",
        "A8": f"Away scored ({s}+/6 overall)",
        "A9": f"Away conceded ({c}+/6 away)",
        "A11": "Away conceded 7+ (L3 away)",
        "A12": f"Away concedes ({c}+/6 overall)",
        "A13": f"Away scored ({s}+/6 overall)",
        "A14": f"Away winless ({n}+/6 away)",
        "A15": f"Away winless ({n}+/6 overall)",
        "A16": f"Away no win ({n}+/6 away)",
        "A17": "Away scored <=4 (L3 away)",
        "A18": f"Away blanked ({b}+/6 away)",
        "S6": "Both teams active",
        "H2H": "Head-to-head pattern",
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
    5 of 6 (draws still count) when wins come with draws."""
    if not ms:
        return False
    wins_n = sum(1 for m in ms if m["gf"] > m["ga"])
    unbeaten_n = sum(1 for m in ms if m["gf"] >= m["ga"])
    n = len(ms)
    if n >= 6:
        return wins_n >= 4 or unbeaten_n >= 5
    if n >= 4:
        win_thr = max(1, round(4 * n / 6))
        unb_thr = max(1, round(5 * n / 6))
        return wins_n >= win_thr or unbeaten_n >= unb_thr
    return False


# Design: attack⇄leakage pairs are the high-signal evidence union, NOT the
# noisy "every-attack-streak" set.
#
# DESIGN NOTE for over / over15 (rewritten 2026-10-03.7):
#   Over now pairs attack evidence the SAME WAY btts does: each half of the
#   union is a to_score profile (home_sc or away_sc) which is "attack of one
#   side ⇄ leakage of the other side".
#     Home half (home_sc profile): H6/H7 (home ATTACK) + A9/A12 (AWAY LEAKAGE)
#     Away half (away_sc profile): A3/A8 (away ATTACK) + H8/H12 (HOME LEAKAGE)
#   Pure-over rate evidence (H2/H3/A4/A5 = 50% Over 2.5 bars) is KEPT.
#
#   EXCLUDED from Over (counts removed from denominator to clean signal):
#     (a) L3 volume streak noise (H1/A1/H10/A11) — kills "one lucky blowout
#         in L3 form is good enough" weak filters
#     (b) standalone BTTS-rate checks (HB/AB/H5/A7); O_PATH is a separate
#         signal. O_PATH separately allows strong open-game history only when
#         paired with the opposing team's full scoring or conceding profile.
#   O_PATH is an eligibility condition, not an extra confidence vote.
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
                # L3 volume streak noise: "one blowout in 3 games" is weak signal
                "H1", "A1", "H10", "A11",
                # BTTS-rate / BTTS-game evidence = BTTS domain, NOT Over
                # (Over cares about TOTAL goals >= 3, not "goals on both sides");
                # NB BTTS itself excludes ALL 8 of H2/H3/H4/H5/A4/A5/A6/A7 + streaks
                "HB", "AB", "H5", "A7"},
    "over15":  {"H4", "H7", "A6", "H1", "A1", "A11", "H10",
                # Same BTTS-pattern cleanup as Over 2.5: BTTS-rate is not Over signal
                "HB", "AB", "H5", "A7"},
    "btts":    {"H2", "H3", "H4", "H5", "A4", "A5", "A6", "A7",
                "H1", "A11", "A1", "H10"},
    "home":    {"H2", "H3", "H4", "H5", "H8", "H10", "A1", "A3",
                "A4", "A5", "A6", "A7", "A11", "H17"},
    "home_sc": {"H2", "H3", "H4", "H5", "H8", "H10", "A1", "A3",
                "A4", "A5", "A6", "A7", "H1", "A11"},
    "away_sc": {"H1", "H2", "H3", "H4", "H5", "H6", "H7",
                "A4", "A5", "A6", "A7", "A9", "A11", "A1", "H10"},
    "home_dw": {"H2", "H3", "H4", "H5", "H8", "H10", "A1", "A3",
                "A4", "A5", "A6", "A7", "A11", "H17"},
    "under":   {"UH_GF_L3", "UA_GF_L3",
                # exclude patterns that measure HIGH total goal volume
                # on the positive side (irrelevant / double-counting):
                "UH_UND", "UA_UND"},
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
    h6H = _last(home_ms, 6, "H")
    a6A = _last(away_ms, 6, "A")
    under_m = lambda m: _tot(m) <= 2.5
    return {
        "S6":       len(home_ms) >= 4 and len(away_ms) >= 4,
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
    h6H = _last(home_ms, 6, "H")
    a6A = _last(away_ms, 6, "A")
    u35 = lambda m: _tot(m) <= 3
    checks = {
        "S6":         len(home_ms) >= 4 and len(away_ms) >= 4,
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
    h6H = _last(home_ms, 6, "H")
    a6A = _last(away_ms, 6, "A")
    btts_m = lambda m: m["gf"] > 0 and m["ga"] > 0
    home_blanks = sum(1 for m in h6H if m["gf"] == 0)
    away_blanks = sum(1 for m in a6A if m["gf"] == 0)
    checks = {
        "S6": len(home_ms) >= 4 and len(away_ms) >= 4,
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


def over_path_passes(home_ms, away_ms, checks):
    """Require Over 2.5 to have a coherent venue+overall evidence path.

    Either a full attack faces the opposing side's full leakage profile, or
    open-game history for one team is paired with full scoring or conceding
    evidence from the other. The component frequency rules use FREQ_CFG.
    """
    h6 = _last(home_ms, 6)
    a6 = _last(away_ms, 6)
    h6H = _last(home_ms, 6, "H")
    a6A = _last(away_ms, 6, "A")
    btts = lambda m: m["gf"] > 0 and m["ga"] > 0
    home_attack_away_leak = (
        checks["H6"] and checks["H7"] and checks["A9"] and checks["A12"])
    away_attack_home_leak = (
        checks["A3"] and checks["A8"] and checks["H8"] and checks["H12"])
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
        home_attack_away_leak or away_attack_home_leak or
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
    h6H = _last(home_ms, 6, "H")
    a6A = _last(away_ms, 6, "A")
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
        "S6": len(home_ms) >= 4 and len(away_ms) >= 4,
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
    elif market == "btts":
        # btts = home_sc U away_sc -- the full union:
        #   Requires BOTH teams to show their own scoring and conceding form:
        #   home scored H6/H7 + home conceded H8/H12; away scored A3/A13 +
        #   away conceded A9/A12. Each pair covers venue and overall history.
        #   Thus each team has been scoring and conceding, independently of
        #   whether the other team is strong or weak.
        # Base checks already provide A9/A11 and H8/H10; we add the venue+overall
        # conceded rates (A12/H12 via conceded category) and overall scoring
        # (H7/A13 via scored category).
        checks.update({
            "H6": _freq_cat("scored", h6H, lambda m: m["gf"] > 0),
            "H7": _freq_cat("scored", h6, lambda m: m["gf"] > 0),
            "A3": _freq_cat("scored", a6A, lambda m: m["gf"] > 0),
            "A13": _freq_cat("scored", a6, lambda m: m["gf"] > 0),
            "A12": _freq_cat("conceded", a6, lambda m: m["ga"] > 0),
            "H12": _freq_cat("conceded", h6, lambda m: m["ga"] > 0),
        })
    elif market == "home":
        # Home-win evidence: home attack against an away defence that leaks,
        # plus home form and away road no-win form.
        checks.update({
            "A12": _freq_cat("conceded", a6, lambda m: m["ga"] > 0),
            "H14": _strong_unbeaten(h6H),
            "H15": _strong_unbeaten(h6),
            "H16": _freq_cat("win", h6H, lambda m: m["gf"] > m["ga"]),
            "A16": _freq_cat("nowin", a6A, lambda m: m["gf"] <= m["ga"]),
        })
    elif market == "home_sc":
        # home_sc: home attack (scored freq) + AWAY concedes (venue freq via base A9,
        # venue volume via A11, plus overall A12 via conceded category).
        checks["A12"] = _freq_cat("conceded", a6, lambda m: m["ga"] > 0)
        checks["H6"] = _freq_cat("scored", h6H, lambda m: m["gf"] > 0)
        checks["H7"] = _freq_cat("scored", h6, lambda m: m["gf"] > 0)
    elif market == "away_sc":
        # away_sc: away attack (scored freq) + HOME concedes (venue freq via base H8,
        # venue volume via H10, plus overall H12 via conceded category).
        checks.update({
            "A3": _freq_cat("scored", a6A, lambda m: m["gf"] > 0),
            "A13": _freq_cat("scored", a6, lambda m: m["gf"] > 0),
            "H12": _freq_cat("conceded", h6, lambda m: m["ga"] > 0),
        })
    elif market == "home_dw":
        # home's evidence but draw-friendly: winless (not loss-heavy) away
        checks.update({
            "A12": _freq_cat("conceded", a6, lambda m: m["ga"] > 0),
            "H14": _strong_unbeaten(h6H),
            "H15": _strong_unbeaten(h6),
            "H17": _low_volume_check(h3h, "ga", 2, 0.7),
            "A14": _freq_cat("nowin", a6A, lambda m: m["gf"] <= m["ga"]),
            "A15": _freq_cat("nowin", a6, lambda m: m["gf"] <= m["ga"]),
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
