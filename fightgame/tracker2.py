"""双人姿态追踪线程。

MediaPipe Pose（num_poses=2，VIDEO 模式）同时跟踪两个人的上半身关键点，
按画面左右分配给玩家 0（左）/玩家 1（右）。画面已镜像：
站在摄像头左边的人就是屏幕左边的角色。

对外发布的每个玩家数据：
    {"t": 时间戳, "nose": (x, y), "l_sh": ..., ...}   坐标为归一化 [0,1]
缺人时为 None。
"""

import sys
import threading
import time
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from posture import MODEL_PATH, _ensure_model

# 用到的关键点：鼻、双肩、双肘、双腕、双髋
POINTS = {"nose": 0, "l_sh": 11, "r_sh": 12, "l_el": 13, "r_el": 14,
          "l_wr": 15, "r_wr": 16, "l_hip": 23, "r_hip": 24}
MIN_PRESENCE = 0.4
DETECT_WIDTH = 640
PIP_SIZE = (320, 180)       # 给游戏画中画用的小图尺寸
SMOOTH_ALPHA = 0.55         # 一般关键点平滑
SMOOTH_ALPHA_WRIST = 0.8    # 手腕要保留速度信息，少平滑


class DuoTracker(threading.Thread):
    def __init__(self, camera_index=0):
        super().__init__(daemon=True)
        self.camera_index = camera_index
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.players = [None, None]
        self.pip_rgb = None          # PIP_SIZE 的 RGB ndarray
        self.error = None
        self._smoothed = [{}, {}]

    def stop(self):
        self._stop.set()

    def get_state(self):
        with self._lock:
            return list(self.players), self.pip_rgb, self.error

    def run(self):
        try:
            _ensure_model()
            options = vision.PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
                running_mode=vision.RunningMode.VIDEO,
                num_poses=2,
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
                self.error = f"无法打开摄像头 {self.camera_index}"
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
                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w = rgb.shape[:2]
                small = cv2.resize(rgb, (DETECT_WIDTH, int(DETECT_WIDTH * h / w)),
                                   interpolation=cv2.INTER_AREA)
                ts_ms = int((now - t0) * 1000)
                if ts_ms <= last_ts_ms:
                    ts_ms = last_ts_ms + 1
                last_ts_ms = ts_ms
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=small)
                result = landmarker.detect_for_video(mp_image, ts_ms)

                players = [None, None]
                poses = []
                for lm in result.pose_landmarks:
                    pts = self._extract(lm, now)
                    if pts is not None:
                        poses.append(pts)
                # 按肩膀中心 x 分左右
                poses.sort(key=lambda p: p["_cx"])
                if len(poses) >= 2:
                    players[0], players[1] = poses[0], poses[-1]
                elif len(poses) == 1:
                    idx = 0 if poses[0]["_cx"] < 0.5 else 1
                    players[idx] = poses[0]
                for idx in (0, 1):
                    players[idx] = self._smooth(idx, players[idx])

                pip = cv2.resize(rgb, PIP_SIZE, interpolation=cv2.INTER_AREA)
                with self._lock:
                    self.players = players
                    self.pip_rgb = pip
        finally:
            cap.release()
            landmarker.close()

    @staticmethod
    def _extract(lm, now):
        """从一组关键点里取需要的点；双肩+至少一只手腕可靠才算有效。"""
        pts = {"t": now}
        for name, idx in POINTS.items():
            p = lm[idx]
            if p.presence >= MIN_PRESENCE and p.visibility >= MIN_PRESENCE:
                pts[name] = (p.x, p.y)
        if "l_sh" not in pts or "r_sh" not in pts:
            return None
        if "l_wr" not in pts and "r_wr" not in pts:
            return None
        pts["_cx"] = (pts["l_sh"][0] + pts["r_sh"][0]) / 2
        return pts

    def _smooth(self, idx, pts):
        if pts is None:
            self._smoothed[idx] = {}
            return None
        prev = self._smoothed[idx]
        out = {"t": pts["t"], "_cx": pts["_cx"]}
        for name in POINTS:
            if name not in pts:
                prev.pop(name, None)
                continue
            a = SMOOTH_ALPHA_WRIST if name in ("l_wr", "r_wr") else SMOOTH_ALPHA
            if name in prev:
                px, py = prev[name]
                out[name] = (px + a * (pts[name][0] - px),
                             py + a * (pts[name][1] - py))
            else:
                out[name] = pts[name]
            prev[name] = out[name]
        return out
