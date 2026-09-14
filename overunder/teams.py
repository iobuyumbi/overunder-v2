"""Team-name normalization, aliases, and matching (yours <-> statarea <-> results)."""

import re
import unicodedata
from difflib import SequenceMatcher

from .config import FUZZY_MIN

PREFIXES = ("fc", "afc", "cf", "sc", "ac", "as", "us", "cd", "ud", "ss", "nk",
            "ifk", "bk", "fk", "sk", "ca", "rc", "real", "club", "calcio")

# Keys MUST be the normalized form (i.e. after prefix-stripping). Verify each
# alias against statarea's actual spelling — a wrong alias silently pairs the
# wrong teams.
ALIASES = {
    "go a eagles": "go ahead eagles",
    "f sittard": "fortuna sittard",
    "bristol c": "bristol city",
    "boreham w": "boreham wood",
    "fylde": "afc fylde",
    "st gallen": "fc st gallen",
    "sion": "fc sion",
    "yeovil": "yeovil town",
    "carlisle": "carlisle united",
    "harrogate": "harrogate town",
    "groningen": "fc groningen",
    "nec": "nec nijmegen",
    "cambuur": "sc cambuur",
    "enfield t": "enfield town",
    "cray w": "cray wanderers",
    "utd": "fc utd of manchester",
    "bamber br": "bamber bridge",
    "curzon a": "curzon ashton",
    "paranaense": "atletico paranaense",
    "suwon samsung": "suwon bluewings",
    "kawasaki f": "kawasaki frontale",
    "accrington": "accrington st",
}


def normalize(name):
    n = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    n = re.sub(r"[^a-z0-9 ]", " ", n.lower())
    n = re.sub(r"\s+", " ", n).strip()
    n = re.sub(r"^(?:" + "|".join(PREFIXES) + r") ", "", n).strip()
    return ALIASES.get(n, n)


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


def find_match(home, away, games, fuzzy_min=FUZZY_MIN):
    """Exact-normalized pair match first, then fuzzy. Returns (game, score)."""
    h, a = normalize(home), normalize(away)
    best, best_score = None, 0.0
    for g in games:
        gh, ga = normalize(g.get("home", "")), normalize(g.get("away", ""))
        if gh == h and ga == a:
            return g, 1.0
        s = (similar(h, gh) + similar(a, ga)) / 2
        if s > best_score:
            best, best_score = g, s
    return (best, round(best_score, 2)) if best_score >= fuzzy_min else (None, round(best_score, 2))
