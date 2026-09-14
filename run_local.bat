@echo off
REM overunder v2 - local daily runner (Windows)
REM Usage:  run_local.bat           (runs the full pipeline)
REM         run_local.bat demo      (offline self-test)
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)
if "%~1"=="demo" (
    python -m overunder demo
) else (
    python -m overunder fetch-statarea
    python -m overunder predict --statarea
    python -m overunder report
    python -m overunder settle
    python -m overunder stats
)
