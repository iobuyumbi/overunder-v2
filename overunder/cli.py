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
    try:
        return SoccerbaseProvider()
    except Exception as e:
        sys.exit(f"real provider unavailable ({e}). Use --demo or implement "
                 f"SoccerbaseProvider parsing.")


def cmd_demo(args):
    prov = DemoProvider()
    picks = predict_day(prov, day=args.date)
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
    picks = predict_day(prov, day=args.date, odds=args.odds)
    if args.statarea or args.demo:
        text = st.load_card(args.date) if not args.card else st.load_card_file(args.card)
        picks = st.cross_check(picks, st.parse_card(text))
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
    n = hist.settle(prov.results(args.date))
    print(f"settled {n} picks")


def cmd_stats(args):
    print(json.dumps(hist.stats(), indent=2))


def cmd_report(args):
    prov = DemoProvider() if args.demo else _provider(args.demo)
    picks = predict_day(prov, day=args.date)
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

    p = sub.add_parser("demo"); common(p); p.add_argument("--out"); p.set_defaults(fn=cmd_demo)
    p = sub.add_parser("predict"); common(p); p.add_argument("--odds", type=float, default=config.DEFAULT_ODDS)
    p.add_argument("--statarea", action="store_true"); p.add_argument("--card")
    p.set_defaults(fn=cmd_predict)
    p = sub.add_parser("compare"); common(p); p.add_argument("--picks", required=True)
    p.add_argument("--card"); p.set_defaults(fn=cmd_compare)
    p = sub.add_parser("settle"); common(p); p.set_defaults(fn=cmd_settle)
    p = sub.add_parser("stats"); p.set_defaults(fn=cmd_stats)
    p = sub.add_parser("report"); common(p); p.set_defaults(fn=cmd_report)
    p = sub.add_parser("fetch-statarea"); p.add_argument("--date", default=None)
    p.set_defaults(fn=cmd_fetch_statarea)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
