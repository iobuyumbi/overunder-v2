# overunder-v2

Over/Under 2.5, BTTS, home-win and team-to-score prediction system with a
Statarea consensus cross-check, soccerbase scraping, result settlement,
ROI tracking, and no-lookahead backtesting.

Successor to iobuyumbi/over-under, rebuilt from scratch: one tested engine
(~2,000 lines, 27 unit tests) instead of 15k lines of drifted code.

## Install

    unzip overunder-v2.zip && cd overunder-v2
    python -m venv .venv && .venv\Scripts\activate      (Windows)
    pip install -r requirements.txt

## Prove it works (offline, no network)

    python -m overunder demo
    python -m unittest discover -s tests -v              (expect 27+ pass)

## First live setup (one time)

    python -m overunder scrape-check --date 2026-09-14   (confirm soccerbase parse works)
    python -m overunder backfill --days 120              (history DB for deep form + backtests)

## Daily workflow

    python -m overunder fetch-statarea                   (optional; tags only, never blocks)
    python -m overunder predict --statarea --markets over,btts,home,home_sc,away_sc
    python -m overunder report                           (VIP-style txt; add --telegram to send)
    python -m overunder settle                           (auto-scans every pending pick's date)
    python -m overunder verify                           (audits recorded scores vs scrape)
    python -m overunder stats                            (ROI by market / tier / statarea signal)

Or just:  run_local.bat   (Windows, does all of the above; `run_local.bat demo` offline)

## Multi-day and backtesting

    python -m overunder predict --days 4                 (today + 3 days ahead, all recorded)
    python -m overunder report --days 4
    python -m overunder backtest --days 60 --markets over,btts,home
        (replays the past N days: picks as-of each morning, settled vs real
         results, no lookahead; never writes to prediction history)

## Commands reference

    demo            offline end-to-end self-test
    predict         build picks for a day/range of days (--date, --days, --markets,
                    --odds, --statarea, --card, --demo)
    report          VIP-style txt report (--days, --markets, --telegram)
    settle          settle pending picks (no args = scan all pending dates)
    stats           readable ROI tables (--json for machines)
    fetch-statarea  cache today's statarea card (best-effort)
    compare         cross-check an external picks file vs the statarea card
    scrape-check    verify soccerbase scraping (--date, or --team to debug one team)
    backfill        scrape N days of results into data\history_db.json
    backtest        no-lookahead historical replay + hypothetical results
    verify          audit settled picks vs fresh scrape; parser sanity report

## Data sources & honesty notes

- soccerbase.com `results.sd?date=` serves both fixtures and results for a
  day; team pages (`team_id`) give recent form; team IDs are cached in
  ~/.cache/overunder/team_ids.json.
- Statarea tags are AGREE/DIVERGE/NOT_FOUND at 70/40/55 thresholds
  (env: ST_OVER_MIN, ST_UNDER_MAX, ST_HOME_MIN). They are advisory until
  `stats` proves their value on settled picks.
- Backtests are honest (point-in-time `before` filtering, enforced in code
  and covered by a regression test) but assume flat odds -- stress with
  --odds 1.9.
- Postponed matches may show as MISSING in verify; that is flagged, never
  silently wrong.
- Never delete prediction_history.json mid-run; if a clean slate is needed,
  rename it (corrupt/empty files are auto-quarantined, not fatal).

## Layout

    overunder/            the package (cli, rules, predict, providers,
                          statarea, history, report, notify, config, teams)
    tests/                unittest suite (27+ tests)
    sample_data/          bundled statarea card + demo fixtures/results
    data/                 YOUR data: prediction_history.json, history_db.json
                          (gitignored; back it up yourself)

## License / usage

Personal use. Betting involves risk; the backtest exists so you can measure
the model before staking real money.
