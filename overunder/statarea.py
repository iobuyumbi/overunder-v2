"""Statarea consensus cross-check. Parser verified against the live card;
fetch layer: reader-proxy first, direct HTML fallback, validation gate."""

import os
import re
import sys
import time
import unicodedata
from datetime import date

import requests

from .config import (CACHE_DIR, FUZZY_MIN, JINA_PROXY, ST_HOME_MIN, ST_MIN_MATCHES,
                     ST_OVER_MIN, ST_UNDER_MAX, STATAREA_URL)
from .teams import find_match

TIME_RE = re.compile(r"^\d{2}:\d{2}$")
INT_RE = re.compile(r"^\d+$")
NOISE = {
    "tip", "1", "x", "2", "ht1", "htx", "ht2", "1.5", "2.5", "3.5", "bts",
    "ots", "your prediction", "advertisement", "go", "close x", "actions",
    "gmt 0", "time zone", "select", "competition", "sort by",
    "click to select competition", "scroll to competition", "expand all",
    "collapse all", "all predicted matches", "switch to mobile site",
    "select date", "back to top", "tipster24.com go your bet navigator",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def _dbg(msg):
    print(f"[statarea] {msg}", file=sys.stderr)


def _extract_html_text(html):
    html = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r'(?:alt|title)\s*=\s*"([^"]+)"', r"\n\1\n", html)
    html = re.sub(r"<[^>]+>", "\n", html)
    html = re.sub(r"&nbsp;?", " ", html)
    return html.replace("&amp;", "&")


def parse_card(text):
    if "<" in text and ">" in text:
        text = _extract_html_text(text)
    tokens = [t.strip() for t in text.splitlines() if t.strip()]
    matches, league, i = [], None, 0
    while i < len(tokens):
        t = tokens[i]
        if t.lower() in NOISE:
            i += 1
            continue
        if ("-" in t and t == t.upper() and re.search(r"[A-Z]{3,}", t)
                and not TIME_RE.match(t) and len(t) > 6):
            league, i = t, i + 1
            continue
        if TIME_RE.match(t):
            parsed, i = _parse_block(tokens, i, league)
            if parsed:
                matches.append(parsed)
            continue
        i += 1
    return matches


def _parse_block(tokens, i, league):
    n = len(tokens)
    j = i + 1
    try:
        while j < n and not INT_RE.match(tokens[j]):
            j += 1
        votes1 = int(tokens[j]); j += 1
        votes2 = int(tokens[j]); j += 1
        tip = tokens[j]; j += 1
        while j < n and (tokens[j] == "-" or INT_RE.match(tokens[j])):
            j += 1
        home = tokens[j]; j += 1
        while j < n and (tokens[j] == "-" or INT_RE.match(tokens[j])):
            j += 1
        away = tokens[j]; j += 1
        stats = []
        while j < n and len(stats) < 11 and INT_RE.match(tokens[j]):
            stats.append(int(tokens[j])); j += 1
        if len(stats) < 11:
            return None, i + 1
        return {"league": league, "time": tokens[i], "home": home, "away": away,
                "tip": tip, "p_home": stats[0], "p_draw": stats[1], "p_away": stats[2],
                "p_over15": stats[6], "over25": stats[7], "p_over35": stats[8],
                "p_btts": stats[9], "under25": 100 - stats[7]}, j
    except (IndexError, ValueError):
        return None, i + 1


def fetch_card(day=None, retries=2):
    day = day or date.today().isoformat()
    os.makedirs(CACHE_DIR, exist_ok=True)
    for attempt in range(retries + 1):
        for name, url, cache in (("jina-proxy", JINA_PROXY, f"{day}.md"),
                                 ("direct", STATAREA_URL, f"{day}.html")):
            try:
                r = requests.get(url, headers=HEADERS, timeout=60)
                _dbg(f"'{name}': HTTP {r.status_code}, {len(r.text)} bytes")
                if not r.ok or len(r.text) < 20000:
                    continue
                games = parse_card(r.text)
                if len(games) < ST_MIN_MATCHES:
                    _dbg(f"'{name}': only {len(games)} games parsed (< {ST_MIN_MATCHES}) -- trying next")
                    continue
                path = os.path.join(CACHE_DIR, cache)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(r.text)
                _dbg(f"'{name}' OK: {len(games)} games cached")
                return r.text
            except requests.RequestException as e:
                _dbg(f"'{name}' failed: {e}")
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(
        "could not fetch a usable Statarea card. If jina-proxy returned "
        "401/402/429 it now needs a free API key; if direct returned 403 the "
        "runner IP is blocked. Use load_card_file() with a browser-saved page.")


def load_card(day=None, max_age_hours=12):
    day = day or date.today().isoformat()
    for fn in (f"{day}.md", f"{day}.html"):
        path = os.path.join(CACHE_DIR, fn)
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_hours * 3600:
            with open(path, encoding="utf-8") as f:
                return f.read()
    return fetch_card(day)


def load_card_file(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def cross_check(picks, games, over_min=ST_OVER_MIN, under_max=ST_UNDER_MAX, home_min=ST_HOME_MIN):
    """Annotate each pick with statarea's view. Never filters — tags only."""
    out = []
    for p in picks:
        g, score = find_match(p["home"], p["away"], games)
        sig = "NOT_FOUND"
        st = None
        if g:
            st = {"over25": g["over25"], "under25": g["under25"], "p_home": g["p_home"],
                  "p_draw": g["p_draw"], "p_away": g["p_away"], "p_btts": g["p_btts"],
                  "league": g["league"], "home": g["home"], "away": g["away"]}
            mkt = (p.get("market") or "").lower()
            if mkt.startswith("over") and g["over25"] >= over_min:
                sig = "AGREE_OVER"
            elif mkt.startswith("under") and g["over25"] <= under_max:
                sig = "AGREE_UNDER"
            elif mkt in ("home", "1") and g["p_home"] >= home_min:
                sig = "AGREE_HOME"
            elif mkt:
                sig = "DIVERGE"
            else:
                sig = "INFO"
        q = dict(p)
        q["statarea"] = st
        q["statarea_signal"] = sig
        q["match_score"] = score
        out.append(q)
    return out


def list_filtered(games, over_min=ST_OVER_MIN, under_max=ST_UNDER_MAX, home_min=ST_HOME_MIN):
    return {
        "over_games": [f'{g["home"]} vs {g["away"]} ({g["over25"]}%)' for g in games if g["over25"] >= over_min],
        "under_games": [f'{g["home"]} vs {g["away"]} (U {g["under25"]}%)' for g in games if g["over25"] <= under_max],
        "home_games": [f'{g["home"]} vs {g["away"]} (1 {g["p_home"]}%)' for g in games if g["p_home"] >= home_min],
    }
