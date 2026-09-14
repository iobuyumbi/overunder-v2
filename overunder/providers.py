"""Data providers.

DemoProvider  — fully offline, seeded synthetic stats + bundled fixtures/results.
SoccerbaseProvider — real scraping adapter (skeleton): robust fetch+cache+retry is
                     implemented; the page-specific parsing is the part you must
                     maintain as soccerbase changes. The engine below only ever
                     talks to the provider interface, so swapping is one line.

Provider interface:
    fixtures(day=None)            -> [{"date","league","home","away"}]
    team_matches(team)            -> [{"venue":"H"/"A","gf":int,"ga":int,"date":str}]
    results(day=None)             -> [{"home","away","hg","ag"}]  (settlement)
"""

import json
import os
import random
import time

import requests

from .config import CACHE_DIR

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

    # attack strength per team (goals-for rate multiplier) — hand-set so the
    # demo produces a realistic mix of premium/solid/weak picks
    ATTACK = {
        "st gallen": 1.6, "fc sion": 1.3, "southampton": 1.5, "bristol city": 1.3,
        "real madrid": 1.7, "rayo vallecano": 1.2, "harrogate town": 1.4, "tamworth": 0.9,
        "mansfield": 1.0, "huddersfield": 1.3, "blackpool": 1.5, "bromley": 1.1,
        "genoa": 1.1, "frosinone": 0.9, "gornik zabrze": 1.5, "lech poznan": 1.3,
        "lillestrom": 1.6, "valerenga": 1.4, "clyde": 1.2, "kelty hearts": 1.0,
        "barnet": 1.4, "accrington st": 1.1, "yeovil town": 1.3, "afc fylde": 1.2,
    }

    # demo results for the full-cycle settle step
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
        # Knuth sampler
        L, k, p = pow(2.718281828, -lam), 0, 1.0
        while True:
            k += 1
            p *= rng.random()
            if p <= L:
                return k - 1

    def team_matches(self, team):
        from .teams import normalize
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
        return self._histories[key]

    def fixtures(self, day=None):
        fs = self.DEMO_FIXTURES
        return [f for f in fs if day is None or f["date"] == day]

    def results(self, day=None):
        return list(self.DEMO_RESULTS)


class SoccerbaseProvider:
    """Real-data adapter. Robustness plumbing (retry/backoff/cache) is done;
    fill in _parse_* when soccerbase's markup changes."""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/126.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        os.makedirs(CACHE_DIR, exist_ok=True)

    def _get(self, url, cache_name):
        path = os.path.join(CACHE_DIR, cache_name)
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < 6 * 3600:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        last_err = None
        for attempt in range(3):
            try:
                r = self._session.get(url, timeout=30)
                if r.ok and len(r.text) > 1000:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(r.text)
                    return r.text
                last_err = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                last_err = str(e)
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"fetch failed for {url}: {last_err}")

    # -- TODO: implement against live soccerbase markup -----------------------
    def fixtures(self, day=None):
        raise NotImplementedError(
            "SoccerbaseProvider.fixtures: implement _parse_fixtures using self._get(). "
            "Until then, run with --demo or wire your existing scraper here.")

    def team_matches(self, team):
        raise NotImplementedError("SoccerbaseProvider.team_matches: implement team page parse.")

    def results(self, day=None):
        raise NotImplementedError("SoccerbaseProvider.results: implement results page parse.")
