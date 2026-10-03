@echo off
REM =====================================================================
REM  overunder-v2: commit + push pending changes.
REM  Run this ONCE after confirming `git status` is what you want.
REM  Usage:  git_commit_push.bat  "your commit message here"
REM =====================================================================
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo USAGE:  %~nx0  "commit message"
  echo e.g.:   %~nx0  "Fix .env OU_FREQ typo; rewrite daily.yml with full 4-job GHA pipeline"
  exit /b 1
)

echo.
echo ==== STATUS BEFORE ====
git status --short

echo.
echo ==== ADDING: .github/workflows/daily.yml ====
git add .github/workflows/daily.yml || exit /b 1
echo ==== ADDING: .github/workflows/ci.yml ====
git add .github/workflows/ci.yml || exit /b 1
echo ==== ADDING: actions-runner-bootstrap.ps1 ====
git add actions-runner-bootstrap.ps1 || exit /b 1

git status --short
echo.
echo ==== COMMIT ====
git commit -m "%~1" || exit /b 1

echo.
echo ==== PUSH origin main ====
git push origin main || exit /b 1

echo.
echo ==== DONE ====
echo Latest commit:
git log --oneline -1
endlocal
pause
