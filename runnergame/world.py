"""三轨跑酷的实体、难度曲线和公平波次生成器。"""

import random
from dataclasses import dataclass

LANES = (0, 1, 2)

BARRIER = "barrier"
OVERHEAD = "overhead"
TRAIN = "train"
CRATE = "crate"
OBSTACLE_KINDS = (BARRIER, OVERHEAD, TRAIN, CRATE)

SHIELD = "shield"
MAGNET = "magnet"
BOOST = "boost"
DOUBLE = "double"
POWER_KINDS = (SHIELD, MAGNET, BOOST, DOUBLE)


@dataclass
class TrackObject:
    kind: str
    lane: int
    progress: float = 0.0
    checked: bool = False
    warned: bool = False


@dataclass
class Coin:
    lane: int
    progress: float = 0.0
    collected: bool = False


@dataclass
class PowerUp:
    kind: str
    lane: int
    progress: float = 0.0
    collected: bool = False


def speed_for(elapsed):
    """以轨道进度/秒表示的速度，三分钟逐渐拉满。"""
    difficulty = min(1.0, max(0.0, elapsed) / 180.0)
    return 0.205 + difficulty * 0.115


def spawn_interval(elapsed):
    difficulty = min(1.0, max(0.0, elapsed) / 180.0)
    return 1.55 - difficulty * 0.60


def project(lane, progress, width=1280, height=720):
    """把轨道、深度投影到屏幕坐标和缩放比例。"""
    p = max(0.0, min(1.12, progress))
    horizon_y = height * 0.235
    y = horizon_y + (p ** 1.72) * (height - horizon_y + 62)
    half_width = 24 + (p ** 1.38) * width * 0.405
    x = width / 2 + (lane - 1) * half_width * 0.57
    scale = 0.16 + p ** 1.48 * 0.92
    return x, y, scale


def obstacle_avoided(kind, jumping=False, ducking=False, punching=False):
    if kind == BARRIER:
        return jumping
    if kind == OVERHEAD:
        return ducking
    if kind == CRATE:
        return punching
    return False


class WavePlanner:
    """生成有明确安全轨道的障碍波次和引导金币。"""

    def __init__(self, seed=2026):
        self.rng = random.Random(seed)

    def make_wave(self, elapsed):
        difficulty = min(1.0, max(0.0, elapsed) / 150.0)
        obstacle_count = 2 if self.rng.random() < 0.14 + difficulty * 0.34 else 1
        blocked = self.rng.sample(list(LANES), obstacle_count)
        safe_lanes = [lane for lane in LANES if lane not in blocked]
        safe_lane = self.rng.choice(safe_lanes)

        if elapsed < 10:
            pool = (BARRIER,)
        elif elapsed < 24:
            pool = (BARRIER, OVERHEAD)
        elif elapsed < 42:
            pool = (BARRIER, OVERHEAD, TRAIN)
        else:
            pool = OBSTACLE_KINDS
        obstacles = [TrackObject(self.rng.choice(pool), lane) for lane in blocked]

        # 金币排成一条安全引导线，最后一枚稍早于障碍抵达玩家。
        coins = [Coin(safe_lane, -0.10 * index) for index in range(1, 6)]
        power = None
        if elapsed > 14 and self.rng.random() < 0.105:
            power = PowerUp(self.rng.choice(POWER_KINDS), safe_lane, -0.18)
        return obstacles, coins, power, safe_lane


def validate_wave(obstacles):
    blocked = {obstacle.lane for obstacle in obstacles}
    return bool(set(LANES) - blocked) and all(obstacle.kind in OBSTACLE_KINDS
                                              for obstacle in obstacles)
