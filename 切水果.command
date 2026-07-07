#!/bin/zsh
# 体感切水果 启动脚本（双击运行）
# 默认自动使用"脚本所在目录"作为项目目录，clone 到哪里都能直接用。
# 只有当你把本文件复制/移动到了项目文件夹之外（比如复制到桌面）时，
# 才需要把下面引号里填上项目实际路径，例如：PROJECT_DIR="$HOME/works/bodyjk"
# （推荐做法是不复制文件，而是右键本文件 →"制作替身"，把替身拖到桌面）
PROJECT_DIR=""

[[ -z "$PROJECT_DIR" ]] && PROJECT_DIR="${0:A:h}"

if [[ ! -f "$PROJECT_DIR/fruitgame/game.py" ]]; then
    echo "在 $PROJECT_DIR 里找不到项目文件（fruitgame/game.py）。"
    echo "请把本脚本放回项目文件夹，或编辑本文件顶部的 PROJECT_DIR 填入项目路径。"
    read -k1
    exit 1
fi

cd "$PROJECT_DIR"

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
