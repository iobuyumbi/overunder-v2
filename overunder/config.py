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

       Override with env, e.g. (4/6 relaxed, 5/6 medium, 6/6 strict):
         OU_FREQ="scored:4:2,conceded:4:2,over:4:2,blank:4:2,win:3:2,cs:5:3,
                   btts_game:3:2,nowin:4:2"                                 -- relaxed (default)
         OU_FREQ="scored:5:3,conceded:5:3,over:4:2,blank:4:2,win:3:2,cs:5:3,
                   btts_game:3:2,nowin:4:2"                                 -- medium
         OU_FREQ="scored:6:3,conceded:6:3,over:4:2,blank:4:2,win:3:2,cs:5:3,
                   btts_game:3:2,nowin:4:2"                                 -- strict (fewest picks)
       scored:4:2 means "scored in 4+/6 matches, fallback 2+/3 when <6 exist".
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
RULES_VERSION = os.getenv("OU_RULES_VERSION", "2026-10-01.1-scored-4of6")
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
# Trailing window + minimum sample before a (league, market) pair gets a
# CAUTION tag. Cautioned picks are TAGGED, never skipped -- and never applied
# in backtests (that would be lookahead).
LEAGUE_HEALTH_WINDOW_DAYS = int(os.getenv("OU_LEAGUE_WINDOW_DAYS", "30"))
LEAGUE_HEALTH_MIN_PICKS = int(os.getenv("OU_LEAGUE_MIN_PICKS", "6"))


def _csv_set(name):
    return {x.strip() for x in os.getenv(name, "").split(",") if x.strip()}


LEAGUE_BLOCK = _csv_set("OU_LEAGUE_BLOCK")   # always caution, all markets
LEAGUE_ALLOW = _csv_set("OU_LEAGUE_ALLOW")   # never auto-caution
LEAGUE_AVOID_DISABLE = bool(os.getenv("OU_LEAGUE_AVOID_DISABLE", ""))

# --- telegram (optional) -----------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_VIP_CHAT_ID = os.getenv("TELEGRAM_VIP_CHAT_ID", "")
