"""Central configuration. Override any value via environment variable of the same
name (see .env.example) or by editing here."""

import os


def _load_dotenv():
    """Load KEY=VALUE pairs from a local .env (cwd, then package root).
    Real environment variables always win. .env is gitignored -- never commit it.

    Non-empty, non-comment lines without an '=' are suspicious (a human note that
    looks like it was meant to be a setting, e.g. "Strict 6/6"). Emit a warning
    to stderr instead of silently skipping them so the user catches typos fast.
    """
    import sys as _sys
    for base in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        path = os.path.join(base, ".env")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                raw = line.rstrip("\n").rstrip("\r")
                stripped = raw.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" not in stripped:
                    print(
                        f"[config] WARNING .env {os.path.basename(path)} L{lineno}: "
                        f"line skipped (no '=' found, not a comment): "
                        f"{raw!r}",
                        file=_sys.stderr,
                    )
                    continue
                k, _, v = stripped.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)
        break


_load_dotenv()

# --- model thresholds -------------------------------------------------------
O25_MIN_CONFIDENCE = float(os.getenv("O25_MIN_CONFIDENCE", "0.55"))
# Conservative Over 2.5 confidence floor. A directional scoring-vs-leakage
# path remains required, but it no longer bypasses the check-ratio blend or
# drops the selection bar below the stable 0.85 setting.
OVER_DIRECTIONAL_MIN_CONFIDENCE = float(
    os.getenv("OVER_DIRECTIONAL_MIN_CONFIDENCE", "0.85"))


def _parse_market_min_conf():
    """Per-market confidence gates. Defaults come from the 47-day tier analysis:
       over 76.7% @0.85+, btts ~67% @0.75+, home ~63% @0.75+ (monotonic),
       team-to-score only clear real-odds breakeven at the top tiers,
       under/no_btts showed no edge -> 0.99 effectively disables them as singles.
    Override with env, e.g. MARKET_MIN_CONF="over:0.80,under:0.90" """
    defaults = {"over": 0.85, "btts": 0.75, "home": 0.85,
                "home_sc": 0.85, "away_sc": 0.80,
                "under": 0.99, "no_btts": 0.99,
                # safer lines: high floors, real breakevens are ~75-83%
                "over15": 0.92, "under35": 0.90, "home_dw": 0.88}
    raw = os.getenv("MARKET_MIN_CONF", "")
    for pair in raw.split(","):
        if ":" in pair:
            k, _, v = pair.partition(":")
            try:
                defaults[k.strip()] = float(v)
            except ValueError:
                pass
    return defaults


MARKET_MIN_CONF = _parse_market_min_conf()
PREMIUM_TIER = float(os.getenv("PREMIUM_TIER", "0.85"))   # >= -> 🔥 Premium


