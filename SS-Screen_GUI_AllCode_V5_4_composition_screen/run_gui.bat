@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [SS-Screen] Creating Python virtual environment...
  py -m venv .venv
  if errorlevel 1 goto :error
)

echo [SS-Screen] Installing/updating GUI dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements-gui.txt
if errorlevel 1 goto :error

echo [SS-Screen] Starting GUI...
".venv\Scripts\python.exe" run_gui_preview.py
goto :eof

:error
echo.
echo Failed to start SS-Screen GUI.
pause
exit /b 1
