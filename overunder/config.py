"""Central configuration. Override any value via environment variable of the same
name (see .env.example) or by editing here."""

import os


def _load_dotenv():
    """Load KEY=VALUE pairs from a local .env (cwd, then package root).
    Real environment variables always win. .env is gitignored -- never commit it."""
    for base in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        path = os.path.join(base, ".env")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
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

       Categories (used to tune each class of evidence independently):
         scored   -- team actually scored a goal (attack evidence)
         conceded -- team conceded a goal (defence-leakage evidence)
         over     -- over-X-line pattern (e.g. over 2.5, under 2.5)
         blank    -- team blanked / failed to score (no_btts, under)
         win      -- outright wins (home dominance)
         cs       -- clean sheet / conceded zero (no_btts defence)

       Override with env, e.g.
         OU_FREQ="scored:6:3,conceded:4:2,over:4:2,blank:4:2,win:3:2,cs:5:3"
       scored:6:3 means "scored in 6+/6 matches, fallback 3+/3".
    """
    defaults = {
        "scored":   {"full": 6, "short": 3},
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
    """Per-market 🔥 Premium thresholds. Premium should mean 'top pick within
    THIS market', so markets with a lower entry gate (btts 0.75, away_sc 0.80)
    get their own premium bar instead of the global 0.85 -- otherwise every
    btts pick between its gate and 0.85 can never be Premium while over/
    home_sc picks are Premium by construction.
    Override with env, e.g. MARKET_PREMIUM="btts:0.82,away_sc:0.84" """
    defaults = {"btts": 0.80, "away_sc": 0.83}
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

# Bump this string whenever rules.py logic, check sets, gates, premium tiers,
# or the confidence formula change. It is mixed into the predict_day cache
# signature so stale picks computed under older rules are never served.
RULES_VERSION = os.getenv("OU_RULES_VERSION", "2026-09-24.1")
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
