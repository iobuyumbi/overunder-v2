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
PREMIUM_TIER = float(os.getenv("PREMIUM_TIER", "0.85"))   # >= -> 🔥 Premium
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

# --- storage ----------------------------------------------------------------
DATA_DIR = os.getenv("OU_DATA_DIR", os.path.join(os.getcwd(), "data"))
HISTORY_FILE = os.path.join(DATA_DIR, "prediction_history.json")

# --- telegram (optional) -----------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_VIP_CHAT_ID = os.getenv("TELEGRAM_VIP_CHAT_ID", "")
