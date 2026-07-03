@echo off
chcp 65001 >nul
rem 坐姿提醒器 Windows 启动脚本（终端版，窗口显示状态日志）
rem 优先使用脚本所在目录；如果把本文件复制到了桌面，请把下面 FALLBACK 改成项目实际路径

set "PROJECT_DIR=%~dp0"
if not exist "%PROJECT_DIR%main.py" set "PROJECT_DIR=%USERPROFILE%\works\bodyjk\"

set "PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo 找不到虚拟环境: %PYTHON%
    echo 请先在项目目录执行: py -3.11 -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo ================================
echo   坐姿提醒器
echo   停止: 在本窗口按 Ctrl+C，或直接关闭窗口
echo ================================
echo.

"%PYTHON%" "%PROJECT_DIR%main.py"

echo.
pause
