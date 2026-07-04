#!/bin/zsh
# 体感切水果 启动脚本（可拖到桌面双击）
PROJECT_DIR="/Users/ailin/works/bodyjk"

cd "$PROJECT_DIR" || { echo "找不到项目目录 $PROJECT_DIR"; read -k1; exit 1; }

PYTHON="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo "找不到虚拟环境: $PYTHON"
    echo "请先在项目目录执行: python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    read -k1
    exit 1
fi

echo "================================"
echo "  体感切水果"
echo "  站到摄像头前，快速挥手切西瓜"
echo "  Esc 退出 · P 暂停 · F 全屏"
echo "================================"
echo

"$PYTHON" -m fruitgame

echo
echo "游戏已退出，按任意键关闭窗口"
read -k1
