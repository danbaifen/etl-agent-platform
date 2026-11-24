@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0frontend"
if errorlevel 1 goto no_dir

echo.
echo [info] frontend : http://localhost:5173
echo [info] backend  : http://127.0.0.1:8010  (start it first)
echo.
echo [info] starting vite, keep this window open...
call npx vite --port 5173
goto done

:no_dir
echo [error] cannot enter directory: %~dp0frontend

:done
echo.
echo [info] dev server stopped. press any key to close.
pause >nul
