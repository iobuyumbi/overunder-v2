"""Command-line interface.

    python -m overunder demo                full offline cycle: predict + cross-check
                                            + report (+ settle/stat when results exist)
    python -m overunder predict [--date D]  generate picks (real provider unless --demo)
    python -m overunder compare --picks f   cross-check external picks vs statarea card
    python -m overunder settle [--demo]     settle pending picks against results
    python -m overunder stats               ROI by signal/tier
    python -m overunder report [--demo]     render VIP-style report
    python -m overunder fetch-statarea      cache today's statarea card
"""

import argparse
import json
import os
import sys

from . import config
from .predict import predict_day
from .providers import DemoProvider, SoccerbaseProvider
from .report import render_report
from .notify import send_telegram
from . import history as hist
from . import statarea as st


def _provider(use_demo):
    if use_demo:
        return DemoProvider()
    return SoccerbaseProvider()


def _date_range(args):
    from datetime import date, timedelta
    start = args.date or date.today().isoformat()
    n = getattr(args, "days", 1) or 1
    return [(date.fromisoformat(start) + timedelta(days=i)).isoformat()
            for i in range(n)]


def _markets(arg):
    return tuple(m.strip() for m in (arg or "over").split(",") if m.strip())


def _maybe_tag_statarea(picks, args):
    """Tag picks with statarea consensus if a card is available; otherwise
    warn once and continue untagged -- predictions never block on statarea."""
    if not getattr(args, "statarea", False):
        return picks
    try:
        text = st.load_card_file(args.card) if getattr(args, "card", None) else st.load_card(args.date)
        games = st.parse_card(text)
        if len(games) < st.ST_MIN_MATCHES:
            print(f"[statarea] only {len(games)} games parsed -- skipping tags",
                  file=sys.stderr)
            return picks
        return st.cross_check(picks, games)
    except Exception as e:
        print(f"[statarea] unavailable ({e}) -- continuing without tags",
              file=sys.stderr)
        return picks


