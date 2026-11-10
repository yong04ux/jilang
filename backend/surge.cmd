@echo off
rem Surge launcher for Windows (ASCII only; non-ASCII here breaks under GBK).
rem Usage from any directory:
rem   backend\surge.cmd
rem   backend\surge.cmd --port 8000
rem   backend\surge.cmd demo
setlocal
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

if exist "%ROOT%\.venv\Scripts\python.exe" (
  set "PY=%ROOT%\.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

set "PYTHONPATH=%ROOT%"
set "PYTHONIOENCODING=utf-8"

pushd "%ROOT%"
"%PY%" -m surge %*
set "RC=%ERRORLEVEL%"
popd

endlocal & exit /b %RC%
