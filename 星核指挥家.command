#!/bin/zsh
# 星核指挥家（全身体感节奏游戏）启动脚本（可拖到桌面双击）
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
echo "  星核指挥家 · 全身体感节奏"
echo "  挥动双手、下蹲、展开身体，演奏星河"
echo "  双手举过头顶 1 秒开始"
echo "  Esc 返回 · P 暂停 · F 全屏"
echo "  （键盘调试: --debug  低动态: --reduced-motion）"
echo "================================"
echo

"$PYTHON" -m stargame "$@"

echo
echo "游戏已退出，按任意键关闭窗口"
read -k1
