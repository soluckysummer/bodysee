"""坐姿监控核心：采样、判定、提醒的状态机。

供 CLI（main.py）和菜单栏应用（menubar.py）共用。
"""

import statistics
import time

import cv2

from alerts import notify
from config import resolve_side
from posture import PostureAnalyzer, median_result


def open_camera(index):
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise RuntimeError(f"打不开摄像头 {index}。请检查系统设置里的摄像头权限，"
                           f"或改 config.json 里的 camera_index。")
    return cap


def grab_fresh_frame(cap):
    """摄像头驱动会缓存旧帧，先丢弃几帧再取，保证拿到的是当前画面。"""
    for _ in range(4):
        cap.grab()
    ok, frame = cap.read()
    return frame if ok else None


PREVIEW_WIDTH = 640  # 预览图写盘宽度（菜单里按一半宽展示，视网膜屏刚好 2x 清晰）


def make_preview(frame, result, neck_limit=None, torso_limit=None):
    """在采样帧上标注判定用的关键点/连线和角度，返回缩放后的预览图。

    连线颜色即判定结果：绿=合格，红=超限。没检测到人则标注 no person，
    方便用户确认是取景问题还是识别问题。
    """
    img = frame.copy()
    h, w = img.shape[:2]
    good, bad = (0, 200, 0), (0, 0, 255)
    if result:
        px = {name: (int(x * w), int(y * h))
              for name, (x, y) in result["points"].items()}
        neck_bad = neck_limit is not None and result["neck"] > neck_limit
        torso_bad = (torso_limit is not None and result["torso"] is not None
                     and result["torso"] > torso_limit)
        if "hip" in px:
            cv2.line(img, px["hip"], px["shoulder"], bad if torso_bad else good, 4)
        cv2.line(img, px["shoulder"], px["ear"], bad if neck_bad else good, 4)
        for pt in px.values():
            cv2.circle(img, pt, 7, (255, 255, 255), -1)
            cv2.circle(img, pt, 7, (60, 60, 60), 2)
        texts = [(f"neck {result['neck']:.1f}"
                  + (f" / {neck_limit:.1f}" if neck_limit is not None else ""),
                  bad if neck_bad else good)]
        if result["torso"] is not None:
            texts.append((f"torso {result['torso']:.1f}"
                          + (f" / {torso_limit:.1f}" if torso_limit is not None else ""),
                          bad if torso_bad else good))
    else:
        texts = [("no person", (0, 165, 255))]
    texts.append((time.strftime("%H:%M:%S"), (255, 255, 255)))
    for i, (text, color) in enumerate(texts):
        pos = (16, 36 + i * 32)
        cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
        cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    return cv2.resize(img, (PREVIEW_WIDTH, round(h * PREVIEW_WIDTH / w)))


def run_calibration(cap, analyzer, config, log=print, duration=10):
    """采集标准坐姿，返回基线 dict；有效采样太少返回 None。不负责保存配置。"""
    forced_side = config["track_side"] if config.get("track_side") in ("left", "right") else "auto"
    necks, torsos, sides = [], [], []
    deadline = time.time() + duration
    while time.time() < deadline:
        frame = grab_fresh_frame(cap)
        if frame is None:
            continue
        result = analyzer.analyze(frame, side=forced_side)
        if result:
            necks.append(result["neck"])
            sides.append(result["side"])
            torsos.append(result["torso"])  # 可能为 None，后面按侧过滤时一起处理
            log(f"  采样 {len(necks):2d}: [{result['side']}] 颈部 {result['neck']:5.1f}°"
                + (f"  躯干 {result['torso']:5.1f}°" if result["torso"] is not None else "  躯干 --（髋部被挡）"))
        time.sleep(0.3)

    if len(necks) < 8:
        return None

    # 记录主导侧，监控时锁定它，避免斜视角下两侧来回切换导致角度跳变；
    # 只用主导侧的样本算基线，混入另一侧的会拉偏
    dominant = max(set(sides), key=sides.count)
    necks = [n for n, s in zip(necks, sides) if s == dominant]
    torsos = [t for t, s in zip(torsos, sides) if s == dominant and t is not None]
    return {
        "neck": round(statistics.median(necks), 1),
        "torso": round(statistics.median(torsos), 1) if len(torsos) >= 8 else None,
        "side": dominant,
    }


