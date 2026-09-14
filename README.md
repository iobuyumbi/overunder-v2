# overunder-v2

Over/Under 2.5 prediction system rebuilt from scratch, with a Statarea consensus
cross-check and a full bet-settlement / ROI-tracking loop.

## Why v2

The original repo drifted beyond repair. This is a clean, small, testable core
that keeps the proven ideas and drops the 15k lines of accreted code:

- **over25tips.com ruleset** (H1/H2/A1-A4) — the exact public rule text, plus
  7 supporting checks, rendered as `Profile: N/13 checks passed`
- **Poisson goals model** for a defensible base probability
- **EV + fractional-Kelly staking** (matches your old stake curve)
- **Statarea cross-check** — verified parser, name aliasing, AGREE/DIVERGE tags
- **Settlement + ROI per signal** so the 70/40/55 thresholds prove themselves
- **VIP-style report** identical in shape to your channel format
- **Offline demo** — the whole cycle runs with zero network

## Install

```bash
unzip overunder-v2.zip && cd overunder-v2
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Prove it works (offline)

```bash
python -m overunder demo          # predict -> cross-check -> report -> settle -> stats
python -m unittest discover -s tests -v
```

## Daily workflow

```bash
python -m overunder fetch-statarea          # cache today's card (needs network)
python -m overunder predict --statarea      # your picks + statarea tags, recorded to history
python -m overunder report                  # VIP-style report (add --telegram to send)
python -m overunder settle                  # after results are known
python -m overunder stats                   # ROI overall / by statarea signal / by tier
```

## Wiring real data

`overunder/providers.py` has the interface. `DemoProvider` runs offline;
`SoccerbaseProvider` has production fetch plumbing (retry/backoff/cache) with
the page-specific parsing marked `NotImplementedError` — implement
`_parse_fixtures` / `_parse_results` / team pages against live soccerbase
markup, or adapt your old scraper into the same three methods. Nothing else
in the codebase changes.

## Running locally

See `SCHEDULE.local.md` — `run_local.bat` (Windows) and `run_daily.sh` (Linux/mac) run the whole pipeline, and your home IP avoids the datacenter blocks that break `fetch-statarea` on GitHub Actions.

## Config

Everything lives in `overunder/config.py` and can be overridden by env vars
(copy `.env.example`). Key knobs: `ST_OVER_MIN` (70), `ST_UNDER_MAX` (40),
`ST_HOME_MIN` (55), `O25_MIN_CONFIDENCE`, `DEFAULT_ODDS`, `KELLY_FRACTION`.

## Push to your new repo

```bash
git init
git add .
git commit -m "overunder v2: clean core + statarea cross-check"
git remote add origin git@github.com:iobuyumbi/overunder-v2.git
git push -u origin main
```

## Honest limitations

- Statarea scraping is inherently brittle; the 30-game validation gate and
  raw dumps tell you the day it breaks instead of silently misfiltering.
- The real soccerbase adapter is a skeleton until implemented against live
  markup.
- Thresholds are starting values. `stats` after ~100 settled picks is the
  arbiter — promote `AGREE_*` to a hard gate only if the data says so.
