"""系统提醒：通知横幅 + 提示音，全部非阻塞。

按平台分支实现，对外接口一致：
    notify(title, message, sound=..., timeout_sec=...)  # 通知横幅 + 声音
    toast(title, message)                               # 轻量提示（校准完成等）

macOS 上两者都是右上角系统通知，几秒后自动消失、不抢焦点，
区别只是 notify 带提示音。Windows 上 notify 仍是超时自动关闭的弹窗。
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

    def _banner(title, message):
        """右上角系统通知横幅，几秒后自动消失，不抢焦点。

        消息第一行作为通知副标题，其余作为正文，卡片上层次更清楚。
        """
        first, _, rest = message.partition("\n")
        script = (f'display notification "{_osascript_quote(rest or first)}" '
                  f'with title "{_osascript_quote(title)}"')
        if rest:
            script += f' subtitle "{_osascript_quote(first)}"'
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def notify(title, message, sound="Sosumi", timeout_sec=25):
        """通知横幅 + 提示音。timeout_sec 在 macOS 上由系统控制展示时长，忽略。"""
        subprocess.Popen(
            ["afplay", f"{SOUND_DIR}/{sound}.aiff"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _banner(title, message)

    def toast(title, message):
        """轻量提示（校准完成等），同为通知横幅，只是不带声音。"""
        _banner(title, message)
