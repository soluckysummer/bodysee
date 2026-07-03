"""侧面视角坐姿分析：基于 MediaPipe PoseLandmarker 关键点计算颈部/躯干角度。

坐标系说明：MediaPipe 输出归一化图像坐标，y 轴向下。
- 颈部角度 neck：肩膀->耳朵 连线与竖直方向的夹角。坐正时耳朵基本在肩膀正上方，
  角度小；脖子前倾时耳朵向前移，角度变大。
- 躯干角度 torso：髋部->肩膀 连线与竖直方向的夹角。驼背/前趴时肩膀相对髋部
  前移，角度变大。
"""

import math
import sys
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

MODEL_PATH = Path(__file__).parent / "models" / "pose_landmarker_lite.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
             "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task")

# PoseLandmarker 关键点索引
LEFT_EAR, RIGHT_EAR = 7, 8
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_HIP, RIGHT_HIP = 23, 24

# 关键点可见度低于此值视为不可靠
MIN_VISIBILITY = 0.5


def _ensure_model():
    if MODEL_PATH.exists():
        return
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"首次运行，下载姿态模型（约 5.5MB）到 {MODEL_PATH} ...")
    try:
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    except Exception as e:
        sys.exit(f"模型下载失败: {e}\n请手动下载 {MODEL_URL} 并保存为 {MODEL_PATH}")


def _angle_from_vertical(lower, upper):
    """下方点指向上方点的向量与竖直向上方向的夹角（度）。

    图像 y 轴向下，upper 应在 lower 上方；若不满足（姿态异常/误检）返回 None。
    """
    dx = upper.x - lower.x
    dy = lower.y - upper.y  # >0 表示 upper 在 lower 上方
    if dy <= 0:
        return None
    return math.degrees(math.atan2(abs(dx), dy))


class PostureAnalyzer:
    def __init__(self):
        _ensure_model()
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.5,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)

    def close(self):
        self._landmarker.close()

    def analyze(self, frame_bgr, side="auto"):
        """分析一帧，返回 dict 或 None（画面中没有可靠的人体）。

        side: "left"/"right" 固定用某一侧的关键点（斜视角下两侧可见度接近，
              自动选侧会左右横跳，锁定一侧才稳定）；"auto" 按可见度自动选。

        返回: {"neck": 度数, "torso": 度数或 None, "side": "left"/"right",
               "points": 本次判定用到的关键点 {名字: (归一化x, 归一化y)}}
        """
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect(mp_image)
        if not result.pose_landmarks:
            return None

        lm = result.pose_landmarks[0]

        if side == "left":
            pick = "left"
        elif side == "right":
            pick = "right"
        else:
            # 按耳+肩+髋的平均可见度选侧
            left_vis = (lm[LEFT_EAR].visibility + lm[LEFT_SHOULDER].visibility
                        + lm[LEFT_HIP].visibility) / 3
            right_vis = (lm[RIGHT_EAR].visibility + lm[RIGHT_SHOULDER].visibility
                         + lm[RIGHT_HIP].visibility) / 3
            pick = "left" if left_vis >= right_vis else "right"

        if pick == "left":
            side, ear, shoulder, hip = "left", lm[LEFT_EAR], lm[LEFT_SHOULDER], lm[LEFT_HIP]
        else:
            side, ear, shoulder, hip = "right", lm[RIGHT_EAR], lm[RIGHT_SHOULDER], lm[RIGHT_HIP]

        # 耳朵和肩膀是判断的最低要求，不可靠就当作没检测到人
        if ear.visibility < MIN_VISIBILITY or shoulder.visibility < MIN_VISIBILITY:
            return None

        neck = _angle_from_vertical(shoulder, ear)
        if neck is None:
            return None

        # 髋部常被桌子/椅背挡住，躯干角度算不出来就只用颈部判断
        torso = None
        hip_ok = hip.visibility >= MIN_VISIBILITY
        if hip_ok:
            torso = _angle_from_vertical(hip, shoulder)

        points = {"ear": (ear.x, ear.y), "shoulder": (shoulder.x, shoulder.y)}
        if hip_ok:
            points["hip"] = (hip.x, hip.y)

        return {"neck": neck, "torso": torso, "side": side, "points": points}


def median_result(results):
    """从同一次采样的多帧结果里选颈部角度居中的那个，压掉单帧检测抖动。"""
    valid = [r for r in results if r]
    if not valid:
        return None
    necks = sorted(r["neck"] for r in valid)
    median_neck = necks[len(necks) // 2]
    return min(valid, key=lambda r: abs(r["neck"] - median_neck))
