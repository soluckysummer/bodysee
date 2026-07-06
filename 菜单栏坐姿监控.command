#!/bin/zsh
# 坐姿提醒器 · 菜单栏版启动脚本（可拖到桌面，双击运行）
# 应用常驻在屏幕右上角菜单栏，本窗口启动完即可关闭。

PROJECT_DIR="/Users/ailin/works/bodyjk"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG="$PROJECT_DIR/menubar.log"

if [[ ! -x "$PYTHON" ]]; then
    echo "找不到虚拟环境: $PYTHON"
    echo "请确认项目位置没有变动，按任意键关闭..."
    read -k1
    exit 1
fi

# 日志超过 1MB 就截断，只保留最近 256KB
if [[ -f "$LOG" ]] && (( $(stat -f%z "$LOG") > 1048576 )); then
    tail -c 262144 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

if pgrep -f "$PROJECT_DIR/menubar.py" >/dev/null; then
    echo "菜单栏应用已经在运行了（看屏幕右上角图标）。"
    echo -n "要重启它吗？（更新代码后需要重启才生效）[y/N] "
    read -k1 answer
    echo
    if [[ "$answer" == [yY] ]]; then
        pkill -f "$PROJECT_DIR/menubar.py"
        sleep 1
    else
        exit 0
    fi
fi

nohup "$PYTHON" "$PROJECT_DIR/menubar.py" >> "$LOG" 2>&1 &
echo "已启动，看屏幕右上角菜单栏图标（🟢/🔴/⚪）。"
echo "日志: $LOG"
echo "本窗口可以直接关闭。"
sleep 3
