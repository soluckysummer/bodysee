"""神拳对决 主程序。

两名玩家站在摄像头前（左边的人 = 左边角色），画面里的霓虹小人
实时镜像你的动作：

- 快速出拳打中对方 → 掉血（打头伤害更高）
- 双手护在脸前 → 格挡（伤害降到 15%）
- 左右移动身体 → 角色进退（够不着就打不到，逼近才能出拳）
- 气攒满后双手合拢蓄力 0.7 秒，再猛推出去 → 气功弹
- 对手可以真人下蹲躲过气功弹
- 60 秒一回合，三局两胜，KO 或时间到血多者胜

模式：默认双人；--solo 单人打电脑；--demo 两个电脑对打（看效果用）。
"""

import argparse
import math
import os
import random
import sys
import time
from pathlib import Path

import pygame

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fightgame import sfx
from fightgame.fighter import (Fighter, BotDriver, W, H, FLOOR_Y,
                               HEAD_R, TORSO_R)

FPS = 60
ROUND_SEC = 60
WINS_NEED = 2
PUNCH_SPEED = 620.0        # 拳头速度阈值（世界 px/s）
FIRE_SPEED = 430.0         # 发波前推速度阈值
PUNCH_COOLDOWN = 0.35
CHARGE_TIME = 0.7
FIREBALL_DMG = 22.0
FIREBALL_V = 540.0

P1_COLOR = (70, 220, 255)
P2_COLOR = (255, 100, 85)

MENU, ROUND_INTRO, FIGHT, ROUND_END, MATCH_END = range(5)


def _find_cjk_font():
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyh.ttf",
        "C:/Windows/Fonts/simhei.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    for name in ("PingFang SC", "Microsoft YaHei", "SimHei",
                  "Noto Sans CJK SC", "WenQuanYi Micro Hei"):
        p = pygame.font.match_font(name)
        if p:
            return p
    return None


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "r0", "color", "t0", "life", "grav")

    def __init__(self, x, y, vx, vy, r, color, life, grav=900.0):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.r0, self.color = r, color
        self.t0 = time.monotonic()
        self.life, self.grav = life, grav

    def update(self, dt):
        self.vy += self.grav * dt
        self.x += self.vx * dt
        self.y += self.vy * dt

    def draw(self, scene, now):
        frac = 1.0 - (now - self.t0) / self.life
        if frac > 0:
            pygame.draw.circle(scene, self.color, (int(self.x), int(self.y)),
                               max(1, int(self.r0 * frac)))


class FloatText:
    def __init__(self, surf, x, y, life=0.8, rise=44):
        self.surf, self.x, self.y = surf, x, y
        self.t0, self.life, self.rise = time.monotonic(), life, rise

    def draw(self, scene, now):
        frac = (now - self.t0) / self.life
        if frac >= 1:
            return False
        img = self.surf.copy()
        img.set_alpha(int(255 * (1 - frac ** 2)))
        scene.blit(img, img.get_rect(center=(self.x, self.y - self.rise * frac)))
        return True


class Fireball:
    def __init__(self, owner, x, y, vx, color):
        self.owner = owner
        self.x, self.y, self.vx = x, y, vx
        self.color = color

    def update(self, dt):
        self.x += self.vx * dt

    def draw(self, scene, now):
        r = 20 + 3 * math.sin(now * 22)
        pygame.draw.circle(scene, tuple(int(v * 0.4) for v in self.color),
                           (int(self.x), int(self.y)), int(r + 12))
        pygame.draw.circle(scene, self.color, (int(self.x), int(self.y)), int(r))
        pygame.draw.circle(scene, (255, 255, 255),
                           (int(self.x), int(self.y)), int(r * 0.5))