def _parse_freq_thresholds():
    """Per-category frequency thresholds.  Each category defines:
         full   = numerator out of the last 6 matches (default window)
         short  = numerator out of the last 3 matches (fallback when <6 exist)

    CATEGORY DEFINITION TABLE (OU_FREQ = 8 categories × what they gate)
    ------------------------------------------------------------------
    Each token cat:N:M means "cat happened in N+/6 matches (or M+/3 fallback)".
    Predicate used inside _freq_cat() is always the same per category.

    Category    | _freq_cat predicate   | Check-IDs powered by this category
    ------------|-----------------------|---------------------------------------------
    scored      | team scored ≥1 goal   | Home attack : H6 (home venue), H7 (overall)
                |   (gf > 0)            | Away attack : A3 (away venue),
                |                       |               A8 (overall -- over/over15 only),
                |                       |               A13 (overall -- btts/away_sc only)
                |   NOTE home attack has 2 BASE checks (H6+H7), away attack has
                |        only 1 BASE check (A3). A8/A13 are AWAY-OVERALL scored,
                |        injected CONDITIONALLY per market by run_checks to
                |        complete the "both attacks fire" profile only for
                |        markets that need it. See asymmetry doc in run_checks.
    ------------|-----------------------|---------------------------------------------
    conceded    | team conceded ≥1 goal | Home defence leaks: H8 (home venue),
                |   (ga > 0)            |                   H12 (overall, btts/home_sc/home/home_dw)
                |                       | Away defence leaks: A9 (away venue),
                |                       |                   A12 (overall, btts/home/home_sc/home_dw)
    ------------|-----------------------|---------------------------------------------
    over        | match total goals > X | H2 (home venue over 2.5 freq),
                |   (lambda is per      | A4 (away venue over 2.5 freq),
                |    market: over/under)| H2u (home venue under 2.5 freq, under-set),
                |                       | A4u (away venue under 2.5 freq, under-set)
    ------------|-----------------------|---------------------------------------------
    blank       | team scored 0 goals   | Away attack absent : A3u (away venue, under-set),
                |   (gf == 0)           |                      A18 (away venue, home_dw)
                |                       | No-btts defence   : H6n (home venue blanked rate),
                |                       |                      A3n (away venue blanked rate),
                |                       |                      A8n (away overall blanked rate)
    ------------|-----------------------|---------------------------------------------
    win         | team won outright     | H16 (home venue outright wins, home market)
                |   (gf > ga)           |
    ------------|-----------------------|---------------------------------------------
    cs          | team kept clean sheet | No-btts defence : H8n (home venue CS rate),
                |   (ga == 0)           |                  H9n (home overall CS rate),
                |                       |                  A9n (away venue CS rate),
                |                       |                  A10n (away overall CS rate)
    ------------|-----------------------|---------------------------------------------
    btts_game   | both teams scored in  | HB (home venue BTTS-rate, over/over15 only),
                | the same game         | AB (away venue BTTS-rate, over/over15 only)
                |   (gf > 0 AND ga > 0) |
    ------------|-----------------------|---------------------------------------------
    nowin       | team failed to win    | A14 (away venue nowin rate, home_dw),
                | (drew or lost:        | A15 (away overall nowin rate, home_dw),
                |    gf <= ga)          | A16 (away venue nowin rate, home market)
    ---------------------------------------------------------------------------

       Defaults use the relaxed 4/6 (2/3 short-window) form thresholds for
       scored, conceded, over, blank, and nowin. Win, clean-sheet, and BTTS
       game thresholds retain their own category-specific defaults.
       Override with env OU_FREQ to tune a category.
    """
    defaults = {
        "scored":   {"full": 4, "short": 2},
        "conceded": {"full": 4, "short": 2},
        "over":     {"full": 4, "short": 2},
        "blank":    {"full": 4, "short": 2},
        "win":      {"full": 3, "short": 2},
        "cs":       {"full": 5, "short": 3},
        "btts_game": {"full": 3, "short": 2},
        "nowin":    {"full": 4, "short": 2},
    }
    raw = os.getenv("OU_FREQ", "")
    for pair in raw.split(","):
        if ":" not in pair:
            continue
        cat, _, rest = pair.partition(":")
        cat = cat.strip()
        if cat not in defaults:
            continue
        if ":" not in rest:
            continue
        fs, _, ss = rest.partition(":")
        try:
            defaults[cat]["full"] = max(1, min(6, int(fs.strip())))
            defaults[cat]["short"] = max(1, min(3, int(ss.strip())))
        except ValueError:
            pass
    return defaults


FREQ_CFG = _parse_freq_thresholds()


def _parse_market_premium():
    """Per-market 🔥 Premium thresholds. Premium means 'top pick within THIS
    market', so EVERY market must have its Premium bar ABOVE its entry gate
    -- otherwise every qualified pick is Premium by construction and Solid
    can never appear in that market.

    Default: Premium = gate + 3pp (if gate ≤ 0.96, otherwise no room).
    Env override:  MARKET_PREMIUM="btts:0.80,away_sc:0.83,over:0.88"
    """
    defaults = {}
    for mkt, gate in MARKET_MIN_CONF.items():
        # Only 1-3 markets have explicit legacy overrides (btts 0.80 had
        # historical win-rate justification).  Remaining markets are
        # synthesised gate + 3pp so EVERY market has a 3pp Premium lead.
        legacy = {"btts": 0.80, "away_sc": 0.83}
        if mkt in legacy:
            defaults[mkt] = legacy[mkt]
        elif gate <= 0.96:
            defaults[mkt] = round(gate + 0.03, 3)
        else:
            # Gates at/above 0.97 (under/no_btts effectively disabled)
            # have no headroom; Premium bar equals gate (no Solid possible).
            defaults[mkt] = gate
    raw = os.getenv("MARKET_PREMIUM", "")
    for pair in raw.split(","):
        if ":" in pair:
            k, _, v = pair.partition(":")
            try:
                defaults[k.strip()] = float(v)
            except ValueError:
                pass
    return defaults


