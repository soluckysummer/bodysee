#!/bin/zsh
# 坐姿提醒器 · 菜单栏版启动脚本（双击运行）
# 应用常驻在屏幕右上角菜单栏，本窗口启动完即可关闭。
# 默认自动使用"脚本所在目录"作为项目目录，clone 到哪里都能直接用。
# 只有当你把本文件复制/移动到了项目文件夹之外（比如复制到桌面）时，
# 才需要把下面引号里填上项目实际路径，例如：PROJECT_DIR="$HOME/works/bodyjk"
# （推荐做法是不复制文件，而是右键本文件 →"制作替身"，把替身拖到桌面）
PROJECT_DIR=""

[[ -z "$PROJECT_DIR" ]] && PROJECT_DIR="${0:A:h}"

if [[ ! -f "$PROJECT_DIR/menubar.py" ]]; then
    echo "在 $PROJECT_DIR 里找不到项目文件（menubar.py）。"
    echo "请把本脚本放回项目文件夹，或编辑本文件顶部的 PROJECT_DIR 填入项目路径。"
    read -k1
    exit 1
fi

PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG="$PROJECT_DIR/menubar.log"

if [[ ! -x "$PYTHON" ]]; then
    echo "找不到虚拟环境: $PYTHON"
    echo "请先在项目目录执行: python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt"
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
