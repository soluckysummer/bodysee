@echo off
chcp 65001 >nul
rem 神拳对决（双人体感格斗）Windows 启动脚本
rem 优先使用脚本所在目录；如果把本文件复制到了桌面，请把下面 FALLBACK 改成项目实际路径

set "PROJECT_DIR=%~dp0"
if not exist "%PROJECT_DIR%fightgame\game.py" set "PROJECT_DIR=%USERPROFILE%\works\bodyjk\"

set "PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo 找不到虚拟环境: %PYTHON%
    echo 请先在项目目录执行: py -3.11 -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo ================================
echo   神拳对决 · 双人体感格斗
echo   左边的人=青影  右边的人=赤焰
echo   双方同时举手 1 秒开始
echo   Esc 退出 · P 暂停 · F 全屏
echo ================================
echo.

cd /d "%PROJECT_DIR%"
"%PYTHON%" -m fightgame %*

echo.
pause
