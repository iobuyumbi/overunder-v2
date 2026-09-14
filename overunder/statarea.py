"""Statarea consensus cross-check. Parser verified against the live card;
fetch layer: reader-proxy first, direct HTML fallback, validation gate."""

import os
import re
import sys
import time
import unicodedata
from datetime import date

import requests

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

from .config import (CACHE_DIR, FUZZY_MIN, JINA_PROXY, ST_HOME_MIN, ST_MIN_MATCHES,
                     ST_OVER_MIN, ST_UNDER_MAX, STATAREA_URL)
from .teams import find_match

TIME_RE = re.compile(r"^\d{2}:\d{2}$")
INT_RE = re.compile(r"^\d+$")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^ ]*\)")
HT_SCORE_RE = re.compile(r"^HT \d{1,2}:\d{1,2}$")
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

JINA_API_KEY = os.getenv("JINA_API_KEY", "")


def _dbg(msg):
    print(f"[statarea] {msg}", file=sys.stderr)


def _extract_html_text(html):
    """BeautifulSoup DOM-aware flattener — tag-stripping regex DESTROYS table
    row order on statarea HTML (cells collapse out of sequence). bs4's
    get_text("\n", strip=True) preserves DOM depth order so match rows
    arrive as TIME → votes → tip → home → − → away → stats, matching the
    exact layout the outer tokeniser expects."""
    if _HAS_BS4:
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        text = text.replace("\xa0", " ")
        return text
    html = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r'(?:alt|title)\s*=\s*"([^"]+)"', r"\n\1\n", html)
    html = re.sub(r"<[^>]+>", "\n", html)
    html = re.sub(r"&nbsp;?", " ", html)
    return html.replace("&amp;", "&")


def _dump_tokens_for_debug(tokens, limit=80):
    """Print the first N tokens to stderr so the user can paste them when
    parse_card returns 0 matches. This lets us identify the exact token
    order the site is currently producing without needing a network trace."""
    if not tokens:
        _dbg("tokens list is EMPTY — _extract_html_text produced nothing")
        return
    _dbg(f"first {min(limit, len(tokens))} tokens produced by extractor:")
    for i in range(min(limit, len(tokens))):
        t = tokens[i]
        tag = []
        if TIME_RE.match(t):
            tag.append("TIME")
        if INT_RE.match(t):
            tag.append("INT")
        if t.lower() in NOISE:
            tag.append("NOISE")
        if HT_SCORE_RE.match(t):
            tag.append("HT")
        suffix = f"  [{', '.join(tag)}]" if tag else ""
        _dbg(f"  [{i:4d}] {t!r}{suffix}")


def parse_card(text, debug_dump=False):
    if "<" in text and ">" in text:
        text = _extract_html_text(text)
    text = "\n".join(
        MD_LINK_RE.sub(r"\1", ln).replace("**", "")
        for ln in text.splitlines()
    )
    tokens = [t.strip() for t in text.splitlines() if t.strip()]
    matches, league, i = [], None, 0
    times_seen = 0
    blocks_tried = 0
    blocks_ok = 0
    while i < len(tokens):
        t = tokens[i]
        if t.lower() in NOISE or HT_SCORE_RE.match(t):
            i += 1
            continue
        if ("-" in t and t == t.upper() and re.search(r"[A-Z]{3,}", t)
                and not TIME_RE.match(t) and len(t) > 6):
            league, i = t, i + 1
            continue
        if TIME_RE.match(t):
            times_seen += 1
            blocks_tried += 1
            parsed, next_i = _parse_block(tokens, i, league)
            if parsed:
                matches.append(parsed)
                blocks_ok += 1
            i = next_i
            continue
        i += 1
    if debug_dump or (len(matches) == 0 and len(tokens) > 0):
        _dbg(f"parse summary: {len(tokens)} tokens, {times_seen} TIME tokens, "
             f"{blocks_tried} blocks attempted, {blocks_ok} blocks OK, "
             f"{len(matches)} matches")
        if len(matches) == 0:
            _dump_tokens_for_debug(tokens, limit=120)
    return matches


def _parse_block(tokens, i, league):
    n = len(tokens)
    j = i + 1

    def skip_seps(idx):
        while idx < n:
            tok = tokens[idx]
            if tok == "-" or tok.startswith("**") or HT_SCORE_RE.match(tok):
                idx += 1
            elif INT_RE.match(tok):
                idx += 1
            else:
                break
        return idx

    try:
        while j < n and not INT_RE.match(tokens[j]):
            j += 1
        votes1 = int(tokens[j]); j += 1
        votes2 = int(tokens[j]); j += 1
        tip = tokens[j]; j += 1
        j = skip_seps(j)
        home = tokens[j]; j += 1
        j = skip_seps(j)
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
    headers_with_auth = dict(HEADERS)
    if JINA_API_KEY:
        headers_with_auth["Authorization"] = f"Bearer {JINA_API_KEY}"
    last_raw = None
    for attempt in range(retries + 1):
        for name, url, cache, use_auth in (
            ("jina-proxy", JINA_PROXY, f"{day}.md", True),
            ("direct", STATAREA_URL, f"{day}.html", False),
        ):
            try:
                hdrs = headers_with_auth if use_auth else HEADERS
                r = requests.get(url, headers=hdrs, timeout=60)
                _dbg(f"'{name}': HTTP {r.status_code}, {len(r.text)} bytes")
                if not r.ok or len(r.text) < 20000:
                    continue
                last_raw = (name, cache, r.text)
                games = parse_card(r.text, debug_dump=True)
                if len(games) < ST_MIN_MATCHES:
                    _dbg(f"'{name}': only {len(games)} games parsed (< {ST_MIN_MATCHES}) -- trying next")
                    # Always save even the failing raw response so we can post-mortem
                    diag = os.path.join(CACHE_DIR, f"FAILED_{name}_{cache}")
                    try:
                        with open(diag, "w", encoding="utf-8") as f:
                            f.write(r.text)
                        _dbg(f"'{name}': raw page saved for diagnosis -> {diag}")
                    except OSError as e:
                        _dbg(f"(could not save diagnostic file: {e})")
                    continue
                path = os.path.join(CACHE_DIR, cache)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(r.text)
                _dbg(f"'{name}' OK: {len(games)} games cached")
                return r.text
            except requests.RequestException as e:
                _dbg(f"'{name}' failed: {e}")
        time.sleep(3 * (attempt + 1))
    hint = ""
    if last_raw:
        hint = (f"\n  Last fetch was '{last_raw[0]}' ({len(last_raw[2])} bytes) — "
                f"see FAILED_* files in {CACHE_DIR} for the raw page. "
                f"Paste the first 40 lines of FAILED_direct_{day}.html into chat "
                f"and I'll write the exact extractor for this layout.")
    raise RuntimeError(
        "could not fetch a usable Statarea card. If jina-proxy returned "
        "401/402/429 it now needs a free API key (add JINA_API_KEY to .env); "
        "if direct returned 403 the runner IP is blocked. "
        "Use load_card_file() with a browser-saved page." + hint)


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
