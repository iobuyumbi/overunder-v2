@echo off
REM overunder v2 - local daily runner (Windows)
REM Usage:  run_local.bat            (full pipeline, statarea optional)
REM         run_local.bat demo      (offline self-test)
REM         run_local.bat real      (same but with the live soccerbase scraper)
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)
if "%~1"=="demo" (
    echo ===== DEMO =====
    python -m overunder demo
) else (
    echo ===== FETCH STATAREA (best-effort) =====
    python -m overunder fetch-statarea
    if "%~1"=="real" (
        echo ===== SCRAPE CHECK =====
        python -m overunder scrape-check
    )
    echo ===== PREDICT =====
    python -m overunder predict --statarea --markets over,btts,home
    echo ===== REPORT =====
    python -m overunder report --markets over,btts,home
    echo ===== SETTLE =====
    python -m overunder settle
    echo ===== STATS =====
    python -m overunder stats
)
echo ===== DONE (any errors are above) =====
pause
