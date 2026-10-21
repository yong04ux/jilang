@echo off
rem CrossPilot launcher for Windows (ASCII only; non-ASCII here breaks under GBK).
rem Usage from any directory:
rem   D:\my-project\CrossPilot\backend\crosspilot.cmd
rem   D:\my-project\CrossPilot\backend\crosspilot.cmd --port 8000
rem   D:\my-project\CrossPilot\backend\crosspilot.cmd demo
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
"%PY%" -m crosspilot %*
set "RC=%ERRORLEVEL%"
popd

endlocal & exit /b %RC%
