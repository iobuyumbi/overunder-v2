"""Offline backtest driven by data/history_db.json only (no network).

The live `backtest` command re-scrapes soccerbase when the page cache is cold
(~/.cache/overunder is empty right now), which takes far longer than a single
shell call allows. This script replays the same no-lookahead logic using the
backfilled local DB and the REAL build_pick/settle code paths, so rules and
thresholds are identical to production.

Usage: venv/Scripts/python backtest_offline.py [--days 50] [--markets home_dw,...]
"""
import argparse
import json
import sys
from datetime import date, timedelta

from overunder.predict import build_pick
from overunder.history import _settle_one
from overunder.teams import normalize
from overunder.config import MARKET_MIN_CONF

DB_PATH = "data/history_db.json"


class OfflineProvider:
    """team_matches backed by history_db.json, sorted ascending, limit 12 --
    mirrors SoccerbaseProvider.team_matches(before=...) semantics."""

    def __init__(self, db):
        self.db = db

    def team_matches(self, team, limit=12, before=None):
        ms = [m for m in self.db.get(normalize(team), [])
              if m.get("date") and (before is None or m["date"] < before)]
        ms.sort(key=lambda m: m["date"])
        return ms[-limit:]


def played_matches(db):
    """Reconstruct unique played matches (one entry per fixture) from the
    per-team rows. Home side identified by venue == 'H'."""
    seen = {}
    for team, ms in db.items():
        for m in ms:
            if m.get("venue") != "H" or not m.get("date") or not m.get("opp"):
                continue
            key = (m["date"], team, normalize(m["opp"]))
            seen[key] = {"date": m["date"], "home": team, "away": m["opp"],
                         "hg": m["gf"], "ag": m["ga"]}
    return sorted(seen.values(), key=lambda r: r["date"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=50)
    ap.add_argument("--markets", default="home_dw")
    ap.add_argument("--odds", type=float, default=2.0)
    args = ap.parse_args()

    db = json.load(open(DB_PATH, encoding="utf-8"))
    prov = OfflineProvider(db)
    matches = played_matches(db)
    by_day = {}
    for r in matches:
        by_day.setdefault(r["date"], []).append(r)

    mkts = tuple(m.strip() for m in args.markets.split(",") if m.strip())
    agg = {m: {"n": 0, "w": 0, "l": 0, "profit": 0.0} for m in mkts}
    agg2 = {m: {"PREMIUM": {"n": 0, "w": 0, "profit": 0.0},
                "SOLID": {"n": 0, "w": 0, "profit": 0.0}} for m in mkts}
    TIERS = [(0.55, 0.65), (0.65, 0.75), (0.75, 0.85), (0.85, 1.01)]
    tiers = {m: {t: {"n": 0, "w": 0, "profit": 0.0} for t in TIERS} for m in mkts}
    alln = 0
    days_used = 0

    today = date.today()
    for i in range(args.days, 0, -1):
        d = (today - timedelta(days=i)).isoformat()
        played = by_day.get(d, [])
        if not played:
            continue
        days_used += 1
        day_n = 0
        for r in played:
            fx = {"date": d, "league": "", "home": r["home"], "away": r["away"]}
            for mkt in mkts:
                try:
                    p = build_pick(fx, prov, market=mkt, odds=args.odds, before=d)
                except Exception:
                    continue
                thr = MARKET_MIN_CONF.get(mkt) or 0.55
                if p["confidence"] < thr:
                    continue
                res = _settle_one(p, r["hg"], r["ag"])
                g = agg[mkt]
                g["n"] += 1
                t2 = agg2[mkt]["PREMIUM" if p["tier"].startswith("🔥") else "SOLID"]
                t2["n"] += 1
                if res == "W":
                    g["w"] += 1
                    profit = p["stake_pct"] * (args.odds - 1)
                    t2["w"] += 1
                    t2["profit"] += profit
                elif res == "L":
                    g["l"] += 1
                    profit = -p["stake_pct"]
                    t2["profit"] += profit
                else:
                    profit = 0.0
                g["profit"] += profit
                for t in TIERS:
                    if t[0] <= p["confidence"] < t[1]:
                        tg = tiers[mkt][t]
                        tg["n"] += 1
                        if res == "W":
                            tg["w"] += 1
                            tg["profit"] += p["stake_pct"] * (args.odds - 1)
                        elif res == "L":
                            tg["profit"] -= p["stake_pct"]
                        break
                day_n += 1
                alln += 1
        print(f"  {d}: {len(played)} matches, {day_n} picks", file=sys.stderr)

    print("\n== BY TIER (premium vs solid) ==")
    for m in mkts:
        row = f"  {m:<9}"
        for tn in ("PREMIUM", "SOLID"):
            t = agg2[m][tn]
            wp = round(100 * t["w"] / t["n"], 1) if t["n"] else 0.0
            row += f" | {tn}: {wp:>5}% n={t['n']:>4} {t['profit']:+.1f}u"
        print(row)
    print("\n== WIN% BY CONFIDENCE TIER ==")
    for m in mkts:
        row = "  " + f"{m:<9}"
        for t in TIERS:
            tg = tiers[m][t]
            wp = round(100 * tg["w"] / tg["n"], 1) if tg["n"] else 0.0
            row += f" | {t[0]:.2f}-{min(t[1], 1.0):.2f}: {wp:>5}% n={tg['n']:>4}"
        print(row)
    print("\n== BACKTEST (offline, history_db only, no-lookahead) ==")
    tw = tl = 0
    for m in mkts:
        g = agg[m]
        tw += g["w"]; tl += g["l"]
        wp = round(100 * g["w"] / g["n"], 1) if g["n"] else 0.0
        print(f"  {m:<10} {g['n']:>3} picks  {g['w']}W-{g['l']}L  {wp:>5}%  "
              f"profit {g['profit']:+.2f} units")
    wp = round(100 * tw / alln, 1) if alln else 0.0
    print(f"  {'TOTAL':<10} {alln:>3} picks  {tw}W-{tl}L  {wp:>5}%")
    print(f"({days_used} match days replayed, per-market gates from config, "
          f"odds {args.odds})")


if __name__ == "__main__":
    main()