MARKET_PREMIUM = _parse_market_premium()


def _parse_market_solid():
    """Per-market ✅ Solid MINIMUM bar (below this, even if you pass the
    entry MARKET_MIN_CONF gate → you are NOT picked at all).

    Intuition: the entry gate was just 'not obviously wrong' but in practice
    the whole big grey zone between gate and Solid bar drags portfolio win
    rates.  Only Premium (conf >= MARKET_PREMIUM) OR the top-2pp just below
    Premium qualify as Solid; everything between gate and Solid bar is
    rejected → 'Solid only in a few matches'.

    Markets where MARKET_PREMIUM (effective) <= MARKET_MIN_CONF have no
    Solid band at all -- every qualifying pick IS Premium, so Solid bar is
    set equal to Premium (the zone between the two is empty).

    Override with env MARKET_SOLID="btts:0.78,away_sc:0.81"
    """
    all_markets = set(MARKET_MIN_CONF.keys()) | set(MARKET_PREMIUM.keys())
    defaults = {}
    for mkt in all_markets:
        prem_eff = MARKET_PREMIUM.get(mkt, PREMIUM_TIER)  # same effective bar as build_pick
        gate = MARKET_MIN_CONF.get(mkt, 0.0)
        # Solid bar defaults to max(gate, prem_eff - 0.02): narrow 2pp band
        # just below Premium.  If prem_eff <= gate (no grey zone exists for
        # this market) then Solid bar == prem_eff, meaning no Solid picks
        # are ever produced for that market.
        defaults[mkt] = max(gate, round(prem_eff - 0.02, 3))
    raw = os.getenv("MARKET_SOLID", "")
    for pair in raw.split(","):
        if ":" in pair:
            k, _, v = pair.partition(":")
            try:
                defaults[k.strip()] = float(v)
            except ValueError:
                pass
    return defaults


MARKET_SOLID = _parse_market_solid()

# Bump this string whenever rules.py logic, check sets, gates, premium tiers,
# or the confidence formula change. It is mixed into the predict_day cache
# signature so stale picks computed under older rules are never served.
RULES_VERSION = os.getenv("OU_RULES_VERSION", "2026-10-10.17-home-dc-restored")

# -----------------------------------------------------------------------------
# Supported + default-publish markets.
#
# ALL_MARKETS: every market the engine can compute for (used in settle/stats
#   to report on historical picks even if no longer published going forward).
# DEFAULT_PUBLISH_MARKETS: subset shipped to Telegram free/VIP chats by the
#   default `predict`/`report` CLI invocations and by the GHA publish job.
#   ORDER = presentation order in the VIP report.
#
# Real settled track record (2026-10-03, 742 settled picks) drives the cut:
#   home_sc   240 picks  87.9%  profit +50.70   << KEEP
#   away_sc   254 picks  84.6%  profit +42.30   << KEEP
#   over       68 picks  73.5%  profit  +8.10   << KEEP
#   btts       83 picks  67.5%  profit  +6.00   << KEEP
#   over15     10 picks  100%   profit  +2.00   << KEEP (small N, perfect)
#   home_dw    10 picks  90.0%  profit  +1.70   << KEEP (small N, perfect)
#   home       41 picks  63.4%  profit  +2.70   << KEEP
#   under35    12 picks  75.0%  profit  +1.50   << KEEP (rewritten rules)
#   no_btts    10 picks  70.0%  profit  +0.40   << CUT (no ROI; opt-in)
#   under      14 picks  42.9%  profit  +0.10   << CUT (below 50%; opt-in)
#
# User can ALWAYS restore any cut market by passing --markets on the CLI or
# overriding the markets= string in GHA workflow_dispatch. The cut simply
# removes them from the default publish list.
ALL_MARKETS = ("over", "over15", "under", "under35",
               "btts", "no_btts",
               "home", "home_dw", "home_sc", "away_sc")
