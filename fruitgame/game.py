"""体感切水果 主程序。

摄像头追踪双手，快速挥手产生"手刀"，切开从屏幕底部喷出的西瓜得分；
切到炸弹掉血，血量耗尽游戏结束。全程无需键盘：菜单和结算界面
也是靠挥手切开屏幕上的西瓜来操作。

按键（可选）：Esc 返回/退出，P 暂停，F 全屏，--mouse 参数用鼠标代替手（调试）。
"""

import argparse
import json
import math
import os
import random
import sys
import time
from collections import deque
from pathlib import Path

import pygame

# 支持 `python fruitgame/game.py` 直接运行（等价于 `python -m fruitgame`）
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fruitgame import sfx
from fruitgame import sprites

W, H = 1280, 720
FPS = 60
GRAVITY = 1350.0            # px/s²
SLICE_SPEED = 850.0         # 手移动快于此速度（px/s）才算"挥刀"
TRAIL_LIFE = 0.28           # 刀光轨迹保留时长（秒）
HAND_COLORS = {"a": (90, 220, 255), "b": (255, 175, 70), "m": (190, 255, 120)}
MAX_HP = 3

SCORE_MELON = 10
SCORE_GOLD = 50

HIGHSCORE_PATH = Path(__file__).parent / "highscore.json"

MENU, PLAYING, GAME_OVER = "menu", "playing", "game_over"


# ---------------------------------------------------------------- 字体

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


# ---------------------------------------------------------------- 实体

class Fruit:
    def __init__(self, kind, sprite, x, y, vx, vy, radius, spark_offset=None):
        self.kind = kind          # "melon" / "gold" / "bomb"
        self.sprite = sprite
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.r = radius
        self.ang = random.uniform(0, 360)
        self.angv = random.uniform(-140, 140)
        self.spark_offset = spark_offset

    def update(self, dt):
        self.vy += GRAVITY * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.ang = (self.ang + self.angv * dt) % 360

    def draw(self, scene, now):
        img = pygame.transform.rotozoom(self.sprite, self.ang, 1.0)
        scene.blit(img, img.get_rect(center=(self.x, self.y)))
        if self.kind == "bomb":
            # 脉动的红色警示圈
            pulse = 6 + 3 * math.sin(now * 9)
            pygame.draw.circle(scene, (255, 70, 60), (int(self.x), int(self.y)),
                               int(self.r + pulse), 2)
            # 引信火花（随弹体旋转）
            a = math.radians(-self.ang)
            ox, oy = self.spark_offset
            sx = self.x + ox * math.cos(a) - oy * math.sin(a)
            sy = self.y + ox * math.sin(a) + oy * math.cos(a)
            for _ in range(3):
                jx = sx + random.uniform(-4, 4)
                jy = sy + random.uniform(-4, 4)
                col = random.choice(((255, 240, 160), (255, 190, 60), (255, 255, 255)))
                pygame.draw.circle(scene, col, (int(jx), int(jy)),
                                   random.randint(2, 4))


class Half:
    def __init__(self, sprite, x, y, vx, vy, ang):
        self.sprite = sprite
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.ang = ang
        self.angv = random.uniform(-90, 90)

    def update(self, dt):
        self.vy += GRAVITY * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.ang += self.angv * dt

    def draw(self, scene):
        img = pygame.transform.rotozoom(self.sprite, self.ang, 1.0)
        scene.blit(img, img.get_rect(center=(self.x, self.y)))


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "r0", "color", "t0", "life")

    def __init__(self, x, y, vx, vy, r, color, life):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.r0 = r
        self.color = color
        self.t0 = time.monotonic()
        self.life = life

    def update(self, dt):
        self.vy += GRAVITY * 0.8 * dt
        self.x += self.vx * dt
        self.y += self.vy * dt

    def draw(self, scene, now):
        frac = 1.0 - (now - self.t0) / self.life
        if frac <= 0:
            return
        r = max(1, int(self.r0 * frac))
        pygame.draw.circle(scene, self.color, (int(self.x), int(self.y)), r)


