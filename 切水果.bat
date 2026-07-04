@echo off
chcp 65001 >nul
rem 体感切水果 Windows 启动脚本
rem 优先使用脚本所在目录；如果把本文件复制到了桌面，请把下面 FALLBACK 改成项目实际路径

set "PROJECT_DIR=%~dp0"
if not exist "%PROJECT_DIR%fruitgame\game.py" set "PROJECT_DIR=%USERPROFILE%\works\bodyjk\"

set "PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo 找不到虚拟环境: %PYTHON%
    echo 请先在项目目录执行: py -3.11 -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo ================================
echo   体感切水果
echo   站到摄像头前，快速挥手切西瓜
echo   Esc 退出 · P 暂停 · F 全屏
echo ================================
echo.

cd /d "%PROJECT_DIR%"
"%PYTHON%" -m fruitgame

echo.
pause
