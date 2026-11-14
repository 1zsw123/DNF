@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" goto run
where py >nul 2>&1
if not errorlevel 1 goto deps
set "PYINSTALLER=%USERPROFILE%\Downloads\python-3.12.10-amd64.exe"
if not exist "%PYINSTALLER%" goto nopython
echo 未检测到 Python，正在安装 Python 3.12（约 1-2 分钟）。
echo 如弹出“是否允许此应用更改设备”，请点“是”。
start "" /wait "%PYINSTALLER%" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=1 Include_test=0
where py >nul 2>&1
if errorlevel 1 goto reopen
:deps
echo 首次运行：正在安装依赖（需要联网，约几分钟），请勿关闭此窗口……
call install.cmd
if not exist ".venv\Scripts\pythonw.exe" goto failed
:run
call start.cmd
exit /b 0
:nopython
echo 未检测到 Python。请先安装 64 位 Python 3.12：
echo https://www.python.org/downloads/windows/
pause
exit /b 1
:reopen
echo Python 已安装，请关闭此窗口，再双击一次桌面上的“DNF刷图助手”。
pause
exit /b 1
:failed
echo 依赖安装失败，请把这个窗口的内容截图发给我。
pause
exit /b 1