DEFAULT_PUBLISH_MARKETS = ("over", "over15", "btts",
                           "home", "home_dw", "home_sc", "away_sc")

# --- international tournament caution (2026-10: national-team / UEFA club
# tournaments showed materially worse hit-rates on total-goals markets) ---
#
# Settled performance split (2026-10):
#   International (Nations League + Europa League, 77 picks):
#       btts  2/7  = 28.6%   (DISASTER)
#       over  2/5  = 40.0%   (LOSER)
#       vs domestic equivalents at 61-72%
#
#   Under35 was 66.7% domestic (33 picks) vs under 42.9% -- both cut from
#   defaults per user request ("Un35 and Un25 not working, caution needed").
#
# Any league name that matches a keyword below is classified as an
# "international tournament".  On those fixtures, markets in
# INTERNATIONAL_SKIP_MARKETS are SKIPPED ENTIRELY (no pick emitted).
# All other markets on such fixtures get a league_caution tag auto-added
# (even if the manual LEAGUE_BLOCK is empty and health data is not yet
# mature for that league) so the user is warned before staking.
INTERNATIONAL_TOURNAMENT_KEYWORDS = (
    # UEFA Nations League (national teams) -- NOT "National League" (ENG 5th tier)
    # Test: "nations league" in name AND "national league" not in name
    ("CASE:Nations League", lambda name:
        "nations league" in name.casefold()
        and "national league" not in name.casefold()),
    # Any provider that prefixes internationals with "INTERNATIONAL - "
    ("PREFIX:INTERNATIONAL", lambda name: name.casefold().startswith("international")),
    # UEFA club continental competitions (Europa League overall: 6 picks 33.3% W)
    "Europa League",
    "Europa Conference",
    "Champions League",
    "Conference League",
    # FIFA / CAF / CONMEBOL / CONCACAF / AFC global continental tournaments
    "World Cup",
    "Copa America",
    "African Cup",
    "AFCON",
    "Gold Cup",
    "Asian Cup",
    "Euro Qualifier",
    "World Cup Qualifier",
    "Friendly",
    "Qualifier",
)


def _parse_international_keywords():
    """Allow user to override INTERNATIONAL_TOURNAMENT_KEYWORDS via env.

    OU_INTERNATIONAL_KEYWORDS=keyword1,keyword2,...
    Blank entry falls back to the hardcoded list above.
    Use OU_INTERNATIONAL_KEYWORDS=__NONE__ to disable the whole system.
    """
    raw = os.getenv("OU_INTERNATIONAL_KEYWORDS", "").strip()
    if raw == "__NONE__":
        return None
    if not raw:
        return INTERNATIONAL_TOURNAMENT_KEYWORDS
    return tuple(k.strip() for k in raw.split(",") if k.strip())


def is_international_tournament(league_name):
    """Return True if `league_name` matches any INTERNATIONAL_TOURNAMENT_KEYWORDS
    entry.  Callable (lambda) entries are invoked with the casefolded name;
    string entries are substring-matched (case-insensitive) against the raw name.
    """
    if not league_name:
        return False
    kws = _parse_international_keywords()
    if kws is None:
        return False
    cf = league_name.casefold()
    for entry in kws:
        if callable(entry):
            if entry(league_name):
                return True
        elif isinstance(entry, tuple) and len(entry) == 2 and callable(entry[1]):
            if entry[1](league_name):
                return True
        elif isinstance(entry, str):
            if entry.casefold() in cf:
                return True
    return False


