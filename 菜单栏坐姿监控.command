#!/bin/zsh
# 坐姿提醒器 · 菜单栏版启动脚本（可拖到桌面，双击运行）
# 应用常驻在屏幕右上角菜单栏，本窗口启动完即可关闭。

PROJECT_DIR="/Users/ailin/works/bodyjk"
PYTHON="$PROJECT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    echo "找不到虚拟环境: $PYTHON"
    echo "请确认项目位置没有变动，按任意键关闭..."
    read -k1
    exit 1
fi

if pgrep -f "$PROJECT_DIR/menubar.py" >/dev/null; then
    echo "菜单栏应用已经在运行了（看屏幕右上角图标）。"
    sleep 3
    exit 0
fi

nohup "$PYTHON" "$PROJECT_DIR/menubar.py" >> "$PROJECT_DIR/menubar.log" 2>&1 &
echo "已启动，看屏幕右上角菜单栏图标（🟢/🔴/⚪）。"
echo "日志: $PROJECT_DIR/menubar.log"
echo "本窗口可以直接关闭。"
sleep 3
