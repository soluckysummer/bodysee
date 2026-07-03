"""系统提醒：弹窗 + 提示音 + 通知横幅，全部非阻塞。

按平台分支实现，对外接口一致：
    notify(title, message, sound=..., timeout_sec=...)  # 明显的弹窗 + 声音
    toast(title, message)                               # 轻量提示（校准完成等）
"""

import subprocess
import sys
import threading

if sys.platform == "win32":
    import ctypes
    import winsound

    # MessageBox 样式
    _MB_ICONWARNING = 0x30
    _MB_ICONINFO = 0x40
    _MB_TOPMOST = 0x40000
    _MB_SETFOREGROUND = 0x10000

    def _msgbox(title, message, flags, timeout_sec):
        """MessageBoxTimeoutW: 带超时自动关闭的系统弹窗（user32 未公开但自 XP
        起一直稳定存在）。在线程里调用避免阻塞监控循环。"""
        def run():
            ctypes.windll.user32.MessageBoxTimeoutW(
                None, ctypes.c_wchar_p(message), ctypes.c_wchar_p(title),
                flags, 0, int(timeout_sec * 1000))
        threading.Thread(target=run, daemon=True).start()

    def notify(title, message, sound="Sosumi", timeout_sec=25):
        # sound 参数沿用 mac 的音色名: "Glass"(久坐,轻) 之外都当警示音
        alias = "SystemAsterisk" if sound == "Glass" else "SystemExclamation"
        winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
        _msgbox(title, message,
                _MB_ICONWARNING | _MB_TOPMOST | _MB_SETFOREGROUND, timeout_sec)

    def toast(title, message):
        _msgbox(title, message, _MB_ICONINFO | _MB_TOPMOST, 8)

else:
    # macOS
    SOUND_DIR = "/System/Library/Sounds"

    def _osascript_quote(text):
        return text.replace("\\", "\\\\").replace('"', '\\"')

    def notify(title, message, sound="Sosumi", timeout_sec=25):
        """弹出系统对话框并播放提示音。对话框置顶显示，超时自动消失。"""
        subprocess.Popen(
            ["afplay", f"{SOUND_DIR}/{sound}.aiff"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        script = (
            f'display dialog "{_osascript_quote(message)}" '
            f'with title "{_osascript_quote(title)}" '
            f'buttons {{"知道了"}} default button 1 with icon caution '
            f"giving up after {timeout_sec}"
        )
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def toast(title, message):
        """右上角系统通知横幅（不打断操作），用于校准完成之类的轻量提示。"""
        script = (f'display notification "{_osascript_quote(message)}" '
                  f'with title "{_osascript_quote(title)}"')
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
