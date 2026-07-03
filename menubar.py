"""坐姿提醒器 · 菜单栏常驻版。

菜单栏图标实时反映状态：
    🟢 坐姿 OK（后跟在座分钟数）   🔴 坏姿势   ⚪ 画面里没人
    ⏸ 已暂停   🎯 校准中   ⚠️ 出错

菜单里可以：查看当前角度/在座时长、暂停/继续监控、重新校准、退出。

启动: .venv/bin/python menubar.py   （或双击 菜单栏坐姿监控.command）
"""

import threading
import time

import rumps

from alerts import toast
from config import load_config, save_config
from monitor_core import PostureMonitor, run_calibration


class PostureApp(rumps.App):
    def __init__(self):
        super().__init__("⏳", quit_button=None)
        self.config = load_config()
        self.paused = False
        self.calibrating = False
        self.error = None
        self.monitor = None
        self._stop = threading.Event()
        self._camera_lock = threading.Lock()

        self.item_posture = rumps.MenuItem("状态: 启动中...")
        self.item_sit = rumps.MenuItem("在座: --")
        self.item_pause = rumps.MenuItem("暂停监控", callback=self.toggle_pause)
        self.item_calibrate = rumps.MenuItem("重新校准（先坐正，采集 10 秒）",
                                             callback=self.recalibrate)
        self.menu = [self.item_posture, self.item_sit, None,
                     self.item_pause, self.item_calibrate, None,
                     rumps.MenuItem("退出", callback=self.quit)]

        threading.Thread(target=self._worker, daemon=True).start()
        rumps.Timer(self._refresh, 2).start()

    # ---------------------------------------------------------- 后台监控线程

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

    # ---------------------------------------------------------- UI 刷新

    def _refresh(self, _timer):
        if self.error:
            self.title = "⚠️"
            self.item_posture.title = f"状态: {self.error}"
            self.item_sit.title = "在座: --"
            return
        if self.calibrating:
            self.title = "🎯"
            self.item_posture.title = "状态: 校准中，请坐正..."
            return
        if self.paused:
            self.title = "⏸"
            self.item_posture.title = "状态: 已暂停"
            return
        if not self.monitor:
            return

        st = self.monitor.status
        if st["updated"] == 0:
            return  # 还没有首次采样
        if not st["present"]:
            self.title = "⚪"
            self.item_posture.title = "状态: 画面中没有人"
            self.item_sit.title = "在座: --"
            return

        sit = f"{st['sit_min']:.0f}"
        if st["bad"]:
            self.title = f"🔴 {'+'.join(st['bad'])}"
            self.item_posture.title = f"状态: ⚠ {'+'.join(st['bad'])}"
        else:
            self.title = f"🟢 {sit}m"
            self.item_posture.title = "状态: 坐姿 OK"
        angles = f"颈部 {st['neck']:.1f}° / 上限 {self.monitor.neck_limit:.1f}°"
        if st["torso"] is not None and self.monitor.torso_limit is not None:
            angles += f"，躯干 {st['torso']:.1f}° / {self.monitor.torso_limit:.1f}°"
        self.item_posture.title = self.item_posture.title + f"（{angles}）"
        self.item_sit.title = f"在座: {sit} 分钟 / 上限 {self.config['sit_limit_min']} 分钟"

    # ---------------------------------------------------------- 菜单动作

    def toggle_pause(self, sender):
        self.paused = not self.paused
        sender.title = "继续监控" if self.paused else "暂停监控"
        self._refresh(None)

    def recalibrate(self, _sender):
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

    def quit(self, _sender):
        self._stop.set()
        if self.monitor:
            with self._camera_lock:
                self.monitor.close()
        rumps.quit_application()


if __name__ == "__main__":
    PostureApp().run()
