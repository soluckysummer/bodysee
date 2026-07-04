#!/bin/zsh
# 缩墙勇士（体感穿墙）启动脚本（可拖到桌面双击）
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
echo "  缩墙勇士 · 体感穿墙"
echo "  在墙到达前摆出洞的姿势！"
echo "  单人直接玩；两人同时入画自动双人对抗"
echo "  举手 1 秒开始 · Esc 退出 · P 暂停 · F 全屏"
echo "================================"
echo

"$PYTHON" -m wallgame "$@"

echo
echo "游戏已退出，按任意键关闭窗口"
read -k1
