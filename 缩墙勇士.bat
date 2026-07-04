@echo off
chcp 65001 >nul
rem 缩墙勇士（体感穿墙）Windows 启动脚本
rem 优先使用脚本所在目录；如果把本文件复制到了桌面，请把下面 FALLBACK 改成项目实际路径

set "PROJECT_DIR=%~dp0"
if not exist "%PROJECT_DIR%wallgame\game.py" set "PROJECT_DIR=%USERPROFILE%\works\bodyjk\"

set "PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo 找不到虚拟环境: %PYTHON%
    echo 请先在项目目录执行: py -3.11 -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo ================================
echo   缩墙勇士 · 体感穿墙
echo   在墙到达前摆出洞的姿势！
echo   举手 1 秒开始 · Esc 退出 · P 暂停 · F 全屏
echo ================================
echo.

cd /d "%PROJECT_DIR%"
"%PYTHON%" -m wallgame %*

echo.
pause
