"""目标姿势库：定义、墙洞剪影绘制、玩家匹配打分。

三者共用同一份手臂角度表（ARM_DIR），保证"洞长什么样"和
"怎么判定"完全一致（所见即所判）。

坐标/角度约定：角度用数学惯例（x 轴向右为 0°，逆时针为正，y 向上），
画到屏幕时再把 y 翻回去。lean: -1 向左歪 / 0 直立 / 1 向右歪（屏幕方向）。
"""

import math
import random

import pygame

# 手臂方向（肩→腕的数学角度，度）。左右臂分开定义，名字一致
ARM_DIR = {
    "l": {"up": 100, "diag_up": 140, "side": 180, "diag_down": -140, "down": -95},
    "r": {"up": 80, "diag_up": 40, "side": 0, "diag_down": -40, "down": -85},
}

# (左臂, 右臂, 是否下蹲, 倾斜, 难度层级)
_P = [
    # 一层：站直，只考手臂
    ("side", "side", False, 0, 1),
    ("up", "up", False, 0, 1),
    ("up", "side", False, 0, 1),
    ("side", "up", False, 0, 1),
    ("down", "up", False, 0, 1),
    ("up", "down", False, 0, 1),
    ("diag_up", "diag_up", False, 0, 1),
    ("side", "down", False, 0, 1),
    ("down", "side", False, 0, 1),
    # 二层：加下蹲或倾斜
    ("side", "side", True, 0, 2),
    ("up", "up", True, 0, 2),
    ("diag_up", "side", False, 1, 2),
    ("side", "diag_up", False, -1, 2),
    ("up", "up", False, 1, 2),
    ("up", "up", False, -1, 2),
    ("down", "down", True, 0, 2),
    # 三层：组合刁钻
    ("diag_up", "down", False, 1, 3),
    ("down", "diag_up", False, -1, 3),
    ("diag_up", "diag_up", True, 0, 3),
    ("up", "side", False, -1, 3),
    ("side", "up", False, 1, 3),
    ("up", "diag_down", False, 1, 3),
    ("diag_down", "up", False, -1, 3),
]

POSES = [{"l": l, "r": r, "crouch": c, "lean": ln, "tier": t}
         for l, r, c, ln, t in _P]

PASS_SCORE = 0.60          # 匹配度达到即可穿墙
ARM_FREE_DEG = 15          # 手臂角度误差豁免
ARM_FAIL_DEG = 35          # 超过豁免后，再差这么多分数归零
ARM_GATE = 0.30            # 任一手臂低于此分，总分封顶 0.45（必挂）
LEAN_DEG = 11              # 躯干倾斜超过此角度算歪
CROUCH_DY = 0.09           # 鼻子比站立基线低这么多（归一化）算下蹲

COMPONENT_NAMES = {"l": "左臂", "r": "右臂", "crouch": "下蹲", "lean": "身体倾斜"}


def random_pose(max_tier, exclude=None, rng=random):
    cands = [p for p in POSES if p["tier"] <= max_tier and p is not exclude]
    return rng.choice(cands)


# ---------------------------------------------------------------- 剪影几何

# 全尺寸（墙未缩放时）的人形尺寸，故意画得比真人胖，给玩家容错
TORSO_LEN = 195
TORSO_W = 130
ARM_LEN = 180
ARM_W = 66
HEAD_R = 60
LEG_W = 62
SHOULDER_HALF = 56
HIP_STAND = 235            # 站立时髋部离地高度
HIP_CROUCH = 148