class FloatText:
    def __init__(self, surf, x, y, life=0.9, rise=52):
        self.surf = surf
        self.x, self.y = x, y
        self.t0 = time.monotonic()
        self.life = life
        self.rise = rise

    def draw(self, scene, now):
        frac = (now - self.t0) / self.life
        if frac >= 1:
            return False
        img = self.surf.copy()
        img.set_alpha(int(255 * (1 - frac ** 2)))
        scene.blit(img, img.get_rect(center=(self.x, self.y - self.rise * frac)))
        return True


# ---------------------------------------------------------------- 游戏

class Game:
    def __init__(self, camera_index=0, mouse_mode=False):
        pygame.mixer.pre_init(sfx.SR, -16, 1, 512)
        pygame.init()
        pygame.display.set_caption("体感切水果")
        self.screen = pygame.display.set_mode((W, H), pygame.SCALED)
        self.scene = pygame.Surface((W, H))
        self.clock = pygame.time.Clock()
        try:
            sfx.init()
        except pygame.error:
            pass  # 无音频设备也能玩

        font_path = _find_cjk_font()
        self.font_big = pygame.font.Font(font_path, 84)
        self.font_mid = pygame.font.Font(font_path, 44)
        self.font_small = pygame.font.Font(font_path, 28)

        self.mouse_mode = mouse_mode
        self.tracker = None
        if not mouse_mode:
            from fruitgame.tracker import HandTracker
            self.tracker = HandTracker(camera_index, (W, H))
            self.tracker.start()

        # 预生成素材
        self.spr_melon = {}
        for r in (46, 52, 58, 64):
            self.spr_melon[r] = (sprites.make_melon(r),
                                 sprites.make_melon_half(r))
        self.spr_gold = (sprites.make_melon(46, gold=True),
                         sprites.make_melon_half(46, gold=True))
        bomb_sprite, spark_off = sprites.make_bomb(44)
        self.spr_bomb = bomb_sprite
        self.bomb_spark_off = spark_off
        self.heart_on = sprites.make_heart(40, alive=True)
        self.heart_off = sprites.make_heart(40, alive=False)
        self.vignette = sprites.make_vignette((W, H))
        self.dark = pygame.Surface((W, H))
        self.dark.set_alpha(95)
        self.overlay_dark = pygame.Surface((W, H))
        self.overlay_dark.set_alpha(150)

        self.bg_surface = None
        self.bg_seq = -1

        self.best = self._load_best()
        self.state = MENU
        self.paused = False
        self.trails = {k: deque(maxlen=40) for k in ("a", "b", "m")}
        self.last_hand = {}          # 手 -> 上一个 (x, y, t)
        self.whoosh_gate = {}        # 手 -> 上次挥刀音效时间
        self.menu_melon_cut_at = None
        self._reset_round()

    # ---------------- 数据

    def _load_best(self):
        try:
            return int(json.loads(HIGHSCORE_PATH.read_text())["best"])
        except Exception:
            return 0

    def _save_best(self):
        try:
            HIGHSCORE_PATH.write_text(json.dumps({"best": self.best}))
        except OSError:
            pass

    def _reset_round(self):
        self.fruits = []
        self.halves = []
        self.particles = []
        self.texts = []
        self.score = 0
        self.hp = MAX_HP
        self.combo = 0
        self.last_slice_t = 0.0
        self.round_t0 = time.monotonic()
        self.next_spawn = self.round_t0 + 0.9
        self.flash = 0.0
        self.shake_until = 0.0
        self.new_record = False

    # ---------------- 主循环

    def run(self):
        running = True
        while running:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            now = time.monotonic()
            running = self._handle_events()
            blades = self._collect_blades(now)

            if self.state == PLAYING and not self.paused:
                self._update_playing(dt, now, blades)
            elif self.state == MENU:
                self._update_menu(now, blades)
            elif self.state == GAME_OVER:
                self._update_game_over(dt, now, blades)

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
                    if self.state == PLAYING:
                        self.state = MENU
                    else:
                        return False
                elif event.key == pygame.K_p and self.state == PLAYING:
                    self.paused = not self.paused
                elif event.key == pygame.K_f:
                    pygame.display.toggle_fullscreen()
                elif event.key == pygame.K_SPACE and self.state != PLAYING:
                    self._start_round()
                elif event.key == pygame.K_r and self.state == GAME_OVER:
                    self._start_round()
        return True

    def _start_round(self):
        self._reset_round()
        self.state = PLAYING
        self.paused = False
        sfx.play("start")

    # ---------------- 手部输入 → 刀刃线段

    def _collect_blades(self, now):
        """读取手部新位置，更新刀光轨迹，返回本帧的快速挥动线段。

        返回 [(p0, p1, speed), ...]，p 为 (x, y)。
        """
        points = {}
        if self.mouse_mode:
            mx, my = pygame.mouse.get_pos()
            points["m"] = (float(mx), float(my), now)
        elif self.tracker:
            _, _, hands, _ = self.tracker.get_state()
            for key in ("a", "b"):
                if hands.get(key):
                    points[key] = hands[key]

        blades = []
        for key, pt in points.items():
            prev = self.last_hand.get(key)
            if prev is not None and pt[2] > prev[2]:
                dt = pt[2] - prev[2]
                if dt < 0.25:  # 跟踪没断开
                    dist = math.hypot(pt[0] - prev[0], pt[1] - prev[1])
                    speed = dist / dt
                    if speed >= SLICE_SPEED and dist > 18:
                        blades.append(((prev[0], prev[1]), (pt[0], pt[1]), speed))
                        gate = self.whoosh_gate.get(key, 0)
                        if now - gate > 0.22 and dist > 55:
                            sfx.play("whoosh")
                            self.whoosh_gate[key] = now
                self.trails[key].append(pt)
            elif prev is None:
                self.trails[key].append(pt)
            self.last_hand[key] = pt
        # 手丢失时清掉记录，避免下次出现产生跨屏假线段
        for key in list(self.last_hand):
            if key not in points and now - self.last_hand[key][2] > 0.3:
                del self.last_hand[key]
        return blades

    @staticmethod
    def _seg_hits_circle(p0, p1, cx, cy, r):
        x0, y0 = p0
        x1, y1 = p1
        dx, dy = x1 - x0, y1 - y0
        len2 = dx * dx + dy * dy
        if len2 <= 1e-6:
            return math.hypot(cx - x0, cy - y0) <= r
        t = max(0.0, min(1.0, ((cx - x0) * dx + (cy - y0) * dy) / len2))
        px, py = x0 + t * dx, y0 + t * dy
        return math.hypot(cx - px, cy - py) <= r

    # ---------------- 生成

    def _spawn_wave(self, now):
        elapsed = now - self.round_t0
        # 难度曲线：间隔 1.35s → 0.55s（2 分钟拉满）
        k = min(1.0, elapsed / 120.0)
        base = 1.35 - 0.8 * k
        self.next_spawn = now + base * random.uniform(0.7, 1.3)

        count = 1
        if random.random() < 0.18 + 0.30 * k:
            count = random.randint(2, 2 + (2 if k > 0.5 else 1))
        p_bomb = 0.0 if elapsed < 8 else min(0.24, 0.10 + 0.10 * k)

        for _ in range(count):
            x = random.uniform(W * 0.12, W * 0.88)
            peak_y = H * random.uniform(0.12, 0.48)
            if random.random() < p_bomb:
                kind, sprite, r = "bomb", self.spr_bomb, 44
                spark = self.bomb_spark_off
            elif random.random() < 0.08:
                kind, sprite, r = "gold", self.spr_gold[0], 46
                spark = None
            else:
                r = random.choice(list(self.spr_melon))
                kind, sprite, spark = "melon", self.spr_melon[r][0], None
            y0 = H + r
            vy = -math.sqrt(2 * GRAVITY * (y0 - peak_y))
            vx = (W / 2 - x) * random.uniform(0.10, 0.30) + random.uniform(-70, 70)
            self.fruits.append(Fruit(kind, sprite, x, y0, vx, vy, r, spark))
        sfx.play("launch")

    # ---------------- 切割

    def _slice_fruit(self, fruit, blade, now):
        p0, p1, _speed = blade
        ang = math.degrees(math.atan2(-(p1[1] - p0[1]), p1[0] - p0[0]))
        if fruit.kind == "bomb":
            self._explode_bomb(fruit, now)
            return

        gold = fruit.kind == "gold"
        half_sprite = self.spr_gold[1] if gold else self.spr_melon[fruit.r][1]
        # 两个半瓜沿切线两侧分开
        perp = math.radians(ang + 90)
        px, py = math.cos(perp), -math.sin(perp)
        push = random.uniform(150, 230)
        for sgn, extra_ang in ((1, 0), (-1, 180)):
            self.halves.append(Half(
                half_sprite, fruit.x + px * sgn * 6, fruit.y + py * sgn * 6,
                fruit.vx * 0.6 + px * sgn * push,
                fruit.vy * 0.4 + py * sgn * push - 60,
                ang + extra_ang))

        juice = (255, 190, 60) if gold else (222, 52, 60)
        rind = (255, 220, 110) if gold else (40, 140, 60)
        for _ in range(24):
            a = random.uniform(0, math.tau)
            spd = random.uniform(80, 420)
            self.particles.append(Particle(
                fruit.x, fruit.y,
                math.cos(a) * spd + fruit.vx * 0.3,
                math.sin(a) * spd + fruit.vy * 0.25,
                random.uniform(3, 7), juice, random.uniform(0.4, 0.8)))
        for _ in range(6):
            a = random.uniform(0, math.tau)
            spd = random.uniform(120, 320)
            self.particles.append(Particle(
                fruit.x, fruit.y, math.cos(a) * spd, math.sin(a) * spd,
                random.uniform(2, 4), rind, random.uniform(0.3, 0.6)))

        points = SCORE_GOLD if gold else SCORE_MELON
        # 连击：短时间内连续切中
        if now - self.last_slice_t < 0.45:
            self.combo += 1
        else:
            self.combo = 1
        self.last_slice_t = now
        bonus = 0
        if self.combo >= 2:
            bonus = self.combo * 5
            surf = self.font_mid.render(f"{self.combo} 连击 +{bonus}", True,
                                        (255, 230, 120))
            self.texts.append(FloatText(surf, W / 2, H * 0.30, life=1.0, rise=60))
            sfx.play("ding")
        elif gold:
            sfx.play("ding")
        self.score += points + bonus

        color = (255, 215, 90) if gold else (255, 255, 255)
        surf = self.font_mid.render(f"+{points}", True, color)
        self.texts.append(FloatText(surf, fruit.x, fruit.y))
        sfx.play("splat")

    def _explode_bomb(self, fruit, now):
        sfx.play("explosion")
        sfx.play("hurt")
        self.flash = 1.0
        self.shake_until = now + 0.55
        self.hp -= 1
        for _ in range(40):
            a = random.uniform(0, math.tau)
            spd = random.uniform(120, 700)
            col = random.choice(((255, 200, 80), (255, 120, 40),
                                 (120, 120, 130), (70, 70, 78)))
            self.particles.append(Particle(
                fruit.x, fruit.y, math.cos(a) * spd, math.sin(a) * spd,
                random.uniform(3, 8), col, random.uniform(0.4, 0.9)))
        surf = self.font_mid.render("生命 -1", True, (255, 90, 90))
        self.texts.append(FloatText(surf, fruit.x, fruit.y, life=1.1))
        if self.hp <= 0:
            self.state = GAME_OVER
            self.game_over_t = now
            if self.score > self.best:
                self.best = self.score
                self.new_record = True
                self._save_best()
            sfx.play("game_over")

    # ---------------- 各状态更新

    def _update_playing(self, dt, now, blades):
        if now >= self.next_spawn:
            self._spawn_wave(now)

        for fruit in self.fruits:
            fruit.update(dt)
        for blade in blades:
            for fruit in self.fruits[:]:
                if self._seg_hits_circle(blade[0], blade[1],
                                         fruit.x, fruit.y, fruit.r + 16):
                    self.fruits.remove(fruit)
                    self._slice_fruit(fruit, blade, now)
                    if self.state != PLAYING:
                        return
        self.fruits = [f for f in self.fruits if f.y < H + 160]
        self._update_effects(dt, now)

    def _update_menu(self, now, blades):
        self._update_effects(1 / FPS, now)
        cx, cy = W / 2, H * 0.58 + 12 * math.sin(now * 2.2)
        self.menu_melon_pos = (cx, cy)
        for blade in blades:
            if self._seg_hits_circle(blade[0], blade[1], cx, cy, 80):
                sfx.play("splat")
                self._start_round()
                break

    def _update_game_over(self, dt, now, blades):
        for f in self.fruits:
            f.update(dt)
        self.fruits = [f for f in self.fruits if f.y < H + 160]
        self._update_effects(dt, now)
        if now - self.game_over_t < 1.2:   # 缓冲，防止爆炸后的余势误触重开
            return
        cx, cy = W / 2, H * 0.72
        self.retry_melon_pos = (cx, cy)
        for blade in blades:
            if self._seg_hits_circle(blade[0], blade[1], cx, cy, 66):
                sfx.play("splat")
                self._start_round()
                break

    def _update_effects(self, dt, now):
        for h in self.halves:
            h.update(dt)
        self.halves = [h for h in self.halves if h.y < H + 200]
        for p in self.particles:
            p.update(dt)
        self.particles = [p for p in self.particles
                          if now - p.t0 < p.life][-300:]
        self.flash = max(0.0, self.flash - dt * 2.4)

    # ---------------- 绘制

    def _draw_background(self, now):
        if self.tracker:
            frame, seq, _, error = self.tracker.get_state()
            if frame is not None and seq != self.bg_seq:
                self.bg_surface = pygame.image.frombuffer(
                    frame.tobytes(), (W, H), "RGB")
                self.bg_seq = seq
            if self.bg_surface is not None:
                self.scene.blit(self.bg_surface, (0, 0))
                self.scene.blit(self.dark, (0, 0))
            else:
                self.scene.fill((18, 20, 30))
                msg = error or "正在打开摄像头…"
                color = (255, 120, 120) if error else (200, 200, 210)
                surf = self.font_small.render(msg, True, color)
                self.scene.blit(surf, surf.get_rect(center=(W / 2, H / 2)))
        else:
            self.scene.fill((18, 20, 30))
        self.scene.blit(self.vignette, (0, 0))

    def _draw_trails(self, now):
        for key, trail in self.trails.items():
            pts = [p for p in trail if now - p[2] < TRAIL_LIFE]
            trail.clear()
            trail.extend(pts)
            if len(pts) < 2:
                continue
            color = HAND_COLORS[key]
            for i in range(len(pts) - 1):
                age = (now - pts[i + 1][2]) / TRAIL_LIFE
                fade = max(0.0, 1.0 - age)
                w_out = max(2, int(16 * fade))
                w_in = max(1, int(7 * fade))
                p0 = (int(pts[i][0]), int(pts[i][1]))
                p1 = (int(pts[i + 1][0]), int(pts[i + 1][1]))
                dim = tuple(int(c * 0.45) for c in color)
                pygame.draw.line(self.scene, dim, p0, p1, w_out)
                pygame.draw.line(self.scene, color, p0, p1, w_in)
            tip = pts[-1]
            pygame.draw.circle(self.scene, (255, 255, 255),
                               (int(tip[0]), int(tip[1])), 5)
            pygame.draw.circle(self.scene, color,
                               (int(tip[0]), int(tip[1])), 9, 2)

    def _draw_text_shadow(self, font, text, color, center):
        shadow = font.render(text, True, (0, 0, 0))
        shadow.set_alpha(150)
        surf = font.render(text, True, color)
        rect = surf.get_rect(center=center)
        self.scene.blit(shadow, rect.move(3, 3))
        self.scene.blit(surf, rect)
        return rect

    def _draw_hud(self, now):
        score_s = self.font_mid.render(f"得分 {self.score}", True, (255, 255, 255))
        sh = self.font_mid.render(f"得分 {self.score}", True, (0, 0, 0))
        sh.set_alpha(150)
        self.scene.blit(sh, (34, 26))
        self.scene.blit(score_s, (30, 22))
        best_s = self.font_small.render(f"最高 {self.best}", True, (220, 220, 160))
        self.scene.blit(best_s, (32, 80))
        for i in range(MAX_HP):
            img = self.heart_on if i < self.hp else self.heart_off
            self.scene.blit(img, (W - 60 - i * 50, 26))
        if self.paused:
            self.scene.blit(self.overlay_dark, (0, 0))
            self._draw_text_shadow(self.font_big, "已暂停", (255, 255, 255),
                                   (W / 2, H / 2 - 20))
            self._draw_text_shadow(self.font_small, "按 P 继续", (210, 210, 210),
                                   (W / 2, H / 2 + 60))

    def _draw_menu(self, now):
        self._draw_text_shadow(self.font_big, "体感切水果", (255, 255, 255),
                               (W / 2, H * 0.22))
        self._draw_text_shadow(self.font_small,
                               "站到摄像头前，快速挥手切开西瓜 · 小心炸弹会掉血",
                               (225, 225, 225), (W / 2, H * 0.33))
        if self.best:
            self._draw_text_shadow(self.font_small, f"最高纪录 {self.best}",
                                   (255, 225, 140), (W / 2, H * 0.40))
        cx, cy = getattr(self, "menu_melon_pos", (W / 2, H * 0.58))
        img = self.spr_melon[64][0]
        rot = pygame.transform.rotozoom(img, now * 20 % 360, 1.25)
        self.scene.blit(rot, rot.get_rect(center=(cx, cy)))
        self._draw_text_shadow(self.font_mid, "挥手切开它，开始！",
                               (160, 255, 170), (W / 2, H * 0.82))
        hint = "空格键也可以开始 · F 全屏 · Esc 退出"
        if self.mouse_mode:
            hint = "鼠标调试模式：快速划过即可切 · " + hint
        self._draw_text_shadow(self.font_small, hint, (170, 175, 185),
                               (W / 2, H * 0.92))

    def _draw_game_over(self, now):
        self.scene.blit(self.overlay_dark, (0, 0))
        self._draw_text_shadow(self.font_big, "游戏结束", (255, 110, 100),
                               (W / 2, H * 0.24))
        self._draw_text_shadow(self.font_mid, f"本局得分  {self.score}",
                               (255, 255, 255), (W / 2, H * 0.40))
        if self.new_record:
            pulse = 1 + 0.06 * math.sin(now * 6)
            surf = self.font_mid.render("新纪录！", True, (255, 225, 120))
            surf = pygame.transform.rotozoom(surf, 0, pulse)
            self.scene.blit(surf, surf.get_rect(center=(W / 2, H * 0.50)))
        else:
            self._draw_text_shadow(self.font_small, f"最高纪录 {self.best}",
                                   (225, 225, 160), (W / 2, H * 0.50))
        if now - self.game_over_t >= 1.2:
            cx, cy = W / 2, H * 0.72
            img = self.spr_melon[52][0]
            rot = pygame.transform.rotozoom(img, now * 24 % 360, 1.0)
            self.scene.blit(rot, rot.get_rect(center=(cx, cy)))
            self._draw_text_shadow(self.font_small, "挥手切开西瓜再来一局（或按 R）",
                                   (170, 255, 180), (W / 2, H * 0.86))

    def _draw(self, now):
        self._draw_background(now)
        for h in self.halves:
            h.draw(self.scene)
        for f in self.fruits:
            f.draw(self.scene, now)
        for p in self.particles:
            p.draw(self.scene, now)
        self._draw_trails(now)
        self.texts = [t for t in self.texts if t.draw(self.scene, now)]

        if self.state == PLAYING:
            self._draw_hud(now)
        elif self.state == MENU:
            self._draw_menu(now)
        elif self.state == GAME_OVER:
            self._draw_hud(now)
            self._draw_game_over(now)

        if self.flash > 0:
            white = pygame.Surface((W, H))
            white.fill((255, 250, 235))
            white.set_alpha(int(200 * self.flash))
            self.scene.blit(white, (0, 0))

        # 爆炸屏幕震动
        ox = oy = 0
        if now < self.shake_until:
            amp = 16 * (self.shake_until - now) / 0.55
            ox = int(random.uniform(-amp, amp))
            oy = int(random.uniform(-amp, amp))
            self.screen.fill((0, 0, 0))
        self.screen.blit(self.scene, (ox, oy))
        pygame.display.flip()


def main():
    parser = argparse.ArgumentParser(description="体感切水果")
    parser.add_argument("--camera", type=int, default=0, help="摄像头编号（默认 0）")
    parser.add_argument("--mouse", action="store_true",
                        help="鼠标调试模式，不开摄像头，用鼠标快速划过来切")
    args = parser.parse_args()
    Game(camera_index=args.camera, mouse_mode=args.mouse).run()


if __name__ == "__main__":
    main()
