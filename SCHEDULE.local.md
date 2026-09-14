# Running locally on a schedule

## Why local beats Actions for this project
`fetch-statarea` hits statarea.com directly, which blocks most datacenter IPs
(GitHub Actions included). Your home IP almost always works. Recommended split:

- **Local machine**: run the full daily pipeline below (fetch + predict + report).
- **GitHub Actions**: optional -- keep it for `settle` + `stats` + artifact
  backups of `data/`, or drop CI entirely; everything works on one machine.

## Windows — Task Scheduler
1. `run_local.bat` once by hand to create the venv and verify.
2. Task Scheduler -> Create Task -> Trigger: daily 09:00 ->
   Action: Start a program -> `C:\path\to\overunder-v2\run_local.bat`
   -> "Start in": `C:\path\to\overunder-v2`
3. Optional Telegram: put TELEGRAM_TOKEN / TELEGRAM_CHAT_ID in a `.env`-style
   setx command or set them as Task Scheduler environment variables, and add
   `--telegram` to the report line in run_local.bat.

## Linux / macOS — cron
    crontab -e
    # daily at 09:00, log to file:
    0 9 * * *  cd /path/to/overunder-v2 && ./run_daily.sh >> daily.log 2>&1

## Where data lives (all local, all yours)
- `data/prediction_history.json` -- every pick + settlement (commit this to git
  if you want history backed up; it's gitignored by default, remove the line to track it)
- `~/.cache/overunder/` -- fetched statarea cards (6-12h TTL) and soccerbase pages

## Working offline / on a laptop
Everything except `fetch-statarea` uses the cache or demo data, so planes and
cafes are fine. If a fetch fails on your IP too, save the statarea page from a
browser and run:
    python -m overunder predict --card saved_page.html --statarea
