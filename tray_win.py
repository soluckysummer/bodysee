"""坐姿提醒器 · Windows 系统托盘常驻版（macOS 请用 menubar.py）。

托盘图标颜色实时反映状态：
    绿 = 坐姿 OK   红 = 坏姿势   灰 = 画面里没人
    黄 = 已暂停    紫 = 校准中   橙 = 出错
鼠标悬停图标可看详细状态（角度/在座时长）；右键菜单可暂停、重新校准、退出。

启动: .venv\\Scripts\\pythonw.exe tray_win.py   （或双击 托盘坐姿监控.bat）
"""

import threading
import time

import pystray
from PIL import Image, ImageDraw

from alerts import toast
from config import load_config, save_config
from monitor_core import PostureMonitor, run_calibration

COLORS = {
    "ok": (46, 204, 64),
    "bad": (255, 65, 54),
    "away": (170, 170, 170),
    "paused": (255, 200, 0),
    "calibrating": (160, 90, 255),
    "error": (255, 133, 27),
    "init": (90, 150, 255),
}


def make_icon(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return img


class TrayApp:
    def __init__(self):
        self.config = load_config()
        self.paused = False
        self.calibrating = False
        self.error = None
        self.monitor = None
        self._stop = threading.Event()
        self._camera_lock = threading.Lock()

        menu = pystray.Menu(
            pystray.MenuItem(lambda item: self._status_text(), None, enabled=False),
            pystray.MenuItem(lambda item: self._sit_text(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: "继续监控" if self.paused else "暂停监控",
                             self.toggle_pause),
            pystray.MenuItem("重新校准（先坐正，采集 10 秒）", self.recalibrate),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self.quit),
        )
        self.icon = pystray.Icon("posture", make_icon(COLORS["init"]),
                                 "坐姿提醒器 · 启动中...", menu)

    # ---------------------------------------------------------- 状态文字

    def _status_text(self):
        if self.error:
            return f"状态: {self.error}"
        if self.calibrating:
            return "状态: 校准中，请坐正..."
        if self.paused:
            return "状态: 已暂停"
        if not self.monitor or self.monitor.status["updated"] == 0:
            return "状态: 启动中..."
        st = self.monitor.status
        if not st["present"]:
            return "状态: 画面中没有人"
        text = ("状态: ⚠ " + "+".join(st["bad"])) if st["bad"] else "状态: 坐姿 OK"
        angles = f"颈部 {st['neck']:.1f}°/{self.monitor.neck_limit:.1f}°"
        if st["torso"] is not None and self.monitor.torso_limit is not None:
            angles += f" 躯干 {st['torso']:.1f}°/{self.monitor.torso_limit:.1f}°"
        return f"{text}（{angles}）"

    def _sit_text(self):
        if self.monitor and self.monitor.status["present"]:
            return (f"在座: {self.monitor.status['sit_min']:.0f} 分钟"
                    f" / 上限 {self.config['sit_limit_min']} 分钟")
        return "在座: --"

    def _state_key(self):
        if self.error:
            return "error"
        if self.calibrating:
            return "calibrating"
        if self.paused:
            return "paused"
        if not self.monitor or self.monitor.status["updated"] == 0:
            return "init"
        if not self.monitor.status["present"]:
            return "away"
        return "bad" if self.monitor.status["bad"] else "ok"

    # ---------------------------------------------------------- 后台线程

    def _worker(self):
        try:
            self.monitor = PostureMonitor(self.config)
            self.monitor.open()
        except RuntimeError as e:
            self.error = str(e)
            return
        while not self._stop.is_set():
            if self.paused or self.calibrating:
                self._stop.wait(0.5)
                continue
            try:
                with self._camera_lock:
                    self.monitor.step()
            except Exception as e:  # 摄像头被占用等异常不让线程死掉
                self.error = f"检测出错: {e}"
                self._stop.wait(10)
                self.error = None
                continue
            self._stop.wait(self.monitor.interval)

    def _refresher(self):
        while not self._stop.is_set():
            self.icon.icon = make_icon(COLORS[self._state_key()])
            self.icon.title = "坐姿提醒器 · " + self._status_text().removeprefix("状态: ")
            self.icon.update_menu()
            self._stop.wait(2)

    # ---------------------------------------------------------- 菜单动作

    def toggle_pause(self, _icon, _item):
        self.paused = not self.paused

    def recalibrate(self, _icon, _item):
        if self.calibrating or not self.monitor or self.error:
            return

        def do_calibrate():
            self.calibrating = True
            try:
                toast("坐姿提醒器", "开始校准：请坐正保持 10 秒（收下巴、背挺直）")
                time.sleep(2)  # 给用户一点摆正姿势的时间
                with self._camera_lock:
                    baseline = run_calibration(self.monitor.cap, self.monitor.analyzer,
                                               self.config, log=lambda m: None)
                if baseline is None:
                    toast("坐姿提醒器", "校准失败：有效采样太少，请确认侧面头肩在画面里")
                    return
                self.config["baseline"] = baseline
                save_config(self.config)
                self.monitor.reload(self.config)
                toast("坐姿提醒器",
                      f"校准完成：颈部基线 {baseline['neck']}°，跟踪侧 {baseline['side']}")
            finally:
                self.calibrating = False

        threading.Thread(target=do_calibrate, daemon=True).start()

    def quit(self, icon, _item):
        self._stop.set()
        if self.monitor:
            with self._camera_lock:
                self.monitor.close()
        icon.stop()

    def run(self):
        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._refresher, daemon=True).start()
        self.icon.run()


if __name__ == "__main__":
    TrayApp().run()
