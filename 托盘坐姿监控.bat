@echo off
chcp 65001 >nul
rem 坐姿提醒器 Windows 启动脚本（系统托盘常驻版，无窗口）
rem 优先使用脚本所在目录；如果把本文件复制到了桌面，请把下面 FALLBACK 改成项目实际路径

set "PROJECT_DIR=%~dp0"
if not exist "%PROJECT_DIR%tray_win.py" set "PROJECT_DIR=%USERPROFILE%\works\bodyjk\"

set "PYTHONW=%PROJECT_DIR%.venv\Scripts\pythonw.exe"
if not exist "%PYTHONW%" (
    echo 找不到虚拟环境: %PYTHONW%
    echo 请先在项目目录执行: py -3.11 -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

rem 已在运行则不重复启动
tasklist /fi "imagename eq pythonw.exe" | find /i "pythonw.exe" >nul && (
    echo 托盘应用可能已在运行，请查看任务栏右下角图标。
    timeout /t 3 >nul
    exit /b 0
)

start "" "%PYTHONW%" "%PROJECT_DIR%tray_win.py"
echo 已启动，请看任务栏右下角托盘图标（绿=OK 红=坏姿势 灰=没人）。
timeout /t 3 >nul
