@echo off
chcp 65001 >nul
rem 体感切水果 Windows 启动脚本
rem 默认自动使用"脚本所在目录"作为项目目录，clone 到哪里都能直接用。
rem 只有当你把本文件复制到了项目文件夹之外（比如桌面）时，才需要在下面引号内
rem 填上项目实际路径，例如 set "PROJECT_DIR_OVERRIDE=C:\Users\你的用户名\works\bodyjk"
rem （推荐做法是不复制文件，而是右键本文件 → 发送到 → 桌面快捷方式）
set "PROJECT_DIR_OVERRIDE="

set "PROJECT_DIR=%~dp0"
if not exist "%PROJECT_DIR%fruitgame\game.py" set "PROJECT_DIR=%PROJECT_DIR_OVERRIDE%\"
if not exist "%PROJECT_DIR%fruitgame\game.py" (
    echo 找不到项目文件 fruitgame\game.py
    echo 请把本脚本放回项目文件夹，或编辑本文件顶部的 PROJECT_DIR_OVERRIDE 填入项目路径。
    pause
    exit /b 1
)

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
