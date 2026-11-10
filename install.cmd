@echo off
setlocal
cd /d "%~dp0"
py -3.12 -c "import sys; assert sys.maxsize > 2**32" >nul 2>&1
if not errorlevel 1 (
  py -3.12 -m venv .venv
  goto dependencies
)
py -3.11 -c "import sys; assert sys.maxsize > 2**32" >nul 2>&1
if not errorlevel 1 (
  py -3.11 -m venv .venv
  goto dependencies
)
echo Install 64-bit Python 3.12 with the Python Launcher first.
echo https://www.python.org/downloads/windows/
pause
exit /b 1
:dependencies
if not exist ".venv\Scripts\python.exe" (
  echo Failed to create Python environment.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed. Check network and retry install.cmd.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m unittest test_follow test_yolo test_name_rescue test_dungeon_telemetry test_coordinate_connection test_portable_follow
if errorlevel 1 (
  echo Self-check failed. Send this output to Codex.
  pause
  exit /b 1
)
echo Installation complete. Run start.cmd next.
pause
