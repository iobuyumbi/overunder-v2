"""Prediction history store: pending picks, settled results, ROI stats."""

import json
import os
import time
import uuid

from .config import HISTORY_FILE


def _load():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"pending": [], "settled": []}


def _save(h):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(h, f, indent=2)
    os.replace(tmp, HISTORY_FILE)


def record_picks(picks):
    h = _load()
    seen = {(p["date"], p["home"], p["away"]) for p in h["pending"] + h["settled"]}
    added = 0
    for p in picks:
        key = (p["date"], p["home"], p["away"])
        if key in seen:
            continue
        rec = dict(p)
        rec["id"] = uuid.uuid4().hex[:12]
        rec["recorded_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        rec["result"] = None
        rec["profit"] = None
        h["pending"].append(rec)
        added += 1
    _save(h)
    return added


def _settle_one(rec, hg, ag):
    total = hg + ag
    if rec["market"] == "over":
        return "W" if total > rec.get("line", 2.5) else "L"
    if rec["market"] == "under":
        return "W" if total < rec.get("line", 2.5) else "L"
    if rec["market"] == "home":
        return "W" if hg > ag else "L"
    return "P"


def settle(results):
    """Match pending picks to results (normalized team names). Returns settled count."""
    from .teams import find_match
    h = _load()
    still, settled_n = [], 0
    for rec in h["pending"]:
        g, _ = find_match(rec["home"], rec["away"], results)
        if not g:
            still.append(rec)
            continue
        res = _settle_one(rec, g["hg"], g["ag"])
        rec["result"] = res
        rec["score"] = f'{g["hg"]}-{g["ag"]}'
        if res == "W":
            rec["profit"] = round(rec["stake_pct"] * (rec.get("odds", 2.0) - 1), 2)
        elif res == "L":
            rec["profit"] = -rec["stake_pct"]
        else:
            rec["profit"] = 0.0
        h["settled"].append(rec)
        settled_n += 1
    h["pending"] = still
    _save(h)
    return settled_n


def _group_stats(recs, key_fn):
    groups = {}
    for r in recs:
        k = key_fn(r) or "none"
        g = groups.setdefault(k, {"n": 0, "w": 0, "l": 0, "profit": 0.0})
        g["n"] += 1
        if r["result"] == "W":
            g["w"] += 1
        elif r["result"] == "L":
            g["l"] += 1
        g["profit"] = round(g["profit"] + (r["profit"] or 0.0), 2)
    for g in groups.values():
        g["win_pct"] = round(100 * g["w"] / g["n"], 1) if g["n"] else 0.0
    return groups


def stats():
    h = _load()
    s = h["settled"]
    out = {
        "overall": _group_stats(s, lambda r: "all"),
        "by_signal": _group_stats(s, lambda r: r.get("statarea_signal")),
        "by_tier": _group_stats(s, lambda r: r.get("tier")),
        "pending": len(h["pending"]),
        "settled_total": len(s),
    }
    return out


def yesterday_record(day_before=None):
    """'7W-2L-0P' style record for the report header."""
    import datetime
    h = _load()
    if day_before is None:
        day_before = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    recs = [r for r in h["settled"] if r["date"] == day_before]
    w = sum(1 for r in recs if r["result"] == "W")
    l = sum(1 for r in recs if r["result"] == "L")
    p = len(recs) - w - l
    return f"{w}W-{l}L-{p}P"
