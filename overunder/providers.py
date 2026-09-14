"""Data providers.

DemoProvider       -- fully offline, seeded synthetic stats + bundled fixtures/results.
SoccerbaseProvider -- real soccerbase.com adapter. Parsing targets verified
                      against the site's page structure (results.sd?date= row
                      tables, team.sd?team_id= pages, /search.sd lookup);
                      raw-HTML robustness varies with their markup -- run
                      `python -m overunder scrape-check --date YYYY-MM-DD`
                      after install to confirm it works from your machine, and
                      see CACHE_DIR for saved raw pages when it doesn't.

Provider interface:
    fixtures(day=None)  -> [{"date","league","home","away"}]
    team_matches(team)  -> [{"venue":"H"/"A","gf":int,"ga":int,"date":str}]
    results(day=None)   -> [{"home","away","hg","ag"}]
"""

import json
import os
import random
import re
import time

import requests

from .config import CACHE_DIR, DATA_DIR
from .teams import normalize

HISTORY_DB = os.path.join(DATA_DIR, "history_db.json")


def load_history_db():
    if os.path.exists(HISTORY_DB):
        with open(HISTORY_DB, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history_db(db):
    os.makedirs(os.path.dirname(HISTORY_DB), exist_ok=True)
    with open(HISTORY_DB, "w", encoding="utf-8") as f:
        json.dump(db, f)


def db_add_match(db, team, venue, gf, ga, date, opp=""):
    """Append one match to a team's history; returns True if actually added.
    Dedupes on (date, venue, gf, ga) so re-backfilling after adding the opp
    field does not duplicate old records."""
    k = normalize(team)
    key = (date, venue, int(gf), int(ga))
    lst = db.setdefault(k, [])
    for e in lst:
        if (e.get("date"), e["venue"], e["gf"], e["ga"]) == key:
            if opp and not e.get("opp"):
                e["opp"] = opp
            return False
    lst.append({"venue": venue, "gf": int(gf), "ga": int(ga), "date": date, "opp": opp})
    return True


def merge_history(page_matches, team, db=None, before=None):
    """Merge soccerbase page history with the backfilled local DB (deduped, date-sorted).
    If `before` (ISO date) is given, drop anything on/after that date -- this is
    the no-lookahead guarantee that makes backtests honest."""
    if db is None:
        db = load_history_db()
    combined = list(page_matches) + list(db.get(normalize(team), []))
    seen, out = set(), []
    for m in combined:
        d = m.get("date", "")
        if before is not None and (not d or d >= before):
            continue
        key = (d, m["venue"], m["gf"], m["ga"])
        if key not in seen:
            seen.add(key)
            out.append(m)
    out.sort(key=lambda m: m.get("date", ""))
    return out

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DIR = os.path.join(PACKAGE_DIR, "sample_data")


class DemoProvider:
    """Deterministic offline provider so the whole system runs end-to-end
    without network: predict -> cross-check -> settle -> stats -> report."""

    DEMO_FIXTURES = [
        {"date": "2026-09-12", "league": "Swiss Super League",        "home": "St Gallen",        "away": "FC Sion"},
        {"date": "2026-09-12", "league": "Football League Championship", "home": "Southampton",   "away": "Bristol City"},
        {"date": "2026-09-12", "league": "Spanish La Liga",           "home": "Real Madrid",      "away": "Rayo Vallecano"},
        {"date": "2026-09-12", "league": "National League",           "home": "Harrogate Town",   "away": "Tamworth"},
        {"date": "2026-09-12", "league": "Football League One",       "home": "Mansfield",        "away": "Huddersfield"},
        {"date": "2026-09-12", "league": "Football League One",       "home": "Blackpool",        "away": "Bromley"},
        {"date": "2026-09-12", "league": "Italian Serie A",           "home": "Genoa",            "away": "Frosinone"},
        {"date": "2026-09-12", "league": "Polish Ekstraklasa",        "home": "Gornik Zabrze",    "away": "Lech Poznan"},
        {"date": "2026-09-12", "league": "Norwegian Eliteserien",     "home": "Lillestrom",       "away": "Valerenga"},
        {"date": "2026-09-12", "league": "Scottish League Two",       "home": "Clyde",            "away": "Kelty Hearts"},
        {"date": "2026-09-12", "league": "Football League Two",       "home": "Barnet",           "away": "Accrington"},
        {"date": "2026-09-12", "league": "National League",           "home": "Yeovil Town",      "away": "AFC Fylde"},
    ]

    ATTACK = {
        "st gallen": 1.6, "fc sion": 1.3, "southampton": 1.5, "bristol city": 1.3,
        "real madrid": 1.7, "rayo vallecano": 1.2, "harrogate town": 1.4, "tamworth": 0.9,
        "mansfield": 1.0, "huddersfield": 1.3, "blackpool": 1.5, "bromley": 1.1,
        "genoa": 1.1, "frosinone": 0.9, "gornik zabrze": 1.5, "lech poznan": 1.3,
        "lillestrom": 1.6, "valerenga": 1.4, "clyde": 1.2, "kelty hearts": 1.0,
        "barnet": 1.4, "accrington st": 1.1, "yeovil town": 1.3, "afc fylde": 1.2,
    }

    DEMO_RESULTS = [
        {"home": "St Gallen",      "away": "FC Sion",         "hg": 3, "ag": 1},
        {"home": "Southampton",    "away": "Bristol City",    "hg": 2, "ag": 1},
        {"home": "Real Madrid",    "away": "Rayo Vallecano",  "hg": 4, "ag": 0},
        {"home": "Harrogate Town", "away": "Tamworth",        "hg": 1, "ag": 1},
        {"home": "Mansfield",      "away": "Huddersfield",    "hg": 0, "ag": 2},
        {"home": "Blackpool",      "away": "Bromley",         "hg": 2, "ag": 2},
        {"home": "Genoa",          "away": "Frosinone",       "hg": 1, "ag": 0},
        {"home": "Gornik Zabrze",  "away": "Lech Poznan",     "hg": 2, "ag": 1},
        {"home": "Lillestrom",     "away": "Valerenga",       "hg": 3, "ag": 2},
        {"home": "Clyde",          "away": "Kelty Hearts",    "hg": 1, "ag": 0},
        {"home": "Barnet",         "away": "Accrington",      "hg": 2, "ag": 0},
        {"home": "Yeovil Town",    "away": "AFC Fylde",       "hg": 2, "ag": 3},
    ]

    def __init__(self, seed=7):
        self._histories = {}

    def _pois(self, rng, lam):
        L, k, p = pow(2.718281828, -lam), 0, 1.0
        while True:
            k += 1
            p *= rng.random()
            if p <= L:
                return k - 1

    def team_matches(self, team, limit=12, before=None):
        key = normalize(team)
        if key not in self._histories:
            rng = random.Random(key)  # stable across processes (str seed)
            atk = self.ATTACK.get(key, 1.2)
            hist = []
            for i in range(12):
                venue = "H" if i % 2 == 0 else "A"
                lam_for = atk * (1.25 if venue == "H" else 1.0)
                lam_agn = 1.25 if venue == "H" else 1.45
                hist.append({"venue": venue,
                             "gf": self._pois(rng, lam_for),
                             "ga": self._pois(rng, lam_agn),
                             "date": f"2026-08-{20 + (i % 23):02d}"})
            self._histories[key] = hist
        out = self._histories[key]
        if before is not None:
            out = [m for m in out if m.get("date", "") and m["date"] < before] or self._histories[key]
        return out[-limit:] if limit else out

    def fixtures(self, day=None):
        fs = self.DEMO_FIXTURES
        return [f for f in fs if day is None or f["date"] == day]

    def results(self, day=None):
        return list(self.DEMO_RESULTS)


class SoccerbaseProvider:
    """Live soccerbase.com scraper.

    Pages used:
      results.sd?date=YYYY-MM-DD   one day: played matches (scores) AND upcoming
                                   fixtures (no score) across all leagues
      team.sd?team_id=N&teamTabs=results   team history (last N scored matches)
      search.sd?searchtype=team&searchterm=X   name -> team_id resolution

    Every parsed page contributes team_id mappings to a persistent cache
    (~/.cache/overunder/team_ids.json) so lookups get cheaper over time.
    """

    BASE = "https://www.soccerbase.com"
    RE_TEAM_LINK = re.compile(r'/teams/team\.sd\?team_id=(\d+)[^"]*"[^>]*>\s*([^<]+?)\s*</a>')
    RE_COMP = re.compile(r'/tournaments/tournament\.sd\?comp_id=\d+[^"]*"[^>]*>\s*([^<]+?)\s*</a>')
    RE_DATE = re.compile(r'results\.sd\?date=(\d{4}-\d{2}-\d{2})')
    RE_SCORE = re.compile(r'>\s*(\d{1,2})\s*-\s*(\d{1,2})\s*<')
    # fallback: score as bare text (handles &nbsp;, spans, extra classes).
    # boundaries reject date fragments like 2026-09-14 ("26-09" sits between digits)
    RE_SCORE_LOOSE = re.compile(r'(?<![\d/-])(\d{1,2})\s*-\s*(\d{1,2})(?![\d/-])')
    RE_FIXTURE_V = re.compile(r'>\s*v\s*<', re.I)

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/126.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._ids_path = os.path.join(CACHE_DIR, "team_ids.json")
        self._ids = {}
        if os.path.exists(self._ids_path):
            with open(self._ids_path, encoding="utf-8") as f:
                self._ids = json.load(f)

    # -- fetch plumbing ------------------------------------------------------
    def _get(self, url, cache_name, fresh=False):
        """fresh=True bypasses the read cache (settlement/verify need live
        scores; backfill/backtest want the cache). Responses are still
        written to cache for other callers."""
        import sys as _sys
        path = os.path.join(CACHE_DIR, cache_name)
        cached = (not fresh) and os.path.exists(path) \
                 and time.time() - os.path.getmtime(path) < 6 * 3600
        if not cached:
            print(f"[soccerbase] fetching {url}", file=_sys.stderr, flush=True)
        if cached:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        last_err = None
        for attempt in range(3):
            try:
                req_url = url
                if fresh:
                    # defeat soccerbase's server-side page cache: the CDN keys
                    # on the full URL, so a changing dummy param forces a
                    # fresh render with the latest posted scores
                    sep = "&" if "?" in url else "?"
                    req_url = f"{url}{sep}_cb={int(time.time())}"
                r = self._session.get(req_url, timeout=30)
                print(f"[soccerbase]   -> HTTP {r.status_code}, {len(r.text)} bytes",
                      file=_sys.stderr, flush=True)
                if r.ok and len(r.text) > 1000:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(r.text)
                    return r.text
                last_err = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                last_err = str(e)
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"fetch failed for {url}: {last_err} "
                           f"(saved pages live in {CACHE_DIR})")

    def _save_ids(self):
        with open(self._ids_path, "w", encoding="utf-8") as f:
            json.dump(self._ids, f, indent=1)

    # -- parsing ---------------------------------------------------------------
    def _parse_rows(self, html):
        """Row-wise parse of any soccerbase results/fixtures table.
        Returns [{"date","league","home","away","home_id","away_id","hg","ag"}]
        with hg/ag None for unplayed fixtures."""
        rows = []
        current_comp = None
        for row in re.split(r"<tr[^>]*>", html):
            comp_m = self.RE_COMP.search(row)
            teams = self.RE_TEAM_LINK.findall(row)
            if len(teams) >= 2:
                if comp_m:
                    current_comp = comp_m.group(1).strip()
                (hid, home), (aid, away) = teams[0], teams[1]
                self._ids.setdefault(normalize(home), hid)
                self._ids.setdefault(normalize(away), aid)
                date_m = self.RE_DATE.search(row)
                row_n = row.replace("&nbsp;", " ").replace("&#8211;", "-") \
                           .replace("&ndash;", "-").replace("&#8212;", "-")
                score_m = self.RE_SCORE.search(row_n)
                if not score_m:
                    # day pages put the score BETWEEN the two team links, team
                    # pages after them -- so scan the whole row as plain text.
                    # The lookarounds reject date fragments (2026-09-13).
                    txt = re.sub(r"<[^>]+>", " ", row_n)
                    score_m = self.RE_SCORE_LOOSE.search(txt)
                rows.append({
                    "date": date_m.group(1) if date_m else None,
                    "league": current_comp or "",
                    "home": home.strip(), "away": away.strip(),
                    "home_id": hid, "away_id": aid,
                    "hg": int(score_m.group(1)) if score_m else None,
                    "ag": int(score_m.group(2)) if score_m else None,
                })
            elif comp_m and not teams:
                current_comp = comp_m.group(1).strip()
            elif not teams and "colspan" in row:
                txt = re.sub(r"<[^>]+>", "", row).strip()
                if len(txt) >= 5 and not self.RE_SCORE_LOOSE.search(txt):
                    current_comp = txt
        if self._ids:
            self._save_ids()
        return rows

    # -- team id resolution ------------------------------------------------------
    def _resolve_team_id(self, team):
        key = normalize(team)
        if key in self._ids:
            return self._ids[key]
        q = re.sub(r"[^a-z0-9 ]", " ", team.lower()).strip()
        html = self._get(f"{self.BASE}/search.sd?searchtype=team&searchterm="
                         f"{requests.utils.quote(q)}", f"search_{key}.html")
        m = self.RE_TEAM_LINK.search(html)
        if m:
            self._ids[key] = m.group(1)
            self._save_ids()
            return m.group(1)
        raise RuntimeError(
            f"could not resolve soccerbase team_id for '{team}'. "
            f"Find it on soccerbase (team page URL has team_id=NNNN) and add "
            f'"{key}": "<id>" to {self._ids_path}')

    def debug_team(self, team):
        """Return (parsed_rows, score_like_snippets) for diagnosing parse issues."""
        tid = self._resolve_team_id(team)
        html = self._get(f"{self.BASE}/teams/team.sd?team_id={tid}&teamTabs=results",
                         f"sb_team_{tid}.html")
        rows = self._parse_rows(html)
        snippets = []
        for m in self.RE_SCORE_LOOSE.finditer(html.replace("&nbsp;", " ")):
            s = max(0, m.start() - 50)
            snippets.append(html[s: m.end() + 30].replace("\n", " "))
            if len(snippets) >= 5:
                break
        return rows, snippets

    # -- provider interface ------------------------------------------------------
    def fixtures(self, day=None):
        day = day or time.strftime("%Y-%m-%d")
        html = self._get(f"{self.BASE}/matches/results.sd?date={day}",
                         f"sb_date_{day}.html")
        rows = self._parse_rows(html)
        fx = [{"date": r["date"] or day, "league": r["league"],
               "home": r["home"], "away": r["away"]}
              for r in rows if r["hg"] is None]
        import sys as _sys
        print(f"[soccerbase] {day}: {len(fx)} fixtures, {len(rows)-len(fx)} results",
              file=_sys.stderr, flush=True)
        if not fx:
            raise RuntimeError(
                f"no fixtures parsed for {day} -- soccerbase markup may have "
                f"changed. Inspect {CACHE_DIR}/sb_date_{day}.html and adjust "
                f"the RE_* patterns at the top of SoccerbaseProvider.")
        return fx

    def team_matches(self, team, limit=12, before=None):
        key = normalize(team)
        if before is not None:
            key = key + "|" + before          # cache is point-in-time aware
        if not hasattr(self, "_team_cache"):
            self._team_cache = {}
        if key in self._team_cache:
            return self._team_cache[key]
        result = self._team_matches_impl(team, limit, before=before)
        self._team_cache[key] = result
        return result

    def _team_matches_impl(self, team, limit=12, before=None):
        tid = self._resolve_team_id(team)
        html = self._get(f"{self.BASE}/teams/team.sd?team_id={tid}&teamTabs=results",
                         f"sb_team_{tid}.html")
        rows = [r for r in self._parse_rows(html) if r["hg"] is not None]
        import sys as _sys
        print(f"[soccerbase] team {team}: {len(rows)} scored matches",
              file=_sys.stderr, flush=True)
        out = []
        for r in rows:
            venue = "H" if normalize(r["home"]) == normalize(team) else "A"
            gf, ga = (r["hg"], r["ag"]) if venue == "H" else (r["ag"], r["hg"])
            out.append({"venue": venue, "gf": gf, "ga": ga, "date": r["date"] or "",
                        "opp": r["away"] if venue == "H" else r["home"]})
        self._team_cache = getattr(self, "_team_cache", {})
        merged = merge_history(out, team, before=before)
        return merged[-limit:]

    def day_rows(self, day):
        """All parsed rows for one day page: played matches carry hg/ag,
        upcoming fixtures have hg=None. Used by backtest and settlement.
        Honors self.fresh (set by settle/verify for live scores)."""
        html = self._get(f"{self.BASE}/matches/results.sd?date={day}",
                         f"sb_date_{day}.html",
                         fresh=getattr(self, "fresh", False))
        return self._parse_rows(html)

    def results(self, day=None):
        rows = self.day_rows(day or time.strftime("%Y-%m-%d"))
        return [{"home": r["home"], "away": r["away"],
                 "hg": r["hg"], "ag": r["ag"]}
                for r in rows if r["hg"] is not None]
