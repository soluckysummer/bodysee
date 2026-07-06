"""坐姿提醒器 · 菜单栏常驻版。

菜单栏图标实时反映状态：
    🟢 坐姿 OK（后跟在座分钟数）   🔴 坏姿势   ⚪ 画面里没人
    ⏸ 已暂停   🎯 校准中   ⚠️ 出错

菜单里可以：
    - 查看当前角度/在座时长、下次采样倒计时
    - 查看最近一次采样画面（带关键点标注，点击可打开大图）
    - 查看最近 3 次采样记录
    - 打开实时预览窗口（摆放摄像头/确认识别效果用）
    - 立即采样、暂停/继续监控、重新校准、重置久坐计时、打开日志、退出

启动: .venv/bin/python menubar.py   （或双击 菜单栏坐姿监控.command）
"""

import os
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import rumps
from AppKit import (NSApp, NSBackingStoreBuffered, NSFloatingWindowLevel,
                    NSImage, NSImageScaleProportionallyUpOrDown, NSImageView,
                    NSViewHeightSizable, NSViewWidthSizable, NSWindow,
                    NSWindowStyleMaskClosable, NSWindowStyleMaskMiniaturizable,
                    NSWindowStyleMaskResizable, NSWindowStyleMaskTitled)
from Foundation import NSData, NSMakeRect

from alerts import toast
from config import load_config, save_config
from monitor_core import (PostureMonitor, grab_fresh_frame, make_preview,
                          run_calibration)

LOG_PATH = Path(__file__).parent / "menubar.log"
PREVIEW_PATH = Path(tempfile.gettempdir()) / "bodyjk_posture_preview.png"
PREVIEW_SHOW_WIDTH = 320  # 菜单里图片的显示宽度（写盘是 2 倍宽，视网膜屏清晰）


