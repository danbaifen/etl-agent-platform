@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0backend"
if errorlevel 1 goto no_dir

rem prefer project venv (inherits installed deps), fallback to system python
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe

"%PY%" -c "import pydantic_settings, fastapi, sqlalchemy" >nul 2>&1
if errorlevel 1 goto no_deps

if not exist "var\platform.db" (
  echo [info] database not found, initializing...
  "%PY%" -m alembic upgrade head
  "%PY%" -m app.scripts.seed_demo --data-dir ./var/demo
)

echo.
echo [info] python   : %PY%
echo [info] backend  : http://127.0.0.1:8010
echo [info] api docs : http://127.0.0.1:8010/docs
echo [info] login    : local:zhanglan / DemoPass!2026
echo.
echo [info] starting uvicorn, keep this window open...
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8010
goto done

:no_dir
echo [error] cannot enter directory: %~dp0backend
goto done

:no_deps
echo [error] selected python is missing required packages: %PY%
echo [error] expected venv at backend\.venv\Scripts\python.exe
echo [error] create it once with:
echo [error]   python -m venv .venv --system-site-packages

:done
echo.
echo [info] server stopped. press any key to close.
pause >nul