class PostureMonitor:
    """驱动方式：先 open()，然后周期性调 step()（间隔 self.interval 秒）。

    每次 step 后 self.status 是最新状态快照（菜单栏应用直接读它刷新 UI）：
    {"present": bool, "bad": ["前倾", ...], "neck": float|None, "torso": ...,
     "sit_min": float, "lines": [画面叠加文字], "updated": 时间戳}
    """

    def __init__(self, config, log=None):
        self.log = log or (lambda message: None)
        self.cap = None
        self.analyzer = None
        self.preview = None  # 最近一次采样的标注预览图（BGR），take_sample 后更新
        self.status = {"present": False, "bad": [], "neck": None, "torso": None,
                       "sit_min": 0.0, "lines": ["等待首次采样..."], "updated": 0.0}
        self.reload(config)

    def reload(self, config):
        """套用（新）配置和基线，并重置判定状态。校准后调用。"""
        baseline = config.get("baseline")
        if not baseline:
            raise RuntimeError("还没有校准基线，请先校准。")
        self.config = config
        self.baseline = baseline
        self.neck_limit = baseline["neck"] + config["neck_delta_deg"]
        self.torso_limit = (baseline["torso"] + config["torso_delta_deg"]
                            if baseline.get("torso") is not None else None)
        self.side = resolve_side(config)
        self.interval = config["sample_interval_sec"]
        self.frames_n = max(1, config.get("frames_per_sample", 3))
        self.streak_needed = config["bad_streak_to_alert"]
        # 判定状态
        self.neck_streak = 0
        self.torso_streak = 0
        self.last_posture_alert = 0.0
        self.sit_start = None          # 本次连续在座的开始时间
        self.last_seen = None          # 最后一次在画面里的时间
        self.next_sit_alert_min = config["sit_limit_min"]

    def open(self):
        self.cap = open_camera(self.config["camera_index"])
        self.analyzer = PostureAnalyzer()

    def close(self):
        if self.cap:
            self.cap.release()
            self.cap = None
        if self.analyzer:
            self.analyzer.close()
            self.analyzer = None

    def take_sample(self):
        """连拍多帧分别检测，取颈部角度中位的结果，抑制关键点抖动。

        同时把选中结果对应的帧做成标注预览图存到 self.preview。
        """
        pairs = []  # (帧, 检测结果)
        for i in range(self.frames_n):
            frame = grab_fresh_frame(self.cap)
            if frame is not None:
                pairs.append((frame, self.analyzer.analyze(frame, side=self.side)))
            if i < self.frames_n - 1:
                time.sleep(0.1)
        result = median_result([r for _, r in pairs])
        frame = next((f for f, r in pairs if r is result),
                     pairs[-1][0] if pairs else None)
        if frame is not None:
            self.preview = make_preview(frame, result,
                                        self.neck_limit, self.torso_limit)
        return result

    def step(self):
        return self.process(self.take_sample(), time.time())

    def reset_sit_timer(self):
        """手动重置久坐计时，从现在重新累计。"""
        self.sit_start = time.time() if self.status["present"] else None
        self.next_sit_alert_min = self.config["sit_limit_min"]
        self.status = {**self.status, "sit_min": 0.0}

    def process(self, result, now):
        """对一次采样结果执行判定和提醒逻辑，返回 (result, 画面叠加文字行)。"""
        config = self.config

        if result is None:
            # 画面里没人：离开足够久就重置久坐计时
            if self.last_seen and now - self.last_seen > config["absence_reset_min"] * 60:
                if self.sit_start:
                    self.log("检测到你已离开，久坐计时重置。")
                self.sit_start = None
                self.next_sit_alert_min = config["sit_limit_min"]
            self.neck_streak = self.torso_streak = 0
            self.log("画面中未检测到人")
            lines = ["no person detected"]
            self.status = {"present": False, "bad": [], "neck": None, "torso": None,
                           "sit_min": 0.0 if self.sit_start is None else (now - self.sit_start) / 60,
                           "lines": lines, "updated": now}
            return None, lines

        self.last_seen = now
        if self.sit_start is None:
            self.sit_start = now
        sit_min = (now - self.sit_start) / 60

        neck_bad = result["neck"] > self.neck_limit
        torso_bad = (self.torso_limit is not None and result["torso"] is not None
                     and result["torso"] > self.torso_limit)
        self.neck_streak = self.neck_streak + 1 if neck_bad else 0
        self.torso_streak = self.torso_streak + 1 if torso_bad else 0

        bad = []
        if neck_bad:
            bad.append("前倾")
        if torso_bad:
            bad.append("驼背")
        self.log(f"颈部 {result['neck']:5.1f}°"
                 + (f" 躯干 {result['torso']:5.1f}°" if result["torso"] is not None else " 躯干 --")
                 + f" | 在座 {sit_min:.0f}min | " + ("⚠ " + "+".join(bad) if bad else "OK"))

        # 姿势提醒：连续多次采样都不合格，且过了冷却期
        if now - self.last_posture_alert > config["alert_cooldown_sec"]:
            if self.neck_streak >= self.streak_needed and self.torso_streak >= self.streak_needed:
                notify("坐姿提醒", "脖子前倾 + 驼背了！\n收下巴，耳朵对齐肩膀，背挺直。")
                self.last_posture_alert = now
            elif self.neck_streak >= self.streak_needed:
                notify("坐姿提醒", f"脖子前倾了！当前 {result['neck']:.0f}°（基线 {self.baseline['neck']:.0f}°）。\n收下巴，让耳朵回到肩膀正上方。")
                self.last_posture_alert = now
            elif self.torso_streak >= self.streak_needed:
                notify("坐姿提醒", "驼背了！挺直背，肩膀回到髋部正上方。")
                self.last_posture_alert = now

        # 久坐提醒：到上限提醒一次，继续坐着则每隔 sit_realert_min 再提醒
        if sit_min >= self.next_sit_alert_min:
            notify("久坐提醒", f"已连续坐了 {sit_min:.0f} 分钟，起来活动一下吧！\n走动 3~5 分钟，顺便活动下颈椎。",
                   sound="Glass")
            self.next_sit_alert_min = sit_min + config["sit_realert_min"]

        lines = [f"side: {result['side']}" + (" (locked)" if self.side != "auto" else ""),
                 f"neck: {result['neck']:.1f} / {self.neck_limit:.1f} deg"
                 + ("  !" if neck_bad else "")]
        if result["torso"] is not None and self.torso_limit is not None:
            lines.append(f"torso: {result['torso']:.1f} / {self.torso_limit:.1f} deg"
                         + ("  !" if torso_bad else ""))
        lines.append(f"sitting: {sit_min:.0f} / {config['sit_limit_min']} min")
        lines.append(("BAD: " + "+".join(bad)) if bad else "posture: OK")

        self.status = {"present": True, "bad": bad, "neck": result["neck"],
                       "torso": result["torso"], "sit_min": sit_min,
                       "lines": lines, "updated": now}
        return result, lines