# On fixtures classified as international tournaments, EVERY pick (all markets)
# gets a league_caution warning about poor ROI, regardless of gates passed.
# The user explicitly rejected "hard skip" on 2026-10-06:
#   > dont skip picks just caution this league has poor roi
#
# Set env OU_INTERNATIONAL_SKIP to a comma-list to RE-ENABLE hard-skip for
# specific markets if you want (default: empty frozenset = caution only).
# Use OU_INTERNATIONAL_SKIP=__ALL__ to skip all markets on internationals.
def _parse_international_skip_markets():
    raw = os.getenv("OU_INTERNATIONAL_SKIP", "").strip()
    if raw == "__ALL__":
        return frozenset(ALL_MARKETS)
    if raw == "__NONE__" or not raw:
        return frozenset()
    return frozenset(m.strip() for m in raw.split(",") if m.strip())


INTERNATIONAL_SKIP_MARKETS = _parse_international_skip_markets()
DEFAULT_ODDS = float(os.getenv("DEFAULT_ODDS", "2.0"))    # decimal odds for EV
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.35"))
MAX_STAKE_PCT = float(os.getenv("MAX_STAKE_PCT", "0.3"))  # % of bankroll per pick

# league-average goals (used to normalize attack/defence strengths)
LEAGUE_AVG_HOME_GOALS = float(os.getenv("LEAGUE_AVG_HOME_GOALS", "1.45"))
LEAGUE_AVG_AWAY_GOALS = float(os.getenv("LEAGUE_AVG_AWAY_GOALS", "1.15"))

# --- statarea cross-check ---------------------------------------------------
ST_OVER_MIN = int(os.getenv("ST_OVER_MIN", "70"))    # statarea Over 2.5 % we trust
ST_UNDER_MAX = int(os.getenv("ST_UNDER_MAX", "40"))  # below -> treat as Under
ST_HOME_MIN = int(os.getenv("ST_HOME_MIN", "55"))    # statarea home-win % we trust
ST_BTTS_MIN = int(os.getenv("ST_BTTS_MIN", "55"))    # statarea BTTS % we trust
ST_MIN_MATCHES = int(os.getenv("ST_MIN_MATCHES", "30"))  # sanity gate for parse
FUZZY_MIN = float(os.getenv("FUZZY_MIN", "0.78"))

STATAREA_URL = "https://www.statarea.com/predictions"
JINA_PROXY = "https://r.jina.ai/https://www.statarea.com/predictions"
CACHE_DIR = os.getenv("OU_CACHE_DIR", os.path.expanduser("~/.cache/overunder"))

# --- cache tuning (for reruns, backfill, batch runs) --------------------------
# HTML TTLs (hours).  Team history pages barely change mid-season and are
# expensive to re-parse, so they get a long TTL.  Fixture/date pages include
# live score updates which move during a game day, so shorter TTL by default.
# Cross-check (statarea) card TTL kept independent in load_card(12h default).
HTML_TTL_TEAM_HOURS   = int(os.getenv("OU_HTML_TTL_TEAM",  "72"))
HTML_TTL_FIXTURE_HOURS = int(os.getenv("OU_HTML_TTL_FIXTURE", "6"))
# On-disk provider team_matches parse+merge cache TTL (hours). This sits ON TOP
# of the HTML cache: even when HTML is fresh, it avoids re-running merge_history
# and the parse_rows transform across process restarts.
TEAM_CACHE_TTL_HOURS  = int(os.getenv("OU_TEAM_CACHE_TTL", "168"))   # 7 days
# predict_day() on-disk memoization: if same fixtures+markets used on rerun,
# return cached picks instantly (TTL matches fixture TTL by default).
PREDICT_CACHE_TTL_HOURS = int(os.getenv("OU_PREDICT_CACHE_TTL", str(HTML_TTL_FIXTURE_HOURS)))
# Disable caches entirely: set OU_CACHE_DISABLE=1 (settlement/verify/live need fresh)
CACHE_DISABLE = bool(os.getenv("OU_CACHE_DISABLE", ""))
# HTTP read timeout (seconds) and total retries for soccerbase/statarea fetches.
# Settlement days (weekend heavy traffic) can exceed the default 30s read timeout.
HTTP_TIMEOUT_SEC = int(os.getenv("OU_HTTP_TIMEOUT", "60"))
HTTP_MAX_RETRIES = int(os.getenv("OU_HTTP_RETRIES", "4"))

