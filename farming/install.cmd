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
echo Install 64-bit Python 3.12 with Python Launcher first.
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
  echo Dependency installation failed. Retry install.cmd after checking network.
  pause
  exit /b 1
)
echo Installed. Open start.cmd to configure this PC and open the farming panel.
pause
