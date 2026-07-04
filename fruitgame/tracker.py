"""摄像头手部追踪线程。

MediaPipe Pose 的 VIDEO 模式（带帧间追踪）实时跟踪双手位置，
同时把镜像后的摄像头画面处理成游戏窗口尺寸的 RGB 背景。

坐标约定：对外输出的手部位置是游戏窗口像素坐标（画面已镜像，
玩家向右挥手，屏幕上的点也向右移动）。
"""

import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

# posture.py 在项目根目录（复用它的模型下载逻辑）
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from posture import MODEL_PATH, _ensure_model

# PoseLandmarker 关键点索引：手腕 / 食指根部
LEFT_WRIST, RIGHT_WRIST = 15, 16
LEFT_INDEX, RIGHT_INDEX = 19, 20

MIN_PRESENCE = 0.5
# 检测用小图宽度：姿态模型对 640 宽已足够准，比全分辨率快得多
DETECT_WIDTH = 640
# 手部位置指数平滑系数（越大越跟手，越小越平滑）
SMOOTH_ALPHA = 0.65


class HandTracker(threading.Thread):
    """后台线程：采集摄像头 → 姿态检测 → 发布双手坐标和背景画面。"""

    def __init__(self, camera_index, out_size):
        super().__init__(daemon=True)
        self.camera_index = camera_index
        self.out_w, self.out_h = out_size
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # 发布区（加锁访问）
        self.frame_rgb = None          # 窗口尺寸的 RGB ndarray
        self.frame_seq = 0             # 画面序号，游戏侧据此判断是否有新帧
        self.hands = {"a": None, "b": None}   # 手 -> (x, y, 时间戳) 或 None
        self.error = None
        self._smoothed = {"a": None, "b": None}

    def stop(self):
        self._stop.set()

    def get_state(self):
        """返回 (frame_rgb, frame_seq, hands 快照, error)。"""
        with self._lock:
            return self.frame_rgb, self.frame_seq, dict(self.hands), self.error

    def run(self):
        try:
            _ensure_model()
            options = vision.PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
                running_mode=vision.RunningMode.VIDEO,
                num_poses=1,
                min_pose_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            landmarker = vision.PoseLandmarker.create_from_options(options)
        except SystemExit as e:
            with self._lock:
                self.error = str(e)
            return
        except Exception as e:
            with self._lock:
                self.error = f"姿态模型初始化失败: {e}"
            return

        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            with self._lock:
                self.error = f"无法打开摄像头 {self.camera_index}（检查权限或 --camera 参数）"
            landmarker.close()
            return

        t0 = time.monotonic()
        last_ts_ms = -1
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                now = time.monotonic()

                frame = cv2.flip(frame, 1)  # 镜像，动作方向与屏幕一致
                display = self._resize_cover(frame)
                rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)

                # 检测在缩小图上做，坐标是归一化的，与显示图通用
                small = cv2.resize(
                    rgb, (DETECT_WIDTH, int(DETECT_WIDTH * self.out_h / self.out_w)),
                    interpolation=cv2.INTER_AREA)
                ts_ms = int((now - t0) * 1000)
                if ts_ms <= last_ts_ms:      # VIDEO 模式要求时间戳严格递增
                    ts_ms = last_ts_ms + 1
                last_ts_ms = ts_ms
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=small)
                result = landmarker.detect_for_video(mp_image, ts_ms)

                hands = {"a": None, "b": None}
                if result.pose_landmarks:
                    lm = result.pose_landmarks[0]
                    hands["a"] = self._hand_point(lm, LEFT_WRIST, LEFT_INDEX, now)
                    hands["b"] = self._hand_point(lm, RIGHT_WRIST, RIGHT_INDEX, now)
                for key in ("a", "b"):
                    hands[key] = self._smooth(key, hands[key])

                with self._lock:
                    self.frame_rgb = rgb
                    self.frame_seq += 1
                    self.hands = hands
        finally:
            cap.release()
            landmarker.close()

    def _resize_cover(self, frame):
        """等比缩放 + 居中裁剪，铺满游戏窗口（避免拉伸变形）。"""
        h, w = frame.shape[:2]
        scale = max(self.out_w / w, self.out_h / h)
        nw, nh = int(round(w * scale)), int(round(h * scale))
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        x0 = (nw - self.out_w) // 2
        y0 = (nh - self.out_h) // 2
        return resized[y0:y0 + self.out_h, x0:x0 + self.out_w]

    def _hand_point(self, lm, wrist_idx, index_idx, now):
        """取手腕（可用时混合食指根部，更靠近手掌重心）的窗口像素坐标。"""
        wrist, index = lm[wrist_idx], lm[index_idx]
        if wrist.presence < MIN_PRESENCE or wrist.visibility < MIN_PRESENCE:
            return None
        x, y = wrist.x, wrist.y
        if index.presence >= MIN_PRESENCE and index.visibility >= MIN_PRESENCE:
            x = (wrist.x + index.x) / 2
            y = (wrist.y + index.y) / 2
        return (x * self.out_w, y * self.out_h, now)

    def _smooth(self, key, point):
        if point is None:
            self._smoothed[key] = None
            return None
        prev = self._smoothed[key]
        if prev is None:
            self._smoothed[key] = point
            return point
        a = SMOOTH_ALPHA
        sm = (prev[0] + a * (point[0] - prev[0]),
              prev[1] + a * (point[1] - prev[1]),
              point[2])
        self._smoothed[key] = sm
        return sm
