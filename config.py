"""配置读写：config.json 的默认值、加载、保存。"""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    "camera_index": 0,          # 摄像头编号，外接摄像头后如识别错了改成 1
    "track_side": "auto",       # 跟踪身体哪一侧: "left"/"right"/"auto"。
                                # auto = 用校准时记录的主导侧；斜视角（如摄像头在
                                # 左前方）下如果选侧不对，手动指定
    "frames_per_sample": 3,     # 每次采样连拍几帧取中位数，抑制关键点抖动
    "sample_interval_sec": 10,  # 采样间隔（秒），越大越省电
    "bad_streak_to_alert": 3,   # 连续多少次采样都是坏姿势才提醒（3 次 x 10 秒 = 30 秒）
    "alert_cooldown_sec": 180,  # 姿势提醒后的冷却时间，避免连环轰炸
    "neck_delta_deg": 12,       # 颈部角度超过基线多少度算前倾
    "torso_delta_deg": 10,      # 躯干角度超过基线多少度算驼背
    "sit_limit_min": 50,        # 连续在座多少分钟提醒起身
    "sit_realert_min": 10,      # 久坐提醒后若继续坐着，每隔多少分钟再提醒
    "absence_reset_min": 3,     # 离开画面超过多少分钟算"起身过了"，重置久坐计时
    "baseline": None,           # 校准后写入 {"neck": x, "torso": y, "side": ...}
}


def load_config():
    config = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        config.update(json.loads(CONFIG_PATH.read_text()))
    return config


def save_config(config):
    data = {k: v for k, v in config.items() if k in DEFAULT_CONFIG}
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def resolve_side(config):
    """确定监控用哪一侧：手动指定优先，其次是校准时记录的主导侧。"""
    if config.get("track_side") in ("left", "right"):
        return config["track_side"]
    baseline = config.get("baseline") or {}
    return baseline.get("side", "auto")
