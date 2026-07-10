"""实时全身姿态追踪，输出镜像画面和经过平滑的关键点。"""

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

LANDMARKS = {
    "nose": 0,
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_wrist": 15,
    "right_wrist": 16,
    "left_hip": 23,
    "right_hip": 24,
    "left_knee": 25,
    "right_knee": 26,
    "left_ankle": 27,
    "right_ankle": 28,
}

MIN_PRESENCE = 0.48
DETECT_WIDTH = 640
SMOOTH_ALPHA = 0.58


class BodyTracker(threading.Thread):
    """后台采集摄像头，游戏线程只读取最新的不可变快照。"""

    def __init__(self, camera_index, out_size):
        super().__init__(daemon=True)
        self.camera_index = camera_index
        self.out_w, self.out_h = out_size
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self.frame_rgb = None
        self.frame_seq = 0
        self.points = {}
        self.error = None
        self._smoothed = {}

    def stop(self):
        self._stop_event.set()

    def get_state(self):
        with self._lock:
            return self.frame_rgb, self.frame_seq, dict(self.points), self.error

    def run(self):
        landmarker = None
        cap = None
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
            cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                raise RuntimeError(
                    f"无法打开摄像头 {self.camera_index}（请检查权限或 --camera 参数）")
        except SystemExit as exc:
            self._set_error(str(exc))
            return
        except Exception as exc:
            self._set_error(f"姿态追踪初始化失败：{exc}")
            if landmarker:
                landmarker.close()
            return

        t0 = time.monotonic()
        last_ts_ms = -1
        try:
            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.04)
                    continue
                now = time.monotonic()
                frame = cv2.flip(frame, 1)
                display = self._resize_cover(frame)
                rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
                detect_h = int(DETECT_WIDTH * self.out_h / self.out_w)
                small = cv2.resize(rgb, (DETECT_WIDTH, detect_h),
                                   interpolation=cv2.INTER_AREA)
                ts_ms = max(last_ts_ms + 1, int((now - t0) * 1000))
                last_ts_ms = ts_ms
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=small)
                result = landmarker.detect_for_video(mp_image, ts_ms)
                points = self._extract(result.pose_landmarks, now)
                with self._lock:
                    self.frame_rgb = rgb
                    self.frame_seq += 1
                    self.points = points
        finally:
            cap.release()
            landmarker.close()

    def _set_error(self, message):
        with self._lock:
            self.error = message

    def _resize_cover(self, frame):
        h, w = frame.shape[:2]
        scale = max(self.out_w / w, self.out_h / h)
        nw, nh = int(round(w * scale)), int(round(h * scale))
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        x0 = (nw - self.out_w) // 2
        y0 = (nh - self.out_h) // 2
        return resized[y0:y0 + self.out_h, x0:x0 + self.out_w]

    def _extract(self, poses, now):
        if not poses:
            self._smoothed.clear()
            return {}
        landmarks = poses[0]
        result = {}
        for name, index in LANDMARKS.items():
            lm = landmarks[index]
            if lm.presence < MIN_PRESENCE or lm.visibility < MIN_PRESENCE:
                self._smoothed.pop(name, None)
                continue
            point = (lm.x * self.out_w, lm.y * self.out_h, now)
            previous = self._smoothed.get(name)
            if previous is not None:
                a = SMOOTH_ALPHA
                point = (previous[0] + a * (point[0] - previous[0]),
                         previous[1] + a * (point[1] - previous[1]), now)
            self._smoothed[name] = point
            result[name] = point
        return result