class Announcer:
    """屏幕中央的大字播报（回合、KO、连击等），带弹出动画。"""

    def __init__(self, font_big, font_mid):
        self.font_big, self.font_mid = font_big, font_mid
        self.items = []

    def say(self, text, dur=1.4, color=(255, 255, 255), big=True, y=0.36):
        self.items.append({"text": text, "t0": time.monotonic(), "dur": dur,
                           "color": color, "big": big, "y": y})

    def draw(self, scene, now):
        self.items = [m for m in self.items if now - m["t0"] < m["dur"]]
        for m in self.items:
            age = now - m["t0"]
            font = self.font_big if m["big"] else self.font_mid
            surf = font.render(m["text"], True, m["color"])
            pop = min(1.0, age / 0.12)
            scale = 0.5 + 0.5 * pop
            fade = 1.0
            if age > m["dur"] - 0.3:
                fade = max(0.0, (m["dur"] - age) / 0.3)
            img = pygame.transform.rotozoom(surf, 0, scale)
            img.set_alpha(int(255 * fade))
            shadow = pygame.transform.rotozoom(
                font.render(m["text"], True, (0, 0, 0)), 0, scale)
            shadow.set_alpha(int(140 * fade))
            rect = img.get_rect(center=(W / 2, H * m["y"]))
            scene.blit(shadow, rect.move(4, 4))
            scene.blit(img, rect)


def build_arena():
    """霓虹夜擂台背景，启动时渲染一次。"""
    s = pygame.Surface((W, H))
    for y in range(H):
        t = y / H
        s.fill((int(10 + 26 * t), int(6 + 10 * t), int(26 + 34 * t)),
               (0, y, W, 1))
    rng = random.Random(9)
    for _ in range(90):
        x, y = rng.randrange(W), rng.randrange(int(FLOOR_Y * 0.75))
        b = rng.randint(90, 200)
        s.set_at((x, y), (b, b, min(255, b + 30)))
    # 地平线光带
    for i, (col, wid) in enumerate((((255, 70, 160), 6), ((120, 60, 220), 14))):
        glow = pygame.Surface((W, wid * 2), pygame.SRCALPHA)
        glow.fill((*col, 70 - i * 30))
        s.blit(glow, (0, FLOOR_Y - wid))
    pygame.draw.line(s, (255, 120, 200), (0, FLOOR_Y), (W, FLOOR_Y), 3)
    # 透视网格地板
    vx, vy = W / 2, FLOOR_Y - 260
    for i in range(-14, 15):
        x_far = W / 2 + i * 46
        x_near = W / 2 + i * 260
        pygame.draw.line(s, (70, 40, 120),
                         (x_far, FLOOR_Y), (x_near, H), 2)
    y = FLOOR_Y + 4
    step = 7.0
    while y < H:
        pygame.draw.line(s, (85, 50, 140), (0, int(y)), (W, int(y)), 2)
        y += step
        step *= 1.55
    # 中线标记
    pygame.draw.line(s, (255, 200, 90), (W / 2, FLOOR_Y - 8), (W / 2, FLOOR_Y + 8), 4)
    return s