# --- storage ----------------------------------------------------------------
DATA_DIR = os.getenv("OU_DATA_DIR", os.path.join(os.getcwd(), "data"))
HISTORY_FILE = os.path.join(DATA_DIR, "prediction_history.json")

# --- league health (caution on leagues where our patterns keep losing) --------
# User workflow (2026-10):
#   > "i do back tests for 60 days to find messy leagues and be cautious on
#     each market ... calculate loses deviating from our picks and say they
#     don't go with us well."
#
# A (league, market) pair is flagged CAUTION when all:
#   1. It has >= LEAGUE_HEALTH_MIN_PICKS settled picks in the trailing window
#   2. EITHER:
#      a. profit < 0                               (money loser)
#      b. win_pct <= baseline_win_pct - LEAGUE_HEALTH_DEV_PCT
#                                                (win-rate deviates badly vs
#                                                 what our model targets for
#                                                 that market -> poor fit)
#      c. win_pct <= LEAGUE_HEALTH_FLOOR_PCT     (absolute floor, any pair
#                                                 below is a long-term loser)
#   AND league is NOT in OU_LEAGUE_ALLOW.
# Cautioned picks are TAGGED, never skipped -- and never applied in backtests
# (that would be lookahead bias).
LEAGUE_HEALTH_WINDOW_DAYS = int(os.getenv("OU_LEAGUE_WINDOW_DAYS", "60"))
LEAGUE_HEALTH_MIN_PICKS   = int(os.getenv("OU_LEAGUE_MIN_PICKS",  "5"))
# Deviation gate: if a league/market runs this many pp *below* its expected
# baseline win-rate, it is flagged as "doesn't go with our picks well".
# Default 20pp.  Example: home_sc baseline=85% -> any league/home_sc <= 65%
# win-rate is flagged as caution regardless of profit accounting.
LEAGUE_HEALTH_DEV_PCT     = float(os.getenv("OU_LEAGUE_DEV_PCT",  "20"))
# Absolute floor.  Any league/market pair win% below this is ALWAYS flagged
# (default 55%: anything below is a long-term loser at typical 1.90/2.00 odds).
LEAGUE_HEALTH_FLOOR_PCT   = float(os.getenv("OU_LEAGUE_FLOOR_PCT","55"))

# Expected baseline win-rates per market -- what our solid gates target.
# Used ONLY for 60-day backtest "deviation from our picks" benchmarking.
# Settled all-time averages (good leagues):
#   home_sc 85, away_sc 83, home_dw 88, over15 90, over 72, btts 65, home 62.
# under/no_btts baselines included for when user opts back into those markets.
def _parse_market_baseline_win_pct():
    raw = os.getenv("MARKET_BASELINE_WIN_PCT", "").strip()
    base = {
        "home_sc":   85.0,
        "away_sc":   83.0,
        "home_dw":   88.0,
        "over15":    90.0,
        "over":      72.0,
        "btts":      65.0,
        "home":      62.0,
        "under35":   72.0,
        "under":     55.0,
        "no_btts":   62.0,
    }
    if raw:
        for part in raw.split(","):
            if ":" not in part:
                continue
            m, v = part.split(":", 1)
            m = m.strip().lower()
            try:
                base[m] = float(v.strip().rstrip("%"))
            except ValueError:
                continue
    return base

MARKET_BASELINE_WIN_PCT = _parse_market_baseline_win_pct()


def _csv_set(name):
    return {x.strip() for x in os.getenv(name, "").split(",") if x.strip()}


LEAGUE_BLOCK = _csv_set("OU_LEAGUE_BLOCK")   # always caution, all markets
LEAGUE_ALLOW = _csv_set("OU_LEAGUE_ALLOW")   # never auto-caution
LEAGUE_AVOID_DISABLE = bool(os.getenv("OU_LEAGUE_AVOID_DISABLE", ""))

# --- telegram (optional) -----------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_VIP_CHAT_ID = os.getenv("TELEGRAM_VIP_CHAT_ID", "")
