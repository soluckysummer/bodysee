#!/bin/zsh
# 坐姿提醒器快捷启动脚本
# 双击运行（可拖到桌面）。项目路径写死为绝对路径，不依赖脚本所在位置。

PROJECT_DIR="/Users/ailin/works/bodyjk"
PYTHON="$PROJECT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    echo "找不到虚拟环境: $PYTHON"
    echo "请确认项目位置没有变动，按任意键关闭..."
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
