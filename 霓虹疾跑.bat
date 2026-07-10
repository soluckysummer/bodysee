@echo off
chcp 65001 >nul
rem 霓虹疾跑（三轨全身体感跑酷）Windows 启动脚本

set "PROJECT_DIR=%~dp0"
if not exist "%PROJECT_DIR%runnergame\game.py" set "PROJECT_DIR=%USERPROFILE%\works\bodyjk\"

set "PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo 找不到虚拟环境: %PYTHON%
    echo 请先在项目目录执行: py -3.11 -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo ================================
echo   霓虹疾跑 · 三轨全身体感跑酷
echo   倾身换道 · 举手跳跃 · 下蹲滑行 · 挥手击碎
echo   双手举过头顶 1 秒开始
echo   Esc 返回 · P 暂停 · F 全屏
echo ================================
echo.

cd /d "%PROJECT_DIR%"
"%PYTHON%" -m runnergame %*

echo.
pause