class PostureApp(rumps.App):
    def __init__(self):
        super().__init__("⏳", quit_button=None)
        self.config = load_config()
        self.paused = False
        self.calibrating = False
        self.error = None
        self.monitor = None
        self.next_sample_at = None       # 下次采样的预计时间戳（worker 写）
        self.history = deque(maxlen=3)   # 最近 3 次采样的状态快照，新的在前
        self._stop = threading.Event()
        self._wake = threading.Event()   # 打断采样间隔等待（立即采样/暂停/退出）
        self._force_sample = False
        self._camera_lock = threading.Lock()
        self._preview_stamp = 0.0        # 预览图落盘时间（worker 写）
        self._preview_applied = 0.0      # 已刷到菜单上的版本（主线程写）
        self._preview_dims = (PREVIEW_SHOW_WIDTH, PREVIEW_SHOW_WIDTH * 3 // 4)
        self._live_window = None         # 实时预览窗口（首次打开时创建，之后复用）
        self._live_view = None
        self._live_timer = rumps.Timer(self._live_tick, 0.15)

        self.item_posture = rumps.MenuItem("状态: 启动中...")
        self.item_sit = rumps.MenuItem("在座: --")
        self.item_next = rumps.MenuItem("下次采样: --")
        self.item_preview = rumps.MenuItem("采样画面: 等待首次采样...",
                                           callback=self.open_preview)
        self.item_hist = [rumps.MenuItem(f"  {i + 1}. 暂无") for i in range(3)]
        self.item_pause = rumps.MenuItem("暂停监控", callback=self.toggle_pause)
        self.item_calibrate = rumps.MenuItem("重新校准（先坐正，采集 10 秒）",
                                             callback=self.recalibrate)
        self.menu = [self.item_posture, self.item_sit, self.item_next, None,
                     self.item_preview, None,
                     rumps.MenuItem("最近 3 次采样"), *self.item_hist, None,
                     rumps.MenuItem("立即采样一次", callback=self.sample_now),
                     rumps.MenuItem("实时预览（摆放摄像头用）",
                                    callback=self.toggle_live_preview),
                     self.item_pause, self.item_calibrate,
                     rumps.MenuItem("重置久坐计时", callback=self.reset_sit), None,
                     rumps.MenuItem("打开日志", callback=self.open_log),
                     rumps.MenuItem("退出", callback=self.quit)]

        threading.Thread(target=self._worker, daemon=True).start()
        rumps.Timer(self._refresh, 1).start()

    # ---------------------------------------------------------- 后台监控线程

    def _worker(self):
        try:
            self.monitor = PostureMonitor(self.config)
            self.monitor.open()
        except RuntimeError as e:
            self.error = str(e)
            return
        while not self._stop.is_set():
            if (self.paused or self.calibrating) and not self._force_sample:
                self._stop.wait(0.5)
                continue
            self._force_sample = False
            try:
                with self._camera_lock:
                    self.monitor.step()
            except Exception as e:  # 摄像头被占用等异常不让线程死掉
                self.error = f"检测出错: {e}"
                self._stop.wait(10)
                self.error = None
                continue
            self._save_preview()
            self.history.appendleft(dict(self.monitor.status))
            self.next_sample_at = time.time() + self.monitor.interval
            self._wake.wait(self.monitor.interval)
            self._wake.clear()

    def _save_preview(self):
        frame = self.monitor.preview
        if frame is None:
            return
        h, w = frame.shape[:2]
        tmp = PREVIEW_PATH.with_name(PREVIEW_PATH.stem + "_tmp.png")
        try:
            cv2.imwrite(str(tmp), frame)
            os.replace(tmp, PREVIEW_PATH)  # 原子替换，避免主线程读到半张图
        except Exception:
            return
        self._preview_dims = (PREVIEW_SHOW_WIDTH,
                              round(PREVIEW_SHOW_WIDTH * h / w))
        self._preview_stamp = time.time()

    # ---------------------------------------------------------- UI 刷新

    def _refresh(self, _timer):
        self._refresh_preview()
        self._refresh_history()
        self._refresh_countdown()
        self._refresh_status()

    def _refresh_preview(self):
        if self._preview_stamp == self._preview_applied:
            return
        self._preview_applied = self._preview_stamp
        self.item_preview.title = ""
        self.item_preview.set_icon(str(PREVIEW_PATH),
                                   dimensions=self._preview_dims)

    def _refresh_history(self):
        for i, (item, st) in enumerate(zip(self.item_hist, self.history)):
            item.title = f"  {i + 1}. {self._format_sample(st)}"

    @staticmethod
    def _format_sample(st):
        ts = time.strftime("%H:%M:%S", time.localtime(st["updated"]))
        if not st["present"]:
            return f"{ts}  画面中没有人"
        text = f"{ts}  颈 {st['neck']:.1f}°"
        if st["torso"] is not None:
            text += f"  躯干 {st['torso']:.1f}°"
        text += ("  ⚠ " + "+".join(st["bad"])) if st["bad"] else "  ✓"
        return text

    def _refresh_countdown(self):
        if self.error or self.calibrating or not self.monitor:
            self.item_next.title = "下次采样: --"
        elif self.paused:
            self.item_next.title = "下次采样: 已暂停"
        elif self.next_sample_at is None:
            self.item_next.title = "下次采样: 正在采样..."
        else:
            remain = self.next_sample_at - time.time()
            self.item_next.title = ("下次采样: 正在采样..." if remain <= 0
                                    else f"下次采样: {remain:.0f} 秒后")

    def _refresh_status(self):
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

    # ---------------------------------------------------------- 实时预览窗口

    def toggle_live_preview(self, _sender):
        """打开/关闭实时预览悬浮窗。窗口用系统关闭按钮关掉也会自动停帧。"""
        if not self.monitor or self.error or self.calibrating:
            return
        if self._live_window is not None and self._live_window.isVisible():
            self._live_timer.stop()
            self._live_window.orderOut_(None)
            return
        self._open_live_window()

    def _open_live_window(self):
        if self._live_window is None:
            with self._camera_lock:
                frame = grab_fresh_frame(self.monitor.cap)
            h, w = frame.shape[:2] if frame is not None else (360, 640)
            rect = NSMakeRect(0, 0, 640, round(640 * h / w))
            style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                     | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable)
            win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                rect, style, NSBackingStoreBuffered, False)
            win.setTitle_("坐姿实时预览")
            win.setReleasedWhenClosed_(False)      # 关闭后还要复用
            win.setLevel_(NSFloatingWindowLevel)   # 置顶，摆摄像头时不被挡住
            view = NSImageView.alloc().initWithFrame_(rect)
            view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
            view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            win.setContentView_(view)
            win.center()
            self._live_window, self._live_view = win, view
        self._live_window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        if not self._live_timer.is_alive():
            self._live_timer.start()

    def _live_tick(self, _timer):
        win = self._live_window
        if win is None or not win.isVisible():
            self._live_timer.stop()
            return
        # 后台正在采样/校准就跳过这一帧，绝不阻塞主线程
        if not self._camera_lock.acquire(blocking=False):
            return
        try:
            ok, frame = self.monitor.cap.read()
            result = (self.monitor.analyzer.analyze(frame, side=self.monitor.side)
                      if ok else None)
        finally:
            self._camera_lock.release()
        if not ok:
            return
        img = make_preview(frame, result,
                           self.monitor.neck_limit, self.monitor.torso_limit)
        encoded, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not encoded:
            return
        data = NSData.dataWithBytes_length_(buf.tobytes(), len(buf))
        self._live_view.setImage_(NSImage.alloc().initWithData_(data))

    # ---------------------------------------------------------- 菜单动作

    def sample_now(self, _sender):
        if not self.monitor or self.error or self.calibrating:
            return
        self._force_sample = True
        self.next_sample_at = time.time()
        self._wake.set()

    def toggle_pause(self, sender):
        self.paused = not self.paused
        sender.title = "继续监控" if self.paused else "暂停监控"
        self._wake.set()  # 暂停立即生效；继续则马上采一次
        self._refresh(None)

    def reset_sit(self, _sender):
        if not self.monitor or self.error:
            return
        self.monitor.reset_sit_timer()
        toast("坐姿提醒器", "久坐计时已重置，从现在重新累计。")

    def open_preview(self, _sender):
        if PREVIEW_PATH.exists():
            subprocess.Popen(["open", str(PREVIEW_PATH)])

    def open_log(self, _sender):
        if LOG_PATH.exists():
            subprocess.Popen(["open", str(LOG_PATH)])

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
        self._wake.set()
        if self.monitor:
            with self._camera_lock:
                self.monitor.close()
        rumps.quit_application()


if __name__ == "__main__":
    PostureApp().run()
