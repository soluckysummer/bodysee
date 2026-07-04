#!/bin/zsh
# 神拳对决（双人体感格斗）启动脚本（可拖到桌面双击）
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
echo "  神拳对决 · 双人体感格斗"
echo "  左边的人=青影  右边的人=赤焰"
echo "  双方同时举手 1 秒开始"
echo "  Esc 退出 · P 暂停 · F 全屏"
echo "  （单人练习: --solo  演示: --demo）"
echo "================================"
echo

"$PYTHON" -m fightgame "$@"

echo
echo "游戏已退出，按任意键关闭窗口"
read -k1