def cmd_demo(args):
    prov = DemoProvider()
    picks = predict_day(prov, day=args.date, markets=_markets(args.markets),
                        market_min_conf={})   # flat 0.55: showcase the machinery
    sample_card = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "sample_data", "sample_card_2026-09-12.md")
    games = st.parse_card(open(sample_card, encoding="utf-8").read())
    picks = st.cross_check(picks, games)
    report = render_report(picks, day=args.date)
    print(report)
    added = hist.record_picks(picks)
    print(f"[demo] recorded {added} picks to history", file=sys.stderr)
    n = hist.settle(prov.results())
    print(f"[demo] settled {n} picks (results were available)", file=sys.stderr)
    if args.telegram:
        send_telegram(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(picks, f, indent=2)


def cmd_predict(args):
    prov = _provider(args.demo)
    mkts = _markets(args.markets)
    picks = []
    demo_bypass = {} if args.demo else None
    for d in _date_range(args):
        try:
            fxs = prov.fixtures(d)
            print(f"predicting {len(fxs)} fixtures x {len(mkts)} markets for {d}...",
                  file=sys.stderr, flush=True)
            picks += predict_day(prov, day=d, odds=args.odds, markets=mkts,
                                 market_min_conf=demo_bypass)
        except RuntimeError as e:
            print(f"PREDICT FAILED for {d}: {e}", file=sys.stderr)
            if getattr(args, "days", 1) == 1:
                sys.exit(f"Diagnose with:  python -m overunder scrape-check --date {d}\n"
                         f"Or offline demo:  python -m overunder predict --demo")
    # statarea cards only exist for ~today: tag just those, skip future days
    today_picks = [p for p in picks if p.get("date") == __import__("datetime").date.today().isoformat()]
    other_picks = [p for p in picks if p not in today_picks]
    picks = _maybe_tag_statarea(today_picks, args) + other_picks
    added = hist.record_picks(picks)
    print(json.dumps(picks, indent=2))
    print(f"recorded {added} new picks -> {config.HISTORY_FILE}", file=sys.stderr)


def cmd_compare(args):
    text = st.load_card_file(args.card) if args.card else st.load_card(args.date)
    games = st.parse_card(text)
    print(f"parsed {len(games)} games", file=sys.stderr)
    if args.picks.lower().endswith(".csv"):
        import csv
        with open(args.picks, newline="", encoding="utf-8-sig") as f:
            picks = list(csv.DictReader(f))
    else:  # VIP report txt
        import re
        picks, market = [], "over"
        for line in open(args.picks, encoding="utf-8", errors="replace"):
            low = line.lower()
            if "under 2.5" in low and "over" not in low:
                market = "under"
            elif "over 2.5" in low:
                market = "over"
            m = re.match(r"^\s*(\d+)\.\s+(.+?)\s+vs\s+(.+?)\s*$", line)
            if m:
                picks.append({"home": m.group(2).strip(), "away": m.group(3).strip(),
                              "market": market, "num": int(m.group(1))})
    out = st.cross_check(picks, games)
    print(f'{"#":<4}{"MATCH":<44}{"ST-O25":<8}{"ST-1":<6}SIGNAL')
    for r in out:
        s = r.get("statarea") or {}
        print(f"{r.get('num',''):<4}{r['home'] + ' vs ' + r['away']:<44}"
              f"{str(s.get('over25','-')):<8}{str(s.get('p_home','-')):<6}{r['statarea_signal']}")
    summary = {}
    for r in out:
        summary[r["statarea_signal"]] = summary.get(r["statarea_signal"], 0) + 1
    print(f"\nsummary: {summary}")
    print("NO MATCH: " + "; ".join(f"{r['home']} vs {r['away']}" for r in out
                                    if r["statarea_signal"] == "NOT_FOUND"))


def cmd_settle(args):
    prov = DemoProvider() if args.demo else _provider(False)
    prov.fresh = True   # settlement needs live scores, not the 6h cache
    if args.date:
        n = hist.settle(prov.results(args.date))
        print(f"settled {n} picks for {args.date}")
        return
    # auto: fetch each pending pick's own day page (cached) and settle what matches
    h = hist._load()
    dates = sorted({r["date"] for r in h["pending"]})
    if not dates:
        print("nothing pending")
        return
    total = 0
    for d in dates:
        try:
            rows = prov.results(d)
        except RuntimeError as e:
            print(f"{d}: cannot fetch results ({e})", file=sys.stderr)
            continue
        n = hist.settle(rows)
        total += n
        print(f"  {d}: settled {n}")
    print(f"settled {total} picks across {len(dates)} day(s)")


def _fmt_group(name, g):
    return (f"  {name:<14} {g['n']:>3} picks  {g['w']}W-{g['l']}L  "
            f"{g['win_pct']:>5}%  profit {g['profit']:+.2f}")


def cmd_stats(args):
    s = hist.stats()
    if getattr(args, "json", False):
        print(json.dumps(s, indent=2))
        return
    print("== PREDICTION STATS ==")
    for name, g in s.get("overall", {}).items():
        print("OVERALL      " + _fmt_group(name, g)[2:])
    def _show(title, groups):
        print(title)
        if not groups:
            print("  (none settled yet)")
        for name, g in sorted(groups.items()):
            print(_fmt_group(name, g))
    _show("BY STATAREA SIGNAL:", s.get("by_signal", {}))
    _show("BY MARKET:", s.get("by_market", {}))
    _show("BY TIER:", s.get("by_tier", {}))
    print(f"pending: {s['pending']}   settled: {s['settled_total']}")


def cmd_backtest(args):
    """Replay past days: generate the picks the model WOULD have made using
    only data available before each match day (no lookahead), settle against
    the actual results, and report hypothetical performance per market.

    Run `backfill --days N` first so the day pages are cached; backtest then
    costs no extra network."""
    from datetime import date, timedelta
    from .providers import SoccerbaseProvider, load_history_db
    from .predict import build_pick
    from .history import _settle_one
    from .config import O25_MIN_CONFIDENCE
    prov = SoccerbaseProvider()
    mkts = _markets(args.markets)
    min_conf = args.min_conf
    if not load_history_db():
        print("WARNING: history_db.json is empty -- run 'backfill --days N' first "
              "for meaningful form data.", file=sys.stderr)
    agg = {m: {"n": 0, "w": 0, "l": 0, "profit": 0.0} for m in mkts}
    agg2 = {m: {"🔥": {"n": 0, "w": 0, "profit": 0.0},
                "✅": {"n": 0, "w": 0, "profit": 0.0}} for m in mkts}
    TIERS = [(0.55, 0.65), (0.65, 0.75), (0.75, 0.85), (0.85, 1.01)]
    tiers = {m: {t: {"n": 0, "w": 0, "profit": 0.0} for t in TIERS} for m in mkts}
    alln = 0
    days_used = 0
    audit_violations = []
    for i in range(args.days, 0, -1):
        d = (date.today() - timedelta(days=i)).isoformat()
        try:
            rows = prov.day_rows(d)
        except RuntimeError:
            continue
        played = [r for r in rows if r["hg"] is not None]
        if not played:
            continue
        days_used += 1
        day_n = 0
        for r in played:
            fx = {"date": d, "league": r["league"],
                  "home": r["home"], "away": r["away"]}
            for mkt in mkts:
                p = build_pick(fx, prov, market=mkt, odds=args.odds, before=d)
                if args.no_market_thresholds:
                    thr = min_conf
                else:
                    from .config import MARKET_MIN_CONF as _MMC
                    thr = _MMC.get(mkt) or min_conf
                if p["confidence"] < thr:
                    continue
                res = _settle_one(p, r["hg"], r["ag"])
                g = agg[mkt]
                g["n"] += 1
                t2 = agg2[mkt]["🔥" if p["tier"].startswith("🔥") else "✅"]
                t2["n"] += 1
                if res == "W":
                    t2["w"] += 1
                    t2["profit"] += p["stake_pct"] * (args.odds - 1)
                elif res == "L":
                    t2["profit"] -= p["stake_pct"]
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
                profit = 0.0
                if res == "W":
                    g["w"] += 1
                    profit = p["stake_pct"] * (args.odds - 1)
                elif res == "L":
                    g["l"] += 1
                    profit = -p["stake_pct"]
                g["profit"] += profit
                if args.audit:
                    # lookahead detector: no form match may be dated on/after
                    # the fixture day. Memoized cache makes this ~free.
                    for tm in (fx["home"], fx["away"]):
                        for m in prov.team_matches(tm, before=d):
                            if m.get("date", "9999") >= d:
                                audit_violations.append(
                                    f"{d} {fx['home']} vs {fx['away']}: {tm} uses "
                                    f"{m['date']} match ({m['gf']}-{m['ga']})")
                                break
                if args.verbose:
                    mark = {"W": "+", "L": "-", "P": "o"}.get(res, "?")
                    print(f"  [{mark}] {d} {fx['home']} vs {fx['away']} | {mkt:<8} "
                          f"conf {p['confidence']:.2f} | H {p.get('home_attack','?')}/"
                          f"{p.get('home_concede','?')} A {p.get('away_attack','?')}/"
                          f"{p.get('away_concede','?')} (scored/conceded) | "
                          f"{r['hg']}-{r['ag']} ({profit:+.1f})")
                day_n += 1
                alln += 1
        print(f"  {d}: {len(played)} matches, {day_n} picks", file=sys.stderr)
    print("\n== BY TIER (premium vs solid) ==")
    for m in mkts:
        row = f"  {m:<9}"
        for tier_key, tier_name in (("🔥", "PREMIUM"), ("✅", "SOLID")):
            t = agg2[m][tier_key]
            wp = round(100 * t["w"] / t["n"], 1) if t["n"] else 0.0
            row += f" | {tier_name}: {wp:>5}% n={t['n']:>4} {t['profit']:+.1f}u"
        print(row)
    print("\n== WIN% BY CONFIDENCE TIER ==")
    for m in mkts:
        row = "  " + f"{m:<9}"
        for t in TIERS:
            tg = tiers[m][t]
            wp = round(100 * tg["w"] / tg["n"], 1) if tg["n"] else 0.0
            row += f" | {t[0]:.2f}-{min(t[1],1.0):.2f}: {wp:>5}% n={tg['n']:>4}"
        print(row)
    print("(if higher tiers are not clearly better, raising min_conf buys nothing)")
    print("\n== BACKTEST (hypothetical, no-lookahead) ==")
    tw = tl = 0
    for m in mkts:
        g = agg[m]
        tw += g["w"]; tl += g["l"]
        wp = round(100 * g["w"] / g["n"], 1) if g["n"] else 0.0
        print(f"  {m:<10} {g['n']:>3} picks  {g['w']}W-{g['l']}L  {wp:>5}%  "
              f"profit {g['profit']:+.2f} units")
    wp = round(100 * tw / alln, 1) if alln else 0.0
    print(f"  {'TOTAL':<10} {alln:>3} picks  {tw}W-{tl}L  {wp:>5}%")
    if args.audit:
        print(f"\nAUDIT: {len(audit_violations)} lookahead violations "
              f"across {alln} picks")
        for v in audit_violations[:10]:
            print("  " + v)
        if not audit_violations:
            print("  clean: every pick used only pre-match form")
    print(f"({days_used} match days replayed, min_confidence {min_conf}, "
          f"odds {args.odds})")


def cmd_team_stats(args):
    """Scoring profile for one team: venue-split score/concede rates, over and
    BTTS rates, recent results -- the exact form data the rules consume."""
    from .report import render_team_stats
    prov = DemoProvider() if args.demo else _provider(False)
    matches = prov.team_matches(args.team)
    if not matches:
        sys.exit(f"no matches found for '{args.team}'")
    print(render_team_stats(args.team, matches))


def cmd_recent(args):
    """Show recent settled picks with their tier category, signal, and result."""
    h = hist._load()
    recs = h["settled"][-args.n:]
    if not recs:
        print("nothing settled yet")
        return
    print(f'{"DATE":<12}{"MATCH":<42}{"MARKET":<10}{"TIER":<10}{"SIGNAL":<18}{"SCORE":<8}R  P/L')
    for r in recs:
        tier = "PREMIUM" if (r.get("tier") or "").startswith("🔥") else "solid"
        print(f"{r['date']:<12}{r['home'] + ' vs ' + r['away']:<42}"
              f"{r.get('market','?'):<10}{tier:<10}{r.get('statarea_signal','-'):<18}"
              f"{r.get('score','-'):<8}{r['result']}  {r.get('profit',0):+.2f}")
    s = hist.stats()
    print(f"\npending: {s['pending']}   settled: {s['settled_total']}")


def cmd_retag(args):
    """Re-tag PENDING picks with the current statarea card. Fixes labels that
    were recorded under a broken card (e.g. the header-shift bug) without
    touching settled history. Settled picks are never modified."""
    try:
        text = st.load_card_file(args.card) if getattr(args, "card", None) else st.load_card(args.date)
    except Exception as e:
        sys.exit(f"retag: no statarea card available ({e})")
    games = st.parse_card(text)
    h = hist._load()
    changed = skipped = 0
    for rec in h["pending"]:
        pick = {"home": rec["home"], "away": rec["away"],
                "market": rec.get("market", "over")}
        out = st.cross_check([pick], games)[0]
        new_sig = out["statarea_signal"]
        if new_sig != rec.get("statarea_signal") or out["match_score"] != rec.get("match_score"):
            rec["statarea"] = out["statarea"]
            rec["statarea_signal"] = new_sig
            rec["match_score"] = out["match_score"]
            changed += 1
        else:
            skipped += 1
    hist._save(h)
    print(f"retagged {changed} pending picks ({skipped} unchanged). "
          f"Settled history untouched.")


def cmd_backfill(args):
    """Scrape results.sd for each of the last N days into the local history DB.
    One request per day with a polite delay; resumable (cached pages reused,
    already-stored matches deduped)."""
    import time as _time
    from datetime import date, timedelta
    from .providers import (SoccerbaseProvider, db_add_match, load_history_db,
                            save_history_db)
    prov = SoccerbaseProvider()
    db = load_history_db()
    added, days_ok = 0, 0
    for i in range(args.days):
        d = (date.today() - timedelta(days=i)).isoformat()
        try:
            rows = prov.results(d)
        except RuntimeError as e:
            print(f"{d}: fetch failed ({e})", file=sys.stderr)
            continue
        days_ok += 1
        for r in rows:
            added += db_add_match(db, r["home"], "H", r["hg"], r["ag"], d, opp=r["away"])
            added += db_add_match(db, r["away"], "A", r["ag"], r["hg"], d, opp=r["home"])
        if rows:
            print(f"{d}: {len(rows)} results", file=sys.stderr)
        if i % 10 == 9:
            save_history_db(db)
        _time.sleep(args.sleep)
    save_history_db(db)
    print(f"backfill done: {added} team-matches from {days_ok} days "
          f"({len(db)} teams in DB at {os.path.abspath(__import__('overunder.providers', fromlist=['HISTORY_DB']).HISTORY_DB)})")


def cmd_verify(args):
    """Audit data correctness: settled scores vs fresh scrape, parser sanity.
    Run after settle to confirm you are not losing to data errors."""
    from datetime import date
    from .teams import find_match
    h = hist._load()
    prov = SoccerbaseProvider()
    prov.fresh = True   # audit against live scores
    checked = missing = mismatched = 0
    for rec in h["settled"][-args.n:]:
        try:
            rows = prov.results(rec["date"])
        except RuntimeError:
            continue
        g, _ = find_match(rec["home"], rec["away"], rows)
        if not g:
            missing += 1
            print(f"  MISSING in scrape: {rec['home']} vs {rec['away']} ({rec['date']})")
            continue
        checked += 1
        if rec.get("score") and rec["score"] != f"{g['hg']}-{g['ag']}":
            mismatched += 1
            print(f"  MISMATCH {rec['home']} vs {rec['away']}: history {rec['score']} "
                  f"vs scrape {g['hg']}-{g['ag']}")
    day = date.today().isoformat()
    try:
        html = prov._get(f"{prov.BASE}/matches/results.sd?date={day}",
                         f"sb_date_{day}.html")
        rows = prov._parse_rows(html)
        noleague = sum(1 for r in rows if not r["league"])
        weird = [r for r in rows if r["hg"] is not None
                 and (r["hg"] > 12 or r["ag"] > 12)]
        print(f"parser sanity {day}: {len(rows)} rows, {noleague} without league, "
              f"{len(weird)} implausible scores")
    except RuntimeError as e:
        print(f"parser sanity: unchecked ({e})")
    print(f"verify: {checked} settled picks re-checked, {mismatched} mismatches, "
          f"{missing} missing from scrape")


def cmd_scrape_check(args):
    """Verify the soccerbase scraper from your machine before trusting it."""
    prov = SoccerbaseProvider()
    if getattr(args, "team", None):
        rows, snippets = prov.debug_team(args.team)
        scored = [r for r in rows if r["hg"] is not None]
        print(f"team '{args.team}': {len(scored)} scored / {len(rows)} total rows")
        for r in rows[:8]:
            score = f"{r['hg']}-{r['ag']}" if r["hg"] is not None else "v"
            print(f"  {r['date']}  {r['league'][:26]:<26} {r['home']} {score} {r['away']}")
        if not scored:
            print("\nDEBUG: no scores matched. Score-like text found on page:")
            for s in snippets:
                print("  ..." + s + "...")
            print("\nPaste the lines above to get the exact parser fix.")
        return
    day = args.date or __import__("time").strftime("%Y-%m-%d")
    print(f"checking soccerbase for {day} ...", file=sys.stderr)
    rows = prov._parse_rows(prov._get(f"{prov.BASE}/matches/results.sd?date={day}",
                                      f"sb_date_{day}.html"))
    played = [r for r in rows if r["hg"] is not None]
    fx = [r for r in rows if r["hg"] is None]
    print(f"parsed {len(rows)} rows: {len(played)} results, {len(fx)} fixtures")
    if rows and not played:
        import re as _re
        html = prov._get(f"{prov.BASE}/matches/results.sd?date={day}",
                         f"sb_date_{day}.html").replace("&nbsp;", " ")
        hits = []
        for m in prov.RE_SCORE_LOOSE.finditer(html):
            s = max(0, m.start() - 40)
            hits.append(html[s:m.end() + 25].replace("\n", " "))
            if len(hits) >= 5:
                break
        print("DEBUG: rows exist but no scores parsed. Score-like text on page:")
        for h in hits:
            print("  ..." + h + "...")
    for r in rows[:12]:
        score = f"{r['hg']}-{r['ag']}" if r["hg"] is not None else "v"
        print(f"  {r['date']}  {r['league'][:28]:<28} {r['home']} {score} {r['away']}")
    if not rows:
        print("ZERO rows -- markup changed or blocked; inspect the saved page in "
              "your cache dir and adjust RE_* patterns in providers.py", file=sys.stderr)


def cmd_report(args):
    prov = DemoProvider() if args.demo else _provider(args.demo)
    mkts = _markets(args.markets)
    picks = []
    for d in _date_range(args):
        try:
            picks += predict_day(prov, day=d, markets=mkts)
        except RuntimeError as e:
            print(f"report: no fixtures for {d} ({e})", file=sys.stderr)
    # renumber per market across the whole window (dates stay on each pick block)
    for mkt in mkts:
        group = [p for p in picks if p["market"] == mkt]
        for i, p in enumerate(group, 1):
            p["num"] = i
    if args.demo:
        sample_card = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "sample_data", "sample_card_2026-09-12.md")
        picks = st.cross_check(picks, st.parse_card(open(sample_card).read()))
    report = render_report(picks, day=args.date)
    print(report)
    if args.telegram:
        send_telegram(report)


