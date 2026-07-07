#!/bin/zsh
# 坐姿提醒器快捷启动脚本（双击运行）
# 默认自动使用"脚本所在目录"作为项目目录，clone 到哪里都能直接用。
# 只有当你把本文件复制/移动到了项目文件夹之外（比如复制到桌面）时，
# 才需要把下面引号里填上项目实际路径，例如：PROJECT_DIR="$HOME/works/bodyjk"
# （推荐做法是不复制文件，而是右键本文件 →"制作替身"，把替身拖到桌面）
PROJECT_DIR=""

[[ -z "$PROJECT_DIR" ]] && PROJECT_DIR="${0:A:h}"

if [[ ! -f "$PROJECT_DIR/main.py" ]]; then
    echo "在 $PROJECT_DIR 里找不到项目文件（main.py）。"
    echo "请把本脚本放回项目文件夹，或编辑本文件顶部的 PROJECT_DIR 填入项目路径。"
    read -k1
    exit 1
fi

PYTHON="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo "找不到虚拟环境: $PYTHON"
    echo "请先在项目目录执行: python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    read -k1
    exit 1
fi

cd "$PROJECT_DIR"

echo "================================"
echo "  坐姿提醒器"
echo "  停止: 在本窗口按 Ctrl+C，或直接关闭窗口"
echo "================================"
echo

"$PYTHON" main.py

echo
echo "监控已退出，按任意键关闭窗口..."
read -k1
