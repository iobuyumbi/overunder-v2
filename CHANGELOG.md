# CHANGELOG

All notable changes to overunder-v2, tracked so the git history tells the
same story this file does. Suggested commit for each entry shown as message.

## [2.0.0] - 2026-09-14 - Initial public version
    feat: overunder v2 — clean rebuild: 17-check rules engine (venue+overall
    form), Poisson markets (over/btts/home/home_sc/away_sc), EV/Kelly staking,
    statarea consensus cross-check, soccerbase scraper, settlement, ROI stats,
    VIP report, backfill, no-lookahead backtest, verify audit (27 tests)

### Session fixes rolled into 2.0.0 (chronological)

- fix(statarea): parse new double-block card layout (TIP labels, datetimes,
  column headers, markdown links); skip header tokens by name before int
  parse -- stats no longer shift (regression test from live bug report)
- fix(statarea): html.unescape team names (Wingate &amp; F); per-line link
  flattening so greedy regex cannot span lines
- fix(history): empty/corrupt prediction_history.json quarantined, not fatal
- feat(providers): real SoccerbaseProvider (results.sd?date=, team pages,
  team_id cache, search fallback); scrape-check + --team debug
- fix(providers): tolerant score extraction (&nbsp;, nested spans, HT scores);
  memoize team_matches per run
- feat(predict): BTTS + home win + home/away team-to-score markets; real
  lambdas for xG on all markets; per-team goals line in report
- feat(rules): 17 checks — every signal in venue-specific AND overall form;
  early-season rate fallback for H1/A1; S6 threshold 4
- feat(cli): backfill (N-day results DB), verify (score audit + parser sanity),
  backtest (point-in-time, auto-settling, never touches history),
  predict/report --days, settle auto-scans pending dates, txt stats
- feat(docs): README, .env autoload, hardened .gitignore, run_local.bat,
  GitHub Actions workflow, 27-test suite