def cmd_fetch_statarea(args):
    st.fetch_card(args.date)
    print("card cached")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="overunder", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--date", default=None)
        p.add_argument("--demo", action="store_true")
        p.add_argument("--telegram", action="store_true")

    p = sub.add_parser("demo"); common(p); p.add_argument("--out")
    p.add_argument("--markets", default="over,btts,home")
    p.set_defaults(fn=cmd_demo)
    p = sub.add_parser("predict"); common(p); p.add_argument("--odds", type=float, default=config.DEFAULT_ODDS)
    p.add_argument("--statarea", action="store_true"); p.add_argument("--card")
    p.add_argument("--markets", default="over", help="comma list: over,under,btts,no_btts,home,home_sc,away_sc")
    p.add_argument("--days", type=int, default=1, help="predict N days from --date (default today)")
    p.set_defaults(fn=cmd_predict)
    p = sub.add_parser("compare"); common(p); p.add_argument("--picks", required=True)
    p.add_argument("--card"); p.set_defaults(fn=cmd_compare)
    p = sub.add_parser("settle"); common(p); p.add_argument("--days", type=int, default=None)
    p.set_defaults(fn=cmd_settle)
    p = sub.add_parser("stats"); p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_stats)
    p = sub.add_parser("report"); common(p)
    p.add_argument("--markets", default="over,under,btts,no_btts,home,home_sc,away_sc")
    p.add_argument("--days", type=int, default=1)
    p.set_defaults(fn=cmd_report)
    p = sub.add_parser("scrape-check"); p.add_argument("--date", default=None)
    p.add_argument("--team", default=None, help="debug one team's page parse")
    p.set_defaults(fn=cmd_scrape_check)
    p = sub.add_parser("team-stats"); common(p); p.add_argument("team")
    p.set_defaults(fn=cmd_team_stats)
    p = sub.add_parser("recent"); p.add_argument("--n", type=int, default=25)
    p.set_defaults(fn=cmd_recent)
    p = sub.add_parser("retag"); p.add_argument("--date", default=None)
    p.add_argument("--card", default=None)
    p.set_defaults(fn=cmd_retag)
    p = sub.add_parser("backfill"); p.add_argument("--days", type=int, default=120)
    p.add_argument("--sleep", type=float, default=1.0, help="seconds between day fetches")
    p.set_defaults(fn=cmd_backfill)
    p = sub.add_parser("verify"); p.add_argument("--n", type=int, default=50)
    p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("backtest"); p.add_argument("--days", type=int, default=30)
    p.add_argument("--markets", default="over,under,btts,no_btts,home,home_sc,away_sc")
    p.add_argument("--odds", type=float, default=config.DEFAULT_ODDS)
    p.add_argument("--min-conf", type=float, default=config.O25_MIN_CONFIDENCE)
    p.add_argument("--verbose", action="store_true", help="print every replayed pick")
    p.add_argument("--audit", action="store_true", help="detect lookahead leaks")
    p.add_argument("--no-market-thresholds", action="store_true",
                   help="flat --min-conf for all markets (threshold analysis)")
    p.set_defaults(fn=cmd_backtest)
    p = sub.add_parser("fetch-statarea"); p.add_argument("--date", default=None)
    p.set_defaults(fn=cmd_fetch_statarea)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
