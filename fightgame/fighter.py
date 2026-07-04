"""格斗角色：把玩家的真实骨架映射成擂台上的霓虹小人。

上半身（头、躯干、双臂）完全镜像玩家的实时动作；腿是程序生成的
站姿。所有判定用的世界坐标（拳头位置/速度、头部、躯干圈）都在
update_pose 里算好，供 game.py 的战斗逻辑使用。
"""

import math
import random
import time

import pygame

W, H = 1280, 720
FLOOR_Y = H - 80
LEG_H = 140
CHAR_SH_W = 92          # 角色肩宽（世界像素），两边固定一致保证公平
HEAD_R = 30
TORSO_R = 48            # 躯干受击圈半径

# 玩家在自己半边画面里左右移动 → 角色在擂台自己的活动区间里移动
ZONES = {0: (130, W * 0.60), 1: (W * 0.40, W - 130)}
CAM_RANGES = {0: (0.06, 0.48), 1: (0.52, 0.94)}
CAM_RANGE_FULL = (0.15, 0.85)   # 单人模式用整个画面


def _mid(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Fighter:
    def __init__(self, idx, name, color, full_range=False):
        self.idx = idx                      # 0 左 / 1 右
        self.facing = 1 if idx == 0 else -1  # 朝向对手的方向
        self.name = name
        self.color = color
        self.zone = ZONES[idx]
        self.cam_range = CAM_RANGE_FULL if full_range else CAM_RANGES[idx]
        self.x = (self.zone[0] + self.zone[1]) / 2
        self.kb_v = 0.0                     # 受击后的击退速度

        self.hp = 100.0
        self.display_hp = 100.0             # 血条动画用，缓慢追上 hp
        self.meter = 40.0                   # 气（0~100，满了可以放气功弹）
        self.wins = 0
        self.combo_n = 0
        self.combo_t = 0.0

        self.tracked = False
        self.last_tracked = 0.0
        self.pts = None                     # 最近一帧归一化关键点
        self.joints = {}                    # 世界坐标关节
        self.fists = {}                     # 手 -> {"pos","vel","speed","t"}
        self._fist_hist = {}

        self.guarding = False
        self.hands_together = False
        self.crouching = False
        self.raised = False                 # 举手（准备/庆祝）
        self.stand_nose_y = None            # 站立时鼻子高度（回合开始校准）
        self.charge_t = 0.0
        self.charged = False

        self.hit_flash_t = 0.0
        self.ko_t = None

    # ---------------- 姿态 → 世界坐标

    def update_pose(self, pts, now, dt):
        if pts is None:
            self.tracked = False
            return
        self.tracked = True
        self.last_tracked = now
        self.pts = pts

        l_sh, r_sh = pts["l_sh"], pts["r_sh"]
        sh_c = _mid(l_sh, r_sh)
        sw = max(_dist(l_sh, r_sh), 0.05)
        if "l_hip" in pts and "r_hip" in pts:
            hip_c = _mid(pts["l_hip"], pts["r_hip"])
        else:
            hip_c = (sh_c[0], sh_c[1] + sw * 1.15)
        scale = min(CHAR_SH_W / sw, 2400.0)

        # 水平位置：玩家在画面里的位置映射到擂台活动区
        lo, hi = self.cam_range
        t = min(1.0, max(0.0, (sh_c[0] - lo) / (hi - lo)))
        target_x = self.zone[0] + t * (self.zone[1] - self.zone[0])
        self.x += (target_x - self.x) * min(1.0, dt * 9)
        self.x += self.kb_v * dt
        self.kb_v *= max(0.0, 1 - dt * 6)
        self.x = min(max(self.x, self.zone[0]), self.zone[1])

        hip_w = (self.x, FLOOR_Y - LEG_H)

        def world(p):
            return (hip_w[0] + (p[0] - hip_c[0]) * scale,
                    hip_w[1] + (p[1] - hip_c[1]) * scale)

        j = {name: world(p) for name, p in pts.items()
             if name not in ("t", "_cx")}
        # 头：优先鼻子，否则肩上方
        if "nose" in j:
            head = (j["nose"][0], j["nose"][1] - HEAD_R * 0.2)
        else:
            sc = world(sh_c)
            head = (sc[0], sc[1] - HEAD_R * 1.6)
        j["head"] = head
        j["sh_c"] = world(sh_c)
        j["hip_c"] = hip_w
        j["chest"] = _mid(j["sh_c"], hip_w)
        self.joints = j

        # 拳头（世界坐标）速度：只有 tracker 出新样本时才更新
        for hand, wr in (("l", "l_wr"), ("r", "r_wr")):
            if wr not in j:
                self._fist_hist.pop(hand, None)
                self.fists.pop(hand, None)
                continue
            pos = j[wr]
            prev = self._fist_hist.get(hand)
            if prev is not None and pts["t"] > prev[2]:
                pdt = pts["t"] - prev[2]
                if pdt < 0.2:
                    vel = ((pos[0] - prev[0]) / pdt, (pos[1] - prev[1]) / pdt)
                    self.fists[hand] = {"pos": pos, "vel": vel,
                                        "speed": math.hypot(*vel), "t": pts["t"]}
            if prev is None or pts["t"] > prev[2]:
                self._fist_hist[hand] = (pos[0], pos[1], pts["t"])

        # ------ 姿势判定（归一化空间，尺度用肩宽做基准）
        chest_n = _mid(sh_c, hip_c)
        wrists = [pts.get("l_wr"), pts.get("r_wr")]
        self.guarding = all(w is not None and _dist(w, _mid(sh_c, pts.get("nose", sh_c))) < sw * 1.15
                            for w in wrists)
        self.hands_together = (wrists[0] is not None and wrists[1] is not None
                               and _dist(wrists[0], wrists[1]) < sw * 0.75)
        nose = pts.get("nose")
        self.raised = any(w is not None and nose is not None
                          and w[1] < nose[1] - 0.03 for w in wrists)
        if nose is not None and self.stand_nose_y is not None:
            self.crouching = nose[1] > self.stand_nose_y + 0.10
        else:
            self.crouching = False

    def hurt_circles(self):
        """(圆心, 半径, 是否头部) 列表，用于受击判定。"""
        if not self.joints:
            return []
        return [(self.joints["head"], HEAD_R, True),
                (self.joints["chest"], TORSO_R, False)]

    # ---------------- 绘制

    def draw(self, scene, now):
        if not self.joints:
            return
        j = self.joints
        c = self.color
        flash = now - self.hit_flash_t < 0.12
        if flash:
            c = (255, 255, 255)
        crumple = 0.0
        if self.ko_t is not None:
            crumple = min(1.0, (now - self.ko_t) / 0.7)

        def P(p):
            x, y = p
            if crumple > 0:   # KO：整个人向地面瘫下去
                y = FLOOR_Y - (FLOOR_Y - y) * (1 - 0.8 * crumple)
            return (int(x), int(y))

        def glow_line(p0, p1, wid):
            dim = tuple(int(v * 0.32) for v in c)
            pygame.draw.line(scene, dim, P(p0), P(p1), wid + 8)
            pygame.draw.line(scene, c, P(p0), P(p1), wid)
            core = tuple(min(255, v + 130) for v in c)
            pygame.draw.line(scene, core, P(p0), P(p1), max(2, wid - 7))

        # 腿（程序生成的站姿，带一点弹性）
        bounce = math.sin(now * 3 + self.idx * 2) * 3
        for side, hip_name in ((-1, "l_hip"), (1, "r_hip")):
            hip = j.get(hip_name, j["hip_c"])
            knee = (hip[0] + side * 15, FLOOR_Y - LEG_H * 0.45 + bounce)
            foot = (hip[0] + side * 26, FLOOR_Y)
            glow_line(hip, knee, 12)
            glow_line(knee, foot, 11)
            pygame.draw.ellipse(scene, tuple(int(v * 0.5) for v in c),
                                (P(foot)[0] - 20, FLOOR_Y - 8, 44, 14))

        # 躯干
        if all(k in j for k in ("l_sh", "r_sh")):
            l_hip = j.get("l_hip", (j["hip_c"][0] - 20, j["hip_c"][1]))
            r_hip = j.get("r_hip", (j["hip_c"][0] + 20, j["hip_c"][1]))
            poly = [P(j["l_sh"]), P(j["r_sh"]), P(r_hip), P(l_hip)]
            body = tuple(int(v * 0.42) for v in c)
            pygame.draw.polygon(scene, body, poly)
            pygame.draw.polygon(scene, c, poly, 3)
        glow_line(j["sh_c"], j["hip_c"], 10)

        # 头
        head = P(j["head"])
        pygame.draw.circle(scene, tuple(int(v * 0.35) for v in c), head, HEAD_R + 5)
        pygame.draw.circle(scene, c, head, HEAD_R)
        pygame.draw.circle(scene, (15, 15, 22), head, HEAD_R - 7)
        # 面罩亮条朝向对手
        eye_x = head[0] + self.facing * 9
        pygame.draw.line(scene, tuple(min(255, v + 120) for v in c),
                         (eye_x - 7, head[1] - 5), (eye_x + 7, head[1] - 5), 5)

        # 手臂 + 拳头
        for sh, el, wr in (("l_sh", "l_el", "l_wr"), ("r_sh", "r_el", "r_wr")):
            if sh in j and el in j:
                glow_line(j[sh], j[el], 11)
                if wr in j:
                    glow_line(j[el], j[wr], 10)
            elif sh in j and wr in j:
                glow_line(j[sh], j[wr], 10)
            if wr in j:
                fist = P(j[wr])
                pygame.draw.circle(scene, tuple(int(v * 0.4) for v in c),
                                   fist, 17)
                pygame.draw.circle(scene, c, fist, 13)
                pygame.draw.circle(scene, (255, 255, 255), fist, 6)

        # 格挡护盾
        if self.guarding and self.ko_t is None:
            chest = P(j["chest"])
            cx = chest[0] + self.facing * 52
            shield = pygame.Surface((150, 190), pygame.SRCALPHA)
            pygame.draw.ellipse(shield, (*c, 45), shield.get_rect())
            pygame.draw.ellipse(shield, (*c, 140), shield.get_rect(), 4)
            scene.blit(shield, shield.get_rect(center=(cx, chest[1])))

        # 蓄力气团
        if self.charge_t > 0 and self.ko_t is None and "l_wr" in j and "r_wr" in j:
            mid = P(_mid(j["l_wr"], j["r_wr"]))
            r = 8 + 30 * min(1.0, self.charge_t / 0.7)
            pulse = 4 * math.sin(now * 18)
            pygame.draw.circle(scene, (255, 255, 255), mid, int(max(2, r * 0.4)))
            pygame.draw.circle(scene, c, mid, int(r + pulse), 3)
            pygame.draw.circle(scene, tuple(min(255, v + 90) for v in c),
                               mid, int(r * 0.75), 2)

        # 名字 + 状态标
        label_y = FLOOR_Y + 16
        if self.crouching:
            pygame.draw.circle(scene, (120, 220, 255), (int(self.x), label_y + 24), 5)


class BotDriver:
    """人机/演示模式的假玩家：产生和 DuoTracker 相同格式的关键点流。"""

    FPS = 30

    def __init__(self, idx, aggression=0.8):
        self.idx = idx
        self.aggression = aggression
        self.cx = 0.25 if idx == 0 else 0.75
        self._target_cx = self.cx
        self._next_sample = 0.0
        self._next_decision = 0.0
        self._action = "idle"       # idle / punch_l / punch_r / guard / charge
        self._action_t0 = 0.0
        self._punch_phase = 0.0
        self.in_range = False       # 由 game 每帧告知
        self.meter_full = False
        self.rng = random.Random(idx * 7 + 3)

    def step(self, now):
        """按 30Hz 产生新样本；没到时间返回 None（表示沿用旧数据）。"""
        if now < self._next_sample:
            return None
        self._next_sample = now + 1.0 / self.FPS
        self._think(now)
        return self._pose(now)

    def _think(self, now):
        if now < self._next_decision:
            return
        rng = self.rng
        if self._action.startswith("punch") and now - self._action_t0 < 0.4:
            return
        roll = rng.random()
        if self.meter_full and roll < 0.5:
            self._action = "charge"
            self._next_decision = now + 1.4
        elif self.in_range and roll < self.aggression * 0.75:
            self._action = "punch_l" if rng.random() < 0.5 else "punch_r"
            self._next_decision = now + rng.uniform(0.45, 1.0)
        elif roll < 0.75:
            self._action = "idle"
            # 靠近或远离对手
            toward = 0.5 - self.cx
            step = rng.uniform(-0.08, 0.16) * (1 if toward > 0 else -1)
            base = self.cx + step * self.aggression
            lo, hi = (0.08, 0.46) if self.idx == 0 else (0.54, 0.92)
            self._target_cx = min(max(base, lo), hi)
            self._next_decision = now + rng.uniform(0.5, 1.2)
        else:
            self._action = "guard"
            self._next_decision = now + rng.uniform(0.6, 1.2)
        self._action_t0 = now

    def _pose(self, now):
        self.cx += (self._target_cx - self.cx) * 0.12
        cx = self.cx
        sway = math.sin(now * 2.1 + self.idx * 3) * 0.006
        sh_y = 0.42 + sway
        sw = 0.17
        face = 1 if self.idx == 0 else -1     # 朝向画面中央
        pts = {
            "t": now,
            "nose": (cx + face * 0.01, sh_y - 0.11),
            "l_sh": (cx - sw / 2, sh_y),
            "r_sh": (cx + sw / 2, sh_y),
            "l_hip": (cx - sw * 0.4, sh_y + 0.20),
            "r_hip": (cx + sw * 0.4, sh_y + 0.20),
        }
        # 手臂动作
        idle_l = (cx - sw * 0.75, sh_y + 0.13 + math.sin(now * 3) * 0.01)
        idle_r = (cx + sw * 0.75, sh_y + 0.13 + math.cos(now * 3.4) * 0.01)
        act, dt_a = self._action, now - self._action_t0
        if act == "guard":
            pts["l_wr"] = (cx - 0.03, sh_y - 0.05)
            pts["r_wr"] = (cx + 0.03, sh_y - 0.05)
        elif act == "charge":
            if dt_a < 0.9:   # 合掌蓄力
                pts["l_wr"] = (cx - 0.015, sh_y + 0.08)
                pts["r_wr"] = (cx + 0.015, sh_y + 0.08)
            else:            # 前推发波
                push = min(1.0, (dt_a - 0.9) / 0.12) * 0.22 * face
                pts["l_wr"] = (cx - 0.015 + push, sh_y + 0.05)
                pts["r_wr"] = (cx + 0.015 + push, sh_y + 0.05)
        elif act.startswith("punch"):
            hand = "l_wr" if act == "punch_l" else "r_wr"
            other = "r_wr" if hand == "l_wr" else "l_wr"
            # 0~0.12s 出拳，0.12~0.35s 收回
            if dt_a < 0.12:
                ext = dt_a / 0.12
            else:
                ext = max(0.0, 1 - (dt_a - 0.12) / 0.23)
            pts[hand] = (cx + face * (0.05 + 0.24 * ext), sh_y + 0.03 - 0.05 * ext)
            pts[other] = idle_l if other == "l_wr" else idle_r
        else:
            pts["l_wr"], pts["r_wr"] = idle_l, idle_r
        # 手肘放在肩和腕之间偏下
        for el, sh, wr in (("l_el", "l_sh", "l_wr"), ("r_el", "r_sh", "r_wr")):
            s, w_ = pts[sh], pts[wr]
            pts[el] = ((s[0] + w_[0]) / 2, (s[1] + w_[1]) / 2 + 0.045)
        pts["_cx"] = cx
        return pts