def silhouette(pose, feet_x, feet_y):
    """返回 (线段列表 [(p0, p1, 宽)], 圆列表 [(圆心, 半径)])，屏幕坐标。"""
    lean_a = math.radians(90 - pose["lean"] * 18)   # 躯干方向（数学角）
    hip_h = HIP_CROUCH if pose["crouch"] else HIP_STAND
    torso_len = TORSO_LEN * (0.82 if pose["crouch"] else 1.0)
    hip = (feet_x, feet_y - hip_h)

    def offset(p, ang, dist):
        return (p[0] + math.cos(ang) * dist, p[1] - math.sin(ang) * dist)

    sh_c = offset(hip, lean_a, torso_len)
    head = offset(sh_c, lean_a, 78)
    perp = lean_a - math.pi / 2
    sh_l = offset(sh_c, perp, -SHOULDER_HALF)
    sh_r = offset(sh_c, perp, SHOULDER_HALF)

    lines = [(hip, sh_c, TORSO_W)]
    circles = [(head, HEAD_R), (sh_c, TORSO_W // 2), (hip, TORSO_W // 2)]

    for side, sh in (("l", sh_l), ("r", sh_r)):
        ang = math.radians(ARM_DIR[side][pose[side]])
        wrist = offset(sh, ang, ARM_LEN)
        lines.append((sh, wrist, ARM_W))
        circles.append((wrist, ARM_W // 2 + 6))

    if pose["crouch"]:
        for sgn in (-1, 1):
            knee = (hip[0] + sgn * 82, feet_y - 78)
            foot = (hip[0] + sgn * 58, feet_y)
            lines.append((hip, knee, LEG_W))
            lines.append((knee, foot, LEG_W))
            circles.append((knee, LEG_W // 2))
    else:
        for sgn in (-1, 1):
            foot = (hip[0] + sgn * 48, feet_y)
            lines.append(((hip[0] + sgn * 26, hip[1]), foot, LEG_W))
    return lines, circles


def cut_hole(wall_surf, pose, feet_x, feet_y):
    """在墙面上按姿势剪影抠一个透明洞。"""
    mask = pygame.Surface(wall_surf.get_size(), pygame.SRCALPHA)
    lines, circles = silhouette(pose, feet_x, feet_y)
    white = (255, 255, 255, 255)
    for p0, p1, w_ in lines:
        pygame.draw.line(mask, white, p0, p1, int(w_))
    for c, r in circles:
        pygame.draw.circle(mask, white, c, int(r))
    wall_surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_SUB)


# ---------------------------------------------------------------- 匹配打分

def _wrap_deg(d):
    while d > 180:
        d -= 360
    while d < -180:
        d += 360
    return d


def _arm_score(pts, side, target_name):
    sh = pts.get(f"{side}_sh")
    wr = pts.get(f"{side}_wr")
    if sh is None or wr is None:
        return 0.0
    # 归一化坐标 y 向下 → 数学角要翻转 dy
    ang = math.degrees(math.atan2(sh[1] - wr[1], wr[0] - sh[0]))
    diff = abs(_wrap_deg(ang - ARM_DIR[side][target_name]))
    return max(0.0, 1.0 - max(0.0, diff - ARM_FREE_DEG) / ARM_FAIL_DEG)


def player_lean(pts):
    """玩家躯干倾斜类别：-1/0/1。"""
    l_sh, r_sh = pts.get("l_sh"), pts.get("r_sh")
    if l_sh is None or r_sh is None:
        return 0
    sh_c = ((l_sh[0] + r_sh[0]) / 2, (l_sh[1] + r_sh[1]) / 2)
    if "l_hip" in pts and "r_hip" in pts:
        hip_c = ((pts["l_hip"][0] + pts["r_hip"][0]) / 2,
                 (pts["l_hip"][1] + pts["r_hip"][1]) / 2)
    else:
        return 0
    dy = hip_c[1] - sh_c[1]
    if dy <= 0:
        return 0
    tilt = math.degrees(math.atan2(sh_c[0] - hip_c[0], dy))
    if tilt > LEAN_DEG:
        return 1
    if tilt < -LEAN_DEG:
        return -1
    return 0


def match_score(pose, pts, stand_nose_y):
    """返回 (总分 0~1, 分项 {"l","r","crouch","lean"})。"""
    if pts is None:
        return 0.0, {"l": 0.0, "r": 0.0, "crouch": 0.0, "lean": 0.0}
    detail = {
        "l": _arm_score(pts, "l", pose["l"]),
        "r": _arm_score(pts, "r", pose["r"]),
    }
    nose = pts.get("nose")
    if nose is not None and stand_nose_y is not None:
        crouching = nose[1] > stand_nose_y + CROUCH_DY
    else:
        crouching = False
    detail["crouch"] = 1.0 if crouching == pose["crouch"] else 0.0
    detail["lean"] = 1.0 if player_lean(pts) == pose["lean"] else 0.0
    # 手臂平均分打底；蹲/歪搞错是乘法重罚（站着穿蹲洞必失败）；
    # 单臂完全不对时封顶，防止"一臂标准一臂乱甩"混过去
    total = 0.5 * (detail["l"] + detail["r"])
    if min(detail["l"], detail["r"]) < ARM_GATE:
        total = min(total, 0.45)
    if detail["crouch"] < 1.0:
        total *= 0.45
    if detail["lean"] < 1.0:
        total *= 0.55
    return total, detail