class Game:
    def __init__(self, mode="versus", camera_index=0):
        pygame.mixer.pre_init(sfx.SR, -16, 1, 512)
        pygame.init()
        pygame.display.set_caption("神拳对决")
        self.screen = pygame.display.set_mode((W, H), pygame.SCALED)
        self.scene = pygame.Surface((W, H))
        self.clock = pygame.time.Clock()
        try:
            sfx.init()
        except pygame.error:
            pass

        font_path = _find_cjk_font()
        self.font_huge = pygame.font.Font(font_path, 96)
        self.font_big = pygame.font.Font(font_path, 64)
        self.font_mid = pygame.font.Font(font_path, 36)
        self.font_small = pygame.font.Font(font_path, 24)
        self.announcer = Announcer(self.font_huge, self.font_mid)

        self.mode = mode
        self.tracker = None
        self.bots = {}
        if mode != "demo":
            from fightgame.tracker2 import DuoTracker
            self.tracker = DuoTracker(camera_index)
            self.tracker.start()
        if mode == "solo":
            self.bots[1] = BotDriver(1, aggression=0.7)
        elif mode == "demo":
            self.bots[0] = BotDriver(0, aggression=0.9)
            self.bots[1] = BotDriver(1, aggression=0.9)
        self._bot_pts = {}          # bot 上一次产生的样本（30Hz 之间沿用）

        self.fighters = [
            Fighter(0, "青影", P1_COLOR, full_range=(mode == "solo")),
            Fighter(1, "赤焰", P2_COLOR),
        ]
        self.arena = build_arena()
        self.particles = []
        self.texts = []
        self.fireballs = []

        self.state = MENU
        self.round_no = 1
        self.round_deadline = 0.0
        self.state_t0 = time.monotonic()
        self.ready_t = [0.0, 0.0]
        self.paused = False
        self.freeze_until = 0.0
        self.shake_until = 0.0
        self.shake_amp = 10
        self.flash = 0.0
        self.winner = None
        self._punch_seen = {}
        self._whoosh_gate = [0.0, 0.0]
        self._stand_samples = [[], []]
        self._meter_was_full = [False, False]
        self._last_beep = 0
        self.pip_surface = None

    # ---------------- 主循环

    def run(self):
        running = True
        while running:
            raw_dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            now = time.monotonic()
            running = self._handle_events()
            frozen = now < self.freeze_until or self.paused
            dt = 0.0 if frozen else raw_dt

            self._feed_poses(now, raw_dt)

            if self.state == MENU:
                self._update_menu(now, raw_dt)
            elif self.state == ROUND_INTRO:
                self._update_intro(now)
            elif self.state == FIGHT and not frozen:
                self._update_fight(now, dt)
            elif self.state == ROUND_END:
                self._update_round_end(now, dt)
            elif self.state == MATCH_END:
                self._update_match_end(now, raw_dt, dt)

            for p in self.particles:
                p.update(dt)
            self.particles = [p for p in self.particles
                              if now - p.t0 < p.life][-350:]
            self.flash = max(0.0, self.flash - raw_dt * 2.5)

            self._draw(now)
        if self.tracker:
            self.tracker.stop()
        pygame.quit()

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self.state == MENU:
                        return False
                    self._back_to_menu()
                elif event.key == pygame.K_f:
                    pygame.display.toggle_fullscreen()
                elif event.key == pygame.K_p and self.state == FIGHT:
                    self.paused = not self.paused
                elif event.key == pygame.K_SPACE:
                    if self.state == MENU:
                        self._start_match()
                    elif self.state == MATCH_END:
                        self._start_match()
                elif event.key == pygame.K_r and self.state == MATCH_END:
                    self._start_match()
        return True

    # ---------------- 姿态输入

    def _feed_poses(self, now, dt):
        players = [None, None]
        error = None
        if self.tracker:
            players, pip, error = self.tracker.get_state()
            if pip is not None:
                self.pip_surface = pygame.image.frombuffer(
                    pip.tobytes(), (pip.shape[1], pip.shape[0]), "RGB")
        self.tracker_error = error

        if self.mode == "solo":
            # 单人模式：画面里唯一的人就是 P1
            solo = players[0] if players[0] is not None else players[1]
            players = [solo, None]

        for idx, bot in self.bots.items():
            d = abs(self.fighters[0].x - self.fighters[1].x)
            bot.in_range = d < 340
            bot.meter_full = self.fighters[idx].meter >= 100
            pts = bot.step(now)
            if pts is not None:
                self._bot_pts[idx] = pts
            players[idx] = self._bot_pts.get(idx)

        for idx, f in enumerate(self.fighters):
            f.update_pose(players[idx], now, dt)
            f.display_hp += (f.hp - f.display_hp) * min(1.0, dt * 5)

        # 身体碰撞：不允许两个角色穿过对方
        f0, f1 = self.fighters
        min_gap = 90
        if f0.tracked and f1.tracked and f1.x - f0.x < min_gap:
            mid = (f0.x + f1.x) / 2
            f0.x = mid - min_gap / 2
            f1.x = mid + min_gap / 2

    def _both_tracked(self):
        return all(f.tracked for f in self.fighters)

    # ---------------- 状态机

    def _back_to_menu(self):
        self.state = MENU
        self.state_t0 = time.monotonic()
        self.fireballs = []
        self.ready_t = [0.0, 0.0]
        self.paused = False
        for f in self.fighters:
            f.hp = f.display_hp = 100.0
            f.meter = 40.0
            f.wins = 0
            f.ko_t = None
            f.charge_t = 0.0
            f.charged = False

    def _start_match(self):
        for f in self.fighters:
            f.wins = 0
        self.round_no = 1
        self.winner = None
        self._start_round()

    def _start_round(self):
        now = time.monotonic()
        self.state = ROUND_INTRO
        self.state_t0 = now
        self.fireballs = []
        self._stand_samples = [[], []]
        for f in self.fighters:
            f.hp = f.display_hp = 100.0
            f.meter = 40.0
            f.combo_n = 0
            f.ko_t = None
            f.charge_t = 0.0
            f.charged = False
            f.kb_v = 0.0
        self._meter_was_full = [False, False]
        self.announcer.say(f"第 {self.round_no} 回合", dur=1.6,
                           color=(255, 220, 120))
        sfx.play("ready")

    def _update_menu(self, now, dt):
        if self.mode == "demo":
            if now - self.state_t0 > 2.0:
                self._start_match()
            return
        self._update_ready(now, dt, start=self._start_match)

    def _update_ready(self, now, dt, start):
        """双方同时举手 1 秒开始。"""
        for idx, f in enumerate(self.fighters):
            controlled_by_bot = idx in self.bots
            ok = controlled_by_bot or (f.tracked and f.raised)
            if ok:
                self.ready_t[idx] = min(1.0, self.ready_t[idx] + dt)
            else:
                self.ready_t[idx] = max(0.0, self.ready_t[idx] - dt * 2)
        if all(t >= 1.0 for t in self.ready_t):
            self.ready_t = [0.0, 0.0]
            start()

    def _update_intro(self, now):
        # 校准站立身高（发波下蹲躲避的基准）
        for idx, f in enumerate(self.fighters):
            if f.tracked and f.pts and "nose" in f.pts:
                self._stand_samples[idx].append(f.pts["nose"][1])
        if now - self.state_t0 >= 2.0:
            for idx, f in enumerate(self.fighters):
                samples = self._stand_samples[idx]
                if samples:
                    f.stand_nose_y = sorted(samples)[len(samples) // 2]
            self.state = FIGHT
            self.state_t0 = now
            self.round_deadline = now + ROUND_SEC
            self.announcer.say("开打！", dur=0.9, color=(255, 90, 80))
            sfx.play("gong")

    def _update_fight(self, now, dt):
        # 真人玩家跟丢：暂停战斗和计时
        lost = [f for i, f in enumerate(self.fighters)
                if i not in self.bots and not f.tracked
                and now - f.last_tracked > 0.8]
        if self.mode != "demo" and lost:
            self.round_deadline += dt
            return

        remain = self.round_deadline - now
        if remain <= 5.5 and int(remain) != self._last_beep and remain > 0:
            self._last_beep = int(remain)
            sfx.play("beep")
        if remain <= 0:
            self._end_round_by_time(now)
            return

        for idx, f in enumerate(self.fighters):
            opp = self.fighters[1 - idx]
            self._check_punches(f, opp, now)
            self._check_fireball_input(f, opp, now, dt)

        for fb in self.fireballs[:]:
            fb.update(dt)
            self.particles.append(Particle(
                fb.x - fb.vx * 0.02, fb.y + random.uniform(-8, 8),
                -fb.vx * 0.2, random.uniform(-40, 40),
                random.uniform(3, 6), fb.color, 0.3, grav=0))
            target = self.fighters[1 - fb.owner]
            hit = False
            if target.crouching:
                pass          # 蹲下躲过
            else:
                for center, r, is_head in target.hurt_circles():
                    if math.hypot(fb.x - center[0], fb.y - center[1]) < r + 22:
                        hit = True
                        break
            if hit:
                self._apply_hit(self.fighters[fb.owner], target,
                                FIREBALL_DMG, (fb.x, fb.y), now,
                                is_head=False, is_fireball=True)
                self.fireballs.remove(fb)
            elif fb.x < -60 or fb.x > W + 60:
                self.fireballs.remove(fb)

    def _end_round_by_time(self, now):
        f0, f1 = self.fighters
        self.announcer.say("时间到", dur=1.6)
        if abs(f0.hp - f1.hp) < 0.5:
            self.announcer.say("平局，重赛本回合", dur=2.2, big=False, y=0.5)
        else:
            winner = f0 if f0.hp > f1.hp else f1
            winner.wins += 1
            self.announcer.say(f"{winner.name} 胜出本回合", dur=2.2,
                               color=winner.color, big=False, y=0.5)
        self.state = ROUND_END
        self.state_t0 = now

    def _update_round_end(self, now, dt):
        if now - self.state_t0 < 3.0:
            return
        for f in self.fighters:
            if f.wins >= WINS_NEED:
                self.winner = f
                self.state = MATCH_END
                self.state_t0 = now
                self.announcer.say(f"{f.name} 获胜！", dur=2.5, color=f.color)
                sfx.play("win")
                return
        self.round_no += 1
        self._start_round()

    def _update_match_end(self, now, raw_dt, dt):
        if self.mode == "demo":
            if now - self.state_t0 > 5.0:
                self._start_match()
            return
        if now - self.state_t0 > 2.0:
            self._update_ready(now, raw_dt, start=self._start_match)

    # ---------------- 战斗

    def _check_punches(self, f, opp, now):
        if (f.ko_t is not None or opp.ko_t is not None
                or not f.tracked or f.guarding or f.charged):
            return
        for hand, fist in f.fists.items():
            key = (f.idx, hand)
            if self._punch_seen.get(key) == fist["t"]:
                continue
            self._punch_seen[key] = fist["t"]
            speed = fist["speed"]
            toward = fist["vel"][0] * f.facing
            if speed < PUNCH_SPEED or toward < speed * 0.45:
                continue
            gate_key = f.idx
            if now - self._whoosh_gate[gate_key] > 0.25:
                sfx.play("whoosh")
                self._whoosh_gate[gate_key] = now
            cd_key = ("cd", f.idx, hand)
            if now - self._punch_seen.get(cd_key, 0) < PUNCH_COOLDOWN:
                continue
            pos = fist["pos"]
            for center, r, is_head in opp.hurt_circles():
                if math.hypot(pos[0] - center[0], pos[1] - center[1]) < r + 20:
                    self._punch_seen[cd_key] = now
                    dmg = 5.0 + min(6.0, (speed - PUNCH_SPEED) / 130.0)
                    if is_head:
                        dmg *= 1.35
                    self._apply_hit(f, opp, dmg, pos, now, is_head)
                    break

    def _apply_hit(self, attacker, defender, dmg, pos, now,
                   is_head=False, is_fireball=False):
        if defender.ko_t is not None:
            return
        blocked = defender.guarding and not is_head
        if blocked:
            dmg *= 0.15
            sfx.play("block")
        elif is_fireball:
            sfx.play("boom")
        else:
            sfx.play("hit_head" if is_head else "hit_body")

        defender.hp = max(0.0, defender.hp - dmg)
        defender.hit_flash_t = now
        defender.kb_v = (140 if blocked else 260) * attacker.facing
        attacker.meter = min(100.0, attacker.meter + (6 if blocked else 14))
        defender.meter = min(100.0, defender.meter + 7)

        # 连击
        if now - attacker.combo_t < 1.2:
            attacker.combo_n += 1
        else:
            attacker.combo_n = 1
        attacker.combo_t = now
        if attacker.combo_n >= 2 and not blocked:
            surf = self.font_mid.render(
                f"{attacker.combo_n} 连击！", True, attacker.color)
            x = W * 0.28 if attacker.idx == 0 else W * 0.72
            self.texts.append(FloatText(surf, x, H * 0.30, life=0.9))

        # 打击特效
        n = 26 if is_fireball else (6 if blocked else 14)
        base_cols = ((150, 190, 255), (220, 235, 255)) if blocked else \
                    ((255, 240, 160), (255, 160, 70), (255, 255, 255))
        for _ in range(n):
            a = random.uniform(0, math.tau)
            spd = random.uniform(120, 520)
            self.particles.append(Particle(
                pos[0], pos[1], math.cos(a) * spd, math.sin(a) * spd,
                random.uniform(2, 5), random.choice(base_cols),
                random.uniform(0.25, 0.5), grav=500))
        surf = self.font_mid.render(f"-{dmg:.0f}", True,
                                    (170, 200, 255) if blocked else (255, 235, 130))
        self.texts.append(FloatText(surf, pos[0], pos[1] - 20))

        self.freeze_until = now + (0.10 if is_fireball else 0.06)
        self.shake_until = now + (0.4 if is_fireball else 0.18)
        self.shake_amp = 16 if is_fireball else 8
        if is_fireball:
            self.flash = 0.55

        if defender.hp <= 0:
            defender.ko_t = now
            attacker.wins += 1
            attacker.combo_n = 0
            self.announcer.say("K.O.！", dur=2.2, color=(255, 80, 70))
            sfx.play("ko")
            self.flash = 0.7
            self.shake_until = now + 0.6
            self.shake_amp = 18
            self.freeze_until = now + 0.35
            self.state = ROUND_END
            self.state_t0 = now

    def _check_fireball_input(self, f, opp, now, dt):
        if f.ko_t is not None or not f.tracked:
            return
        full = f.meter >= 100
        if full and not self._meter_was_full[f.idx]:
            sfx.play("ready")
        self._meter_was_full[f.idx] = full
        if not full:
            f.charge_t = 0.0
            f.charged = False
            return
        if f.hands_together and not f.charged:
            if f.charge_t == 0.0:
                sfx.play("charge")
            f.charge_t += dt
            if f.charge_t >= CHARGE_TIME:
                f.charged = True
        elif not f.hands_together and not f.charged:
            f.charge_t = 0.0
        if f.charged:
            vels = [fist["vel"][0] * f.facing for fist in f.fists.values()
                    if now - fist["t"] < 0.15]
            if vels and min(vels) > FIRE_SPEED:
                chest = f.joints.get("chest", (f.x, FLOOR_Y - 220))
                self.fireballs.append(Fireball(
                    f.idx, chest[0] + f.facing * 60, chest[1] - 10,
                    FIREBALL_V * f.facing, f.color))
                f.meter = 0.0
                f.charge_t = 0.0
                f.charged = False
                sfx.play("fireball")

    # ---------------- 绘制

    def _draw_hud(self, now):
        bar_w, bar_h, y = 470, 26, 34
        for idx, f in enumerate(self.fighters):
            if idx == 0:
                x0 = 46
                fill_from_right = True
            else:
                x0 = W - 46 - bar_w
                fill_from_right = False
            pygame.draw.rect(self.scene, (25, 25, 35), (x0 - 3, y - 3,
                             bar_w + 6, bar_h + 6))
            # 白色残血条（display_hp 缓慢追上，显示刚扣的血）
            for hp_val, col in ((f.display_hp, (200, 80, 70)),
                                (f.hp, (90, 220, 120) if f.hp > 30 else (245, 200, 60))):
                w_ = int(bar_w * hp_val / 100)
                fx = x0 + (bar_w - w_) if fill_from_right else x0
                pygame.draw.rect(self.scene, col, (fx, y, w_, bar_h))
            pygame.draw.rect(self.scene, (240, 240, 245),
                             (x0 - 3, y - 3, bar_w + 6, bar_h + 6), 2)
            name = self.font_small.render(f.name, True, f.color)
            nx = x0 if idx == 0 else x0 + bar_w - name.get_width()
            self.scene.blit(name, (nx, y + bar_h + 6))
            # 胜场圆点
            for wn in range(WINS_NEED):
                cx = x0 + 60 + wn * 26 if idx == 0 else x0 + bar_w - 60 - wn * 26
                col = (255, 210, 80) if wn < f.wins else (60, 60, 75)
                pygame.draw.circle(self.scene, col, (cx, y + bar_h + 18), 8)
                pygame.draw.circle(self.scene, (230, 230, 235),
                                   (cx, y + bar_h + 18), 8, 2)
            # 气条
            mw, mh = 300, 13
            mx = 46 if idx == 0 else W - 46 - mw
            my = H - 40
            pygame.draw.rect(self.scene, (25, 25, 35), (mx - 2, my - 2, mw + 4, mh + 4))
            fillw = int(mw * f.meter / 100)
            fx = mx if idx == 0 else mx + mw - fillw
            col = (255, 210, 80) if f.meter >= 100 else (150, 130, 220)
            if f.meter >= 100 and int(now * 4) % 2:
                col = (255, 245, 180)
            pygame.draw.rect(self.scene, col, (fx, my, fillw, mh))
            pygame.draw.rect(self.scene, (220, 220, 230),
                             (mx - 2, my - 2, mw + 4, mh + 4), 2)
            if f.meter >= 100:
                hint = self.font_small.render("气满！双手合拢蓄力→猛推发波",
                                              True, (255, 235, 160))
                hx = mx if idx == 0 else mx + mw - hint.get_width()
                self.scene.blit(hint, (hx, my - 30))

        # 计时
        if self.state == FIGHT:
            remain = max(0, int(self.round_deadline - time.monotonic() + 0.999))
        else:
            remain = ROUND_SEC
        col = (255, 255, 255) if remain > 10 else (255, 110, 90)
        t_surf = self.font_big.render(f"{remain}", True, col)
        pygame.draw.circle(self.scene, (25, 25, 40), (W // 2, 58), 46)
        pygame.draw.circle(self.scene, (230, 230, 240), (W // 2, 58), 46, 3)
        self.scene.blit(t_surf, t_surf.get_rect(center=(W // 2, 58)))

    def _draw_pip(self):
        """底部中央画中画：摄像头实况 + 中线，玩家用它校正站位。"""
        if self.mode == "demo":
            return
        pw, ph = 320, 180
        x0, y0 = (W - pw) // 2, H - ph - 14
        if self.pip_surface is not None:
            self.scene.blit(self.pip_surface, (x0, y0))
            if self.mode != "solo":
                pygame.draw.line(self.scene, (255, 220, 100),
                                 (x0 + pw // 2, y0), (x0 + pw // 2, y0 + ph), 2)
        else:
            pygame.draw.rect(self.scene, (20, 20, 30), (x0, y0, pw, ph))
            msg = getattr(self, "tracker_error", None) or "正在打开摄像头…"
            surf = self.font_small.render(msg, True, (230, 150, 150))
            self.scene.blit(surf, surf.get_rect(center=(x0 + pw / 2, y0 + ph / 2)))
        ok = self._both_tracked() if self.mode != "solo" else self.fighters[0].tracked
        pygame.draw.rect(self.scene, (90, 220, 120) if ok else (235, 90, 80),
                         (x0 - 2, y0 - 2, pw + 4, ph + 4), 3)
        if not ok and self.pip_surface is not None:
            missing = [f.name for i, f in enumerate(self.fighters)
                       if i not in self.bots and not f.tracked]
            if missing:
                surf = self.font_small.render(
                    "未检测到：" + "、".join(missing) + "（退后让上半身入画）",
                    True, (255, 200, 200))
                self.scene.blit(surf, surf.get_rect(center=(W / 2, y0 - 16)))

    def _draw_menu_overlay(self, now):
        title = self.font_huge.render("神拳对决", True, (255, 255, 255))
        shadow = self.font_huge.render("神拳对决", True, (120, 60, 200))
        rect = title.get_rect(center=(W / 2, H * 0.18))
        self.scene.blit(shadow, rect.move(5, 5))
        self.scene.blit(title, rect)
        lines = [
            "左边的人控制青影，右边的人控制赤焰，角色实时镜像你的动作",
            "快挥拳打中对方掉血 · 双手护脸格挡 · 左右移动进退",
            "气满后双手合拢蓄力再猛推 = 气功弹，对手可下蹲躲开",
            "60 秒一回合 · 三局两胜",
        ]
        for i, line in enumerate(lines):
            surf = self.font_small.render(line, True, (225, 225, 235))
            self.scene.blit(surf, surf.get_rect(center=(W / 2, H * 0.30 + i * 34)))

        if self.mode == "demo":
            return
        prompt = self.font_mid.render("双方同时举手 1 秒开始（或按空格）",
                                      True, (160, 255, 180))
        self.scene.blit(prompt, prompt.get_rect(center=(W / 2, H * 0.52)))
        # 双方准备进度环
        for idx, f in enumerate(self.fighters):
            cx = W * 0.30 if idx == 0 else W * 0.70
            cy = H * 0.62
            if idx in self.bots:
                status, col = "电脑就绪", (160, 255, 180)
            elif not f.tracked:
                status, col = "未入画", (235, 110, 100)
            elif self.ready_t[idx] > 0:
                status, col = "举手中…", (255, 230, 140)
            else:
                status, col = "已就绪，请举手", (200, 220, 255)
            surf = self.font_small.render(f"{f.name}：{status}", True, col)
            self.scene.blit(surf, surf.get_rect(center=(cx, cy)))
            if self.ready_t[idx] > 0:
                pygame.draw.arc(self.scene, (255, 230, 140),
                                (cx - 34, cy + 20, 68, 68),
                                math.pi / 2,
                                math.pi / 2 + self.ready_t[idx] * math.tau, 5)

    def _draw_match_end(self, now):
        if self.winner is None:
            return
        overlay = pygame.Surface((W, H))
        overlay.set_alpha(120)
        self.scene.blit(overlay, (0, 0))
        surf = self.font_huge.render(f"{self.winner.name} 获胜！", True,
                                     self.winner.color)
        pulse = 1 + 0.05 * math.sin(now * 5)
        img = pygame.transform.rotozoom(surf, 0, pulse)
        self.scene.blit(img, img.get_rect(center=(W / 2, H * 0.34)))
        score = self.font_mid.render(
            f"{self.fighters[0].wins} : {self.fighters[1].wins}", True,
            (255, 255, 255))
        self.scene.blit(score, score.get_rect(center=(W / 2, H * 0.46)))
        if now - self.state_t0 > 2.0 and self.mode != "demo":
            hint = self.font_mid.render("双方举手再战一场（或按 R）", True,
                                        (160, 255, 180))
            self.scene.blit(hint, hint.get_rect(center=(W / 2, H * 0.58)))

    def _draw(self, now):
        self.scene.blit(self.arena, (0, 0))
        for fb in self.fireballs:
            fb.draw(self.scene, now)
        for f in self.fighters:
            f.draw(self.scene, now)
        for p in self.particles:
            p.draw(self.scene, now)
        self.texts = [t for t in self.texts if t.draw(self.scene, now)]

        if self.state == MENU:
            self._draw_menu_overlay(now)
        else:
            self._draw_hud(now)
        if self.state == MATCH_END:
            self._draw_match_end(now)
        if self.paused:
            surf = self.font_big.render("已暂停（按 P 继续）", True,
                                        (255, 255, 255))
            self.scene.blit(surf, surf.get_rect(center=(W / 2, H / 2)))
        self._draw_pip()
        self.announcer.draw(self.scene, now)

        if self.flash > 0:
            white = pygame.Surface((W, H))
            white.fill((255, 250, 240))
            white.set_alpha(int(190 * self.flash))
            self.scene.blit(white, (0, 0))

        ox = oy = 0
        if now < self.shake_until:
            ox = int(random.uniform(-self.shake_amp, self.shake_amp))
            oy = int(random.uniform(-self.shake_amp, self.shake_amp))
            self.screen.fill((0, 0, 0))
        self.screen.blit(self.scene, (ox, oy))
        pygame.display.flip()


def main():
    parser = argparse.ArgumentParser(description="神拳对决：双人体感格斗")
    parser.add_argument("--camera", type=int, default=0, help="摄像头编号")
    parser.add_argument("--solo", action="store_true", help="单人打电脑")
    parser.add_argument("--demo", action="store_true",
                        help="演示模式：两个电脑对打（不开摄像头）")
    args = parser.parse_args()
    mode = "demo" if args.demo else ("solo" if args.solo else "versus")
    Game(mode=mode, camera_index=args.camera).run()


if __name__ == "__main__":
    main()
