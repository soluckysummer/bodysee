"""《霓虹疾跑》主程序：三轨体感跑酷、道具与渐进难度。"""

import argparse
import json
import math
import os
import random
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import pygame

from runnergame import sfx, sprites
from runnergame.world import (BARRIER, BOOST, CRATE, DOUBLE, LANES, MAGNET,
                              OVERHEAD, POWER_KINDS, SHIELD, TRAIN, WavePlanner,
                              obstacle_avoided, project, spawn_interval, speed_for,
                              validate_wave)

W, H = 1280, 720
FPS = 60

NAVY = (5, 8, 24)
CYAN = (85, 231, 255)
ORANGE = (255, 173, 66)
PURPLE = (181, 124, 255)
GOLD = (255, 216, 107)
RED = (255, 92, 112)
GREEN = (95, 245, 165)
WHITE = (242, 247, 255)
MUTED = (164, 179, 205)

MENU = "menu"
CALIBRATING = "calibrating"
COUNTDOWN = "countdown"
PLAYING = "playing"
RESULTS = "results"

BEST_PATH = Path(__file__).parent / "highscore.json"


def _find_cjk_font():
    candidates = (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyh.ttf",
        "C:/Windows/Fonts/simhei.ttf",
    )
    for path in candidates:
        if os.path.exists(path):
            return path
    for name in ("PingFang SC", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC"):
        path = pygame.font.match_font(name)
        if path:
            return path
    return None


@dataclass
class Debris:
    x: float
    y: float
    vx: float
    vy: float
    color: tuple
    born: float
    life: float = 0.65

    def draw(self, surface, now):
        age = (now - self.born) / self.life
        if age >= 1:
            return False
        elapsed = now - self.born
        x = self.x + self.vx * elapsed
        y = self.y + self.vy * elapsed + 220 * elapsed * elapsed
        size = max(2, int(8 * (1 - age)))
        pygame.draw.rect(surface, (*self.color, int(230 * (1 - age))),
                         (int(x), int(y), size, size))
        return True


@dataclass
class FloatText:
    text: str
    color: tuple
    x: float
    y: float
    born: float
    life: float = 0.9

    def draw(self, surface, font, now):
        age = (now - self.born) / self.life
        if age >= 1:
            return False
        image = font.render(self.text, True, self.color)
        image.set_alpha(int(255 * (1 - age * age)))
        surface.blit(image, image.get_rect(center=(self.x, self.y - age * 42)))
        return True


class Game:
    def __init__(self, camera_index=0, debug_mode=False, reduced_motion=False,
                 smoke_test=False):
        pygame.mixer.pre_init(sfx.SR, -16, 2, 512)
        pygame.init()
        pygame.display.set_caption("霓虹疾跑")
        self.screen = pygame.display.set_mode((W, H), pygame.SCALED)
        self.scene = pygame.Surface((W, H))
        self.clock = pygame.time.Clock()
        try:
            sfx.init()
        except pygame.error:
            pass

        font_path = _find_cjk_font()
        self.font_title = pygame.font.Font(font_path, 76)
        self.font_large = pygame.font.Font(font_path, 50)
        self.font_medium = pygame.font.Font(font_path, 32)
        self.font_small = pygame.font.Font(font_path, 23)
        self.font_tiny = pygame.font.Font(font_path, 18)

        self.debug_mode = debug_mode
        self.reduced_motion = reduced_motion
        self.smoke_test = smoke_test
        self.tracker = None
        if not debug_mode:
            from runnergame.tracker import BodyTracker
            self.tracker = BodyTracker(camera_index, (W, H))
            self.tracker.start()

        self.city = sprites.make_city((W, H))
        self.scanlines = sprites.make_scanlines((W, H))
        self.vignette = sprites.make_vignette((W, H))
        self.veil = pygame.Surface((W, H))
        self.veil.fill((3, 7, 23))
        self.veil.set_alpha(172)
        self.bg_surface = None
        self.bg_seq = -1
        self.points = {}
        self.tracker_error = None
        self.state = MENU
        self.state_started = time.monotonic()
        self.hold_progress = 0.0
        self.calibration_samples = []
        self.baseline = None
        self.best = self._load_best()
        self.paused = False
        self.pause_started = 0.0
        self.debug_duck = False
        self.hands_up_latch = False
        self.last_wrists = {}
        self.last_lane_change = 0.0
        self.was_ducking = False
        self._reset_round()

    def _load_best(self):
        try:
            return int(json.loads(BEST_PATH.read_text(encoding="utf-8"))["best"])
        except (OSError, ValueError, KeyError, TypeError):
            return 0

    def _save_best(self):
        try:
            BEST_PATH.write_text(json.dumps({"best": self.best}), encoding="utf-8")
        except OSError:
            pass

    def _reset_round(self):
        self.planner = WavePlanner()
        self.obstacles = []
        self.coins = []
        self.powerups = []
        self.debris = []
        self.float_texts = []
        self.player_lane = 1
        self.visual_lane = 1.0
        self.lives = 3
        self.shields = 0
        self.coins_collected = 0
        self.combo = 0
        self.max_combo = 0
        self.distance = 0.0
        self.bonus_score = 0
        self.jump_started = -10.0
        self.jump_until = -10.0
        self.punch_until = -10.0
        self.magnet_until = -10.0
        self.boost_until = -10.0
        self.double_until = -10.0
        self.invulnerable_until = -10.0
        self.damage_until = -10.0
        self.play_started = 0.0
        self.next_wave = 0.8
        self.debug_duck = False
        self.last_wrists = {}

    @property
    def score(self):
        return self.bonus_score + int(self.distance * 2)

    def run(self):
        running = True
        frames = 0
        while running:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            now = time.monotonic()
            running = self._handle_events(now)
            self._read_tracker()
            self._update(dt, now)
            self._draw(now)
            frames += 1
            if self.smoke_test and frames >= 6:
                running = False
        sfx.stop_music(0)
        if self.tracker:
            self.tracker.stop()
            self.tracker.join(timeout=1.0)
        pygame.quit()

    def _handle_events(self, now):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self.state == MENU:
                        return False
                    sfx.stop_music()
                    self._set_state(MENU, now)
                elif event.key == pygame.K_f:
                    pygame.display.toggle_fullscreen()
                elif event.key == pygame.K_p and self.state == PLAYING:
                    self._toggle_pause(now)
                elif event.key == pygame.K_SPACE:
                    if self.state in (MENU, RESULTS):
                        self._begin_calibration(now)
                    elif self.state == PLAYING:
                        self._jump(now)
                elif self.state == PLAYING and event.key == pygame.K_a:
                    self._change_lane(-1, now)
                elif self.state == PLAYING and event.key == pygame.K_d:
                    self._change_lane(1, now)
                elif self.state == PLAYING and event.key == pygame.K_s:
                    self.debug_duck = True
                elif self.state == PLAYING and event.key == pygame.K_k:
                    self._punch(now)
            elif event.type == pygame.KEYUP and event.key == pygame.K_s:
                self.debug_duck = False
            elif event.type == pygame.MOUSEBUTTONDOWN and self.state in (MENU, RESULTS):
                self._begin_calibration(now)
        return True

    def _toggle_pause(self, now):
        self.paused = not self.paused
        if self.paused:
            self.pause_started = now
            pygame.mixer.pause()
        else:
            paused_for = now - self.pause_started
            self.play_started += paused_for
            self.next_wave += paused_for
            for timer in ("jump_started", "jump_until", "punch_until", "magnet_until",
                          "boost_until", "double_until", "invulnerable_until",
                          "damage_until"):
                setattr(self, timer, getattr(self, timer) + paused_for)
            pygame.mixer.unpause()

    def _read_tracker(self):
        if not self.tracker:
            return
        frame, seq, points, error = self.tracker.get_state()
        self.points = points
        self.tracker_error = error
        if frame is not None and seq != self.bg_seq:
            self.bg_surface = pygame.image.frombuffer(frame.tobytes(), (W, H), "RGB")
            self.bg_seq = seq

    def _set_state(self, state, now):
        self.state = state
        self.state_started = now
        self.hold_progress = 0.0
        self.paused = False
        pygame.mixer.unpause()

    def _begin_calibration(self, now):
        self._reset_round()
        self.calibration_samples = []
        if self.debug_mode:
            self.baseline = {"shoulder_y": H * 0.37, "torso": H * 0.22,
                             "shoulder_width": W * 0.17, "lean": 0.0}
            self._set_state(COUNTDOWN, now)
        else:
            self._set_state(CALIBRATING, now)

    def _update(self, dt, now):
        if self.state in (MENU, RESULTS):
            self._update_hold(dt, now)
        elif self.state == CALIBRATING:
            self._update_calibration(dt, now)
        elif self.state == COUNTDOWN and now - self.state_started >= 3.0:
            self._set_state(PLAYING, now)
            self.play_started = now
            self.next_wave = now + 1.0
            sfx.start_music()
            sfx.play("start")
        elif self.state == PLAYING and not self.paused:
            self._update_playing(dt, now)
        self.debris = [item for item in self.debris if now - item.born < item.life][-260:]
        self.float_texts = [item for item in self.float_texts
                           if now - item.born < item.life][-10:]

    def _update_hold(self, dt, now):
        if self.debug_mode:
            return
        if self._hands_overhead():
            self.hold_progress = min(1.0, self.hold_progress + dt)
            if self.hold_progress >= 1.0:
                self._begin_calibration(now)
        else:
            self.hold_progress = max(0.0, self.hold_progress - dt * 2.2)

    def _hands_overhead(self):
        names = ("left_wrist", "right_wrist", "left_shoulder", "right_shoulder")
        if not all(name in self.points for name in names):
            return False
        shoulder_y = (self.points["left_shoulder"][1]
                      + self.points["right_shoulder"][1]) / 2
        return (self.points["left_wrist"][1] < shoulder_y - 30
                and self.points["right_wrist"][1] < shoulder_y - 30)

    def _update_calibration(self, dt, now):
        names = ("left_shoulder", "right_shoulder", "left_hip", "right_hip",
                 "left_wrist", "right_wrist")
        if not all(name in self.points for name in names):
            self.hold_progress = max(0.0, self.hold_progress - dt)
            return
        sx = (self.points["left_shoulder"][0] + self.points["right_shoulder"][0]) / 2
        sy = (self.points["left_shoulder"][1] + self.points["right_shoulder"][1]) / 2
        hx = (self.points["left_hip"][0] + self.points["right_hip"][0]) / 2
        hy = (self.points["left_hip"][1] + self.points["right_hip"][1]) / 2
        width = abs(self.points["left_shoulder"][0] - self.points["right_shoulder"][0])
        torso = hy - sy
        if torso < 45 or width < 35:
            self.hold_progress = max(0.0, self.hold_progress - dt)
            return
        self.calibration_samples.append((sy, torso, width, sx - hx))
        self.hold_progress = min(1.0, self.hold_progress + dt / 2.0)
        if self.hold_progress >= 1.0 and len(self.calibration_samples) >= 12:
            self.baseline = {
                "shoulder_y": statistics.median(row[0] for row in self.calibration_samples),
                "torso": statistics.median(row[1] for row in self.calibration_samples),
                "shoulder_width": statistics.median(row[2] for row in self.calibration_samples),
                "lean": statistics.median(row[3] for row in self.calibration_samples),
            }
            self._set_state(COUNTDOWN, now)

    def _update_playing(self, dt, now):
        elapsed = now - self.play_started
        boosting = now < self.boost_until
        speed = speed_for(elapsed) * (1.34 if boosting else 1.0)
        multiplier = 2 if now < self.double_until else 1
        self.distance += speed * dt * 40 * multiplier
        self.visual_lane += (self.player_lane - self.visual_lane) * min(1.0, dt * 10)
        self._update_pose_input(now)

        if now >= self.next_wave:
            obstacles, coins, power, _safe_lane = self.planner.make_wave(elapsed)
            self.obstacles.extend(obstacles)
            self.coins.extend(coins)
            if power:
                self.powerups.append(power)
            jitter = random.uniform(0.92, 1.10)
            self.next_wave = now + spawn_interval(elapsed) * jitter

        for obstacle in self.obstacles:
            obstacle.progress += speed * dt
            if obstacle.progress >= 0.58 and not obstacle.warned:
                obstacle.warned = True
                pan = (obstacle.lane - 1) * 0.65
                sfx.play("warning", pan, 0.35)
            if obstacle.progress >= 0.86 and not obstacle.checked:
                obstacle.checked = True
                self._check_obstacle(obstacle, now, boosting)
                if self.state != PLAYING:
                    return
        for coin in self.coins:
            coin.progress += speed * dt
            if not coin.collected and coin.progress >= 0.38:
                magnet = now < self.magnet_until
                near_player = coin.progress >= 0.79 and coin.lane == self.player_lane
                if magnet or near_player:
                    self._collect_coin(coin, now)
        for power in self.powerups:
            power.progress += speed * dt
            if (not power.collected and power.progress >= 0.78
                    and power.lane == self.player_lane):
                self._collect_power(power, now)

        self.obstacles = [obj for obj in self.obstacles if obj.progress < 1.08]
        self.coins = [coin for coin in self.coins
                      if not coin.collected and coin.progress < 1.08]
        self.powerups = [power for power in self.powerups
                         if not power.collected and power.progress < 1.08]
        sfx.update_music(self.combo, boosting)

    def _update_pose_input(self, now):
        if self.debug_mode or not self.baseline:
            return
        names = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")
        if all(name in self.points for name in names):
            sx = (self.points["left_shoulder"][0] + self.points["right_shoulder"][0]) / 2
            hx = (self.points["left_hip"][0] + self.points["right_hip"][0]) / 2
            lean = sx - hx - self.baseline["lean"]
            threshold = max(24.0, self.baseline["shoulder_width"] * 0.17)
            if lean < -threshold:
                self._change_lane(-1, now)
            elif lean > threshold:
                self._change_lane(1, now)

        hands_up = self._hands_overhead()
        if hands_up and not self.hands_up_latch:
            self._jump(now)
        self.hands_up_latch = hands_up

        ducking = self._is_ducking()
        if ducking and not self.was_ducking:
            sfx.play("slide")
        self.was_ducking = ducking

        fastest = 0.0
        for name in ("left_wrist", "right_wrist"):
            point = self.points.get(name)
            previous = self.last_wrists.get(name)
            if point and previous and point[2] > previous[2]:
                delta = point[2] - previous[2]
                fastest = max(fastest, math.dist(point[:2], previous[:2]) / delta)
            if point:
                self.last_wrists[name] = point
        if fastest > 820 and not hands_up:
            self._punch(now)

    def _change_lane(self, direction, now):
        if now - self.last_lane_change < 0.43:
            return
        new_lane = max(0, min(2, self.player_lane + direction))
        if new_lane != self.player_lane:
            self.player_lane = new_lane
            self.last_lane_change = now
            sfx.play("move", (new_lane - 1) * 0.65)

    def _jump(self, now):
        if now < self.jump_until - 0.18:
            return
        self.jump_started = now
        self.jump_until = now + 0.88
        sfx.play("jump")

    def _punch(self, now):
        if now < self.punch_until:
            return
        self.punch_until = now + 0.28
        sfx.play("punch", (self.player_lane - 1) * 0.45)

    def _is_ducking(self):
        if self.debug_mode:
            return self.debug_duck
        if not self.baseline:
            return False
        names = ("left_shoulder", "right_shoulder")
        if not all(name in self.points for name in names):
            return False
        shoulder_y = sum(self.points[name][1] for name in names) / 2
        return shoulder_y - self.baseline["shoulder_y"] > max(
            38.0, self.baseline["torso"] * 0.28)

    def _check_obstacle(self, obstacle, now, boosting):
        if obstacle.lane != self.player_lane:
            self._successful_dodge(obstacle, now)
            return
        if boosting:
            self._smash(obstacle, now)
            return
        avoided = obstacle_avoided(
            obstacle.kind, jumping=now < self.jump_until,
            ducking=self._is_ducking(), punching=now < self.punch_until)
        if avoided:
            self._successful_dodge(obstacle, now)
            if obstacle.kind == CRATE:
                self._smash(obstacle, now, award=False)
        else:
            self._take_hit(obstacle, now)

    def _successful_dodge(self, obstacle, now):
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        award = 35 * min(5, 1 + self.combo // 8)
        if now < self.double_until:
            award *= 2
        self.bonus_score += award
        if obstacle.lane == self.player_lane:
            x, y, _ = project(obstacle.lane, 0.88, W, H)
            self.float_texts.append(FloatText(f"闪避 +{award}", CYAN, x, y - 80, now))

    def _smash(self, obstacle, now, award=True):
        x, y, _ = project(obstacle.lane, 0.88, W, H)
        if award:
            self.combo += 1
            self.max_combo = max(self.max_combo, self.combo)
            self.bonus_score += 90 * (2 if now < self.double_until else 1)
        self._burst(x, y - 30, ORANGE, now, 24)
        self.float_texts.append(FloatText("击碎", GOLD, x, y - 100, now))
        sfx.play("smash", (obstacle.lane - 1) * 0.6)

    def _take_hit(self, obstacle, now):
        if now < self.invulnerable_until:
            return
        self.invulnerable_until = now + 1.35
        self.damage_until = now + 0.55
        self.combo = 0
        x, y, _ = project(obstacle.lane, 0.88, W, H)
        if self.shields:
            self.shields -= 1
            self._burst(x, y - 30, CYAN, now, 24)
            self.float_texts.append(FloatText("护盾抵挡", CYAN, x, y - 100, now, 1.1))
            sfx.play("shield")
            return
        self.lives -= 1
        self._burst(x, y - 30, RED, now, 28)
        self.float_texts.append(FloatText("碰撞", RED, x, y - 100, now))
        sfx.play("hit")
        if self.lives <= 0:
            self._finish(now)

    def _collect_coin(self, coin, now):
        coin.collected = True
        self.coins_collected += 1
        chain = min(5, self.coins_collected % 6)
        value = 10 * (2 if now < self.double_until else 1)
        self.bonus_score += value
        x, y, _ = project(coin.lane, min(0.92, coin.progress), W, H)
        self._burst(x, y, GOLD, now, 5)
        sfx.play(f"coin{chain}", (coin.lane - 1) * 0.55, 0.46)

    def _collect_power(self, power, now):
        power.collected = True
        label = ""
        if power.kind == SHIELD:
            self.shields = min(2, self.shields + 1)
            label = "能量护盾"
        elif power.kind == MAGNET:
            self.magnet_until = now + 8.0
            label = "金币磁铁"
        elif power.kind == BOOST:
            self.boost_until = now + 6.5
            self.invulnerable_until = max(self.invulnerable_until, self.boost_until)
            label = "极速滑板"
        elif power.kind == DOUBLE:
            self.double_until = now + 9.0
            label = "双倍积分"
        x, y, _ = project(power.lane, power.progress, W, H)
        self._burst(x, y, GREEN, now, 22)
        self.float_texts.append(FloatText(label, GREEN, x, y - 75, now, 1.2))
        sfx.play("power")

    def _finish(self, now):
        if self.state != PLAYING:
            return
        sfx.stop_music()
        sfx.play("game_over")
        if self.score > self.best:
            self.best = self.score
            self._save_best()
        self._set_state(RESULTS, now)

    def _burst(self, x, y, color, now, count):
        if self.reduced_motion:
            count = min(6, count)
        for index in range(count):
            angle = index / max(1, count) * math.tau
            speed = 70 + (index % 6) * 35
            self.debris.append(Debris(x, y, math.cos(angle) * speed,
                                      math.sin(angle) * speed, color, now))

    # ------------------------------------------------------------------ draw

    def _draw(self, now):
        speed = 0.11
        if self.state == PLAYING:
            speed = speed_for(now - self.play_started)
        self._draw_background(now)
        self._draw_road(now, speed)
        self._draw_body_aura(now)
        if self.state == PLAYING:
            self._draw_entities(now)
            self._draw_runner(now)
            self._draw_hud(now)
        for item in self.debris:
            item.draw(self.scene, now)
        for item in self.float_texts:
            item.draw(self.scene, self.font_small, now)
        if self.state == MENU:
            self._draw_menu(now)
        elif self.state == CALIBRATING:
            self._draw_calibration()
        elif self.state == COUNTDOWN:
            self._draw_countdown(now)
        elif self.state == RESULTS:
            self._draw_results()
        if self.state == PLAYING and self.paused:
            self._draw_pause()
        if now < self.damage_until:
            alpha = int(105 * (self.damage_until - now) / 0.55)
            border = pygame.Surface((W, H), pygame.SRCALPHA)
            pygame.draw.rect(border, (*RED, alpha), (0, 0, W, H), 28)
            self.scene.blit(border, (0, 0))
        self.screen.blit(self.scene, (0, 0))
        pygame.display.flip()

    def _draw_background(self, now):
        if self.bg_surface is not None:
            self.scene.blit(self.bg_surface, (0, 0))
            self.scene.blit(self.veil, (0, 0))
        else:
            self.scene.fill(NAVY)
        self.scene.blit(self.city, (0, 0))
        if not self.reduced_motion:
            self.scanlines.set_alpha(85)
            self.scene.blit(self.scanlines, (0, 0))
        self.scene.blit(self.vignette, (0, 0))

    def _draw_road(self, now, speed):
        horizon = (W // 2, int(H * 0.235))
        road = ((horizon[0] - 25, horizon[1]), (horizon[0] + 25, horizon[1]),
                (W - 92, H), (92, H))
        pygame.draw.polygon(self.scene, (9, 15, 38), road)
        pygame.draw.lines(self.scene, CYAN, False, (road[0], road[3]), 3)
        pygame.draw.lines(self.scene, ORANGE, False, (road[1], road[2]), 3)
        for boundary in (0.5, 1.5):
            far_x, far_y, _ = project(boundary, 0.0, W, H)
            near_x, near_y, _ = project(boundary, 1.05, W, H)
            pygame.draw.line(self.scene, (79, 91, 132), (far_x, far_y),
                             (near_x, near_y), 2)
        line_count = 7 if self.reduced_motion else 12
        phase = (now * speed * 2.6) % 1.0
        for index in range(line_count):
            progress = (index / line_count + phase) % 1.0
            left_x, y, _ = project(-0.65, progress, W, H)
            right_x, _, _ = project(2.65, progress, W, H)
            alpha_color = (43, 55, 91) if progress < 0.68 else (65, 78, 119)
            pygame.draw.line(self.scene, alpha_color, (left_x, y), (right_x, y),
                             max(1, int(progress * 3)))

    def _draw_body_aura(self, now):
        if not self.points:
            return
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        bones = (("left_shoulder", "right_shoulder"),
                 ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
                 ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
                 ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"),
                 ("left_hip", "right_hip"), ("left_hip", "left_knee"),
                 ("right_hip", "right_knee"))
        for first, second in bones:
            if first in self.points and second in self.points:
                pygame.draw.line(overlay, (*CYAN, 62), self.points[first][:2],
                                 self.points[second][:2], 4)
        self.scene.blit(overlay, (0, 0))

    def _draw_entities(self, now):
        items = [(coin.progress, "coin", coin) for coin in self.coins if coin.progress >= 0]
        items += [(power.progress, "power", power) for power in self.powerups
                  if power.progress >= 0]
        items += [(obj.progress, "obstacle", obj) for obj in self.obstacles
                  if obj.progress >= 0]
        for _progress, category, item in sorted(items, key=lambda row: row[0]):
            if category == "coin":
                self._draw_coin(item, now)
            elif category == "power":
                self._draw_power(item, now)
            else:
                self._draw_obstacle(item, now)

    def _draw_obstacle(self, obstacle, now):
        x, y, scale = project(obstacle.lane, obstacle.progress, W, H)
        if obstacle.kind == BARRIER:
            w, h = int(145 * scale), int(76 * scale)
            rect = pygame.Rect(0, 0, w, h)
            rect.midbottom = (x, y)
            pygame.draw.rect(self.scene, ORANGE, rect, border_radius=max(2, int(8 * scale)))
            pygame.draw.rect(self.scene, (54, 29, 31), rect.inflate(-w * 0.12, -h * 0.28),
                             border_radius=max(2, int(5 * scale)))
            for offset in (-0.26, 0.0, 0.26):
                stripe_x = rect.centerx + int(w * offset)
                pygame.draw.line(self.scene, GOLD, (stripe_x - w * 0.08, rect.top + 5),
                                 (stripe_x + w * 0.08, rect.bottom - 5), max(2, int(7 * scale)))
        elif obstacle.kind == OVERHEAD:
            w, h = int(170 * scale), int(178 * scale)
            thickness = max(4, int(18 * scale))
            left = int(x - w / 2)
            pygame.draw.line(self.scene, PURPLE, (left, y), (left, y - h), thickness)
            pygame.draw.line(self.scene, PURPLE, (left + w, y), (left + w, y - h), thickness)
            pygame.draw.line(self.scene, GOLD, (left, y - h), (left + w, y - h), thickness)
        elif obstacle.kind == TRAIN:
            w, h = int(180 * scale), int(260 * scale)
            rect = pygame.Rect(0, 0, w, h)
            rect.midbottom = (x, y)
            pygame.draw.rect(self.scene, (33, 62, 108), rect,
                             border_radius=max(3, int(13 * scale)))
            pygame.draw.rect(self.scene, CYAN, rect, max(2, int(4 * scale)),
                             border_radius=max(3, int(13 * scale)))
            window = pygame.Rect(rect.left + w * 0.18, rect.top + h * 0.18,
                                 w * 0.64, h * 0.30)
            pygame.draw.rect(self.scene, (139, 226, 244), window,
                             border_radius=max(2, int(6 * scale)))
            pygame.draw.circle(self.scene, RED, (rect.left + int(w * 0.25),
                                                  rect.bottom - int(h * 0.15)),
                               max(2, int(8 * scale)))
            pygame.draw.circle(self.scene, RED, (rect.right - int(w * 0.25),
                                                  rect.bottom - int(h * 0.15)),
                               max(2, int(8 * scale)))
        elif obstacle.kind == CRATE:
            size = int(105 * scale)
            rect = pygame.Rect(0, 0, size, size)
            rect.midbottom = (x, y)
            pygame.draw.rect(self.scene, (138, 82, 42), rect)
            pygame.draw.rect(self.scene, GOLD, rect, max(2, int(5 * scale)))
            pygame.draw.line(self.scene, GOLD, rect.topleft, rect.bottomright,
                             max(2, int(6 * scale)))
            pygame.draw.line(self.scene, GOLD, rect.topright, rect.bottomleft,
                             max(2, int(6 * scale)))
        if obstacle.progress > 0.50 and not obstacle.checked:
            label = {BARRIER: "跳", OVERHEAD: "蹲", TRAIN: "换道", CRATE: "挥击"}[
                obstacle.kind]
            image = self.font_tiny.render(label, True, WHITE)
            self.scene.blit(image, image.get_rect(center=(x, y - max(45, 150 * scale))))

    def _draw_coin(self, coin, now):
        x, y, scale = project(coin.lane, coin.progress, W, H)
        radius = max(3, int(19 * scale))
        width = max(2, int(radius * (0.55 + 0.35 * abs(math.sin(now * 5)))))
        pygame.draw.ellipse(self.scene, GOLD,
                            (int(x - width), int(y - radius * 1.8), width * 2, radius * 2),
                            max(2, int(4 * scale)))

    def _draw_power(self, power, now):
        x, y, scale = project(power.lane, power.progress, W, H)
        radius = max(7, int(34 * scale))
        pulse = 1.0 if self.reduced_motion else 1 + 0.08 * math.sin(now * 6)
        radius = int(radius * pulse)
        points = ((x, y - radius * 2), (x + radius, y - radius),
                  (x, y), (x - radius, y - radius))
        pygame.draw.polygon(self.scene, (20, 54, 68), points)
        pygame.draw.polygon(self.scene, GREEN, points, max(2, int(4 * scale)))
        labels = {SHIELD: "盾", MAGNET: "磁", BOOST: "冲", DOUBLE: "×2"}
        image = self.font_tiny.render(labels[power.kind], True, WHITE)
        if scale < 0.5:
            image = pygame.transform.smoothscale(image, (max(5, int(image.get_width() * scale * 2)),
                                                          max(5, int(image.get_height() * scale * 2))))
        self.scene.blit(image, image.get_rect(center=(x, y - radius)))

    def _draw_runner(self, now):
        x, y, scale = project(self.visual_lane, 0.88, W, H)
        jump = 0.0
        if now < self.jump_until:
            phase = max(0.0, min(1.0, (now - self.jump_started) / 0.88))
            jump = math.sin(phase * math.pi) * 105
        duck = self._is_ducking()
        y -= jump
        glow = pygame.Surface((220, 220), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, (*CYAN, 45), (20, 155, 180, 40))
        self.scene.blit(glow, glow.get_rect(center=(x, y - 10)))
        if now < self.invulnerable_until and int(now * 12) % 2 == 0:
            color = GOLD
        else:
            color = CYAN
        body_h = 76 if duck else 126
        head_y = y - body_h
        run = 0 if self.reduced_motion else math.sin(self.distance * 0.65) * 22
        pygame.draw.circle(self.scene, WHITE, (int(x), int(head_y)), 15)
        pygame.draw.line(self.scene, color, (x, head_y + 18), (x, y - 48), 10)
        pygame.draw.line(self.scene, color, (x, head_y + 35), (x - 34, head_y + 62 + run), 7)
        pygame.draw.line(self.scene, color, (x, head_y + 35), (x + 34, head_y + 62 - run), 7)
        pygame.draw.line(self.scene, color, (x, y - 48), (x - 28, y - 5 - run), 8)
        pygame.draw.line(self.scene, color, (x, y - 48), (x + 28, y - 5 + run), 8)
        if now < self.punch_until:
            pygame.draw.circle(self.scene, ORANGE,
                               (int(x + 48 * (1 if self.player_lane >= 1 else -1)),
                                int(head_y + 42)), 18, 4)
        if self.shields:
            pygame.draw.circle(self.scene, CYAN, (int(x), int(y - 62)), 82, 3)

    def _draw_hud(self, now):
        self._text(self.font_medium, f"{self.score:06d}", WHITE, (105, 45))
        self._text(self.font_tiny, f"BEST {self.best:06d}", MUTED, (105, 78))
        self._text(self.font_medium, f"{int(self.distance):04d} m", CYAN, (W / 2, 45))
        self._text(self.font_small, f"金币 {self.coins_collected}", GOLD, (W - 108, 48))
        for index in range(3):
            color = RED if index < self.lives else (55, 60, 82)
            pygame.draw.circle(self.scene, color, (W - 205 + index * 27, 82), 9)
        if self.shields:
            self._text(self.font_tiny, f"护盾 ×{self.shields}", CYAN, (W - 92, 82))
        if self.combo >= 3:
            self._text(self.font_small, f"{self.combo} 连续闪避", PURPLE, (W / 2, 82))
        timers = []
        if now < self.magnet_until:
            timers.append(("磁铁", self.magnet_until - now, GOLD))
        if now < self.boost_until:
            timers.append(("冲刺", self.boost_until - now, CYAN))
        if now < self.double_until:
            timers.append(("双倍", self.double_until - now, GREEN))
        for index, (label, remaining, color) in enumerate(timers):
            x = 110 + index * 145
            pygame.draw.rect(self.scene, (20, 29, 53), (x - 55, 105, 110, 8),
                             border_radius=4)
            pygame.draw.rect(self.scene, color,
                             (x - 55, 105, int(110 * min(1, remaining / 9)), 8),
                             border_radius=4)
            self._text(self.font_tiny, label, color, (x, 130))

    def _draw_menu(self, now):
        scrim = pygame.Surface((W, H), pygame.SRCALPHA)
        scrim.fill((3, 6, 20, 105))
        self.scene.blit(scrim, (0, 0))
        self._text(self.font_title, "霓虹疾跑", WHITE, (W / 2, H * 0.17))
        self._text(self.font_small, "倾身换道 · 举手跳跃 · 下蹲滑行 · 挥手击碎",
                   MUTED, (W / 2, H * 0.28))
        center = (W // 2, int(H * 0.48))
        pygame.draw.circle(self.scene, (15, 34, 66), center, 76)
        pygame.draw.circle(self.scene, CYAN, center, 76, 3)
        if self.hold_progress:
            rect = pygame.Rect(0, 0, 170, 170)
            rect.center = center
            pygame.draw.arc(self.scene, GOLD, rect, -math.pi / 2,
                            -math.pi / 2 + math.tau * self.hold_progress, 8)
        self._text(self.font_medium, "举起双手", WHITE, (center[0], center[1] - 12))
        self._text(self.font_tiny, "保持 1 秒开始", CYAN, (center[0], center[1] + 28))
        cards = (("倾身", "换道"), ("举手", "跳跃"), ("下蹲", "滑行"), ("挥手", "击碎"))
        for index, (action, result) in enumerate(cards):
            x = W * 0.27 + index * W * 0.155
            rect = pygame.Rect(0, 0, 150, 70)
            rect.center = (x, H * 0.70)
            pygame.draw.rect(self.scene, (15, 24, 50), rect, border_radius=10)
            pygame.draw.rect(self.scene, (55, 75, 112), rect, 2, border_radius=10)
            self._text(self.font_small, action, WHITE, (x, rect.centery - 13))
            self._text(self.font_tiny, result, CYAN, (x, rect.centery + 17))
        hint = "空格开始 · F 全屏 · Esc 退出"
        if self.debug_mode:
            hint = "调试：A/D 换道 · 空格跳 · 按住 S 下蹲 · K 挥击 · " + hint
        self._text(self.font_tiny, hint, MUTED, (W / 2, H * 0.91))
        if self.tracker_error:
            self._text(self.font_small, self.tracker_error, RED, (W / 2, H * 0.84))

    def _draw_calibration(self):
        self._text(self.font_large, "校准跑者", WHITE, (W / 2, H * 0.24))
        self._text(self.font_small, "自然站立，保持双手、肩部和髋部完整入画",
                   MUTED, (W / 2, H * 0.34))
        self._progress_ring((W / 2, H * 0.56), 82, self.hold_progress, CYAN)
        self._text(self.font_medium, f"{int(self.hold_progress * 100)}%", WHITE,
                   (W / 2, H * 0.56))
        if not self.points:
            self._text(self.font_small, "正在寻找身体…", RED, (W / 2, H * 0.76))

    def _draw_countdown(self, now):
        remaining = max(1, 3 - int(now - self.state_started))
        self._text(self.font_large, "前方轨道已开启", WHITE, (W / 2, H * 0.30))
        self._text(self.font_title, remaining, GOLD, (W / 2, H * 0.52))
        self._text(self.font_small, "看清障碍提示，提前完成动作",
                   MUTED, (W / 2, H * 0.68))

    def _draw_results(self):
        rank = "S" if self.distance >= 1200 else "A" if self.distance >= 850 else (
            "B" if self.distance >= 550 else "C" if self.distance >= 300 else "D")
        self._text(self.font_large, "本次疾跑", WHITE, (W / 2, H * 0.15))
        self._text(self.font_title, rank, GOLD if rank in "SA" else CYAN,
                   (W * 0.27, H * 0.39))
        self._text(self.font_large, f"{self.score:06d}", WHITE, (W * 0.62, H * 0.30))
        self._text(self.font_small, f"距离  {int(self.distance)} m", CYAN,
                   (W * 0.62, H * 0.39))
        summary = f"金币 {self.coins_collected}     最高连续闪避 {self.max_combo}"
        self._text(self.font_small, summary, WHITE, (W / 2, H * 0.55))
        self._progress_ring((W / 2, H * 0.73), 55, self.hold_progress, PURPLE)
        self._text(self.font_small, "再次举起双手", WHITE, (W / 2, H * 0.71))
        self._text(self.font_tiny, "保持 1 秒重跑 · 空格也可以开始", MUTED,
                   (W / 2, H * 0.78))

    def _draw_pause(self):
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((2, 4, 14, 210))
        self.scene.blit(overlay, (0, 0))
        self._text(self.font_large, "疾跑暂停", WHITE, (W / 2, H / 2 - 20))
        self._text(self.font_small, "按 P 继续", MUTED, (W / 2, H / 2 + 46))

    def _progress_ring(self, center, radius, progress, color):
        pygame.draw.circle(self.scene, (31, 42, 70), center, radius, 7)
        rect = pygame.Rect(0, 0, radius * 2, radius * 2)
        rect.center = center
        pygame.draw.arc(self.scene, color, rect, -math.pi / 2,
                        -math.pi / 2 + math.tau * progress, 8)

    def _text(self, font, text, color, center):
        shadow = font.render(str(text), True, (0, 0, 0))
        shadow.set_alpha(175)
        image = font.render(str(text), True, color)
        rect = image.get_rect(center=center)
        self.scene.blit(shadow, rect.move(2, 3))
        self.scene.blit(image, rect)
        return rect


def run_self_test():
    assert speed_for(0) < speed_for(180)
    assert spawn_interval(0) > spawn_interval(180)
    assert project(1, 0.2)[1] < project(1, 0.9)[1]
    assert project(0, 0.9)[0] < project(1, 0.9)[0] < project(2, 0.9)[0]
    assert obstacle_avoided(BARRIER, jumping=True)
    assert obstacle_avoided(OVERHEAD, ducking=True)
    assert obstacle_avoided(CRATE, punching=True)
    assert not obstacle_avoided(TRAIN, jumping=True, ducking=True, punching=True)
    planner = WavePlanner(7)
    for elapsed in range(0, 240):
        obstacles, coins, power, safe_lane = planner.make_wave(elapsed)
        assert validate_wave(obstacles)
        assert safe_lane in LANES
        assert all(coin.lane == safe_lane for coin in coins)
        assert power is None or power.kind in POWER_KINDS
    print("self-test passed: projection, difficulty, gestures, 240 fair waves")


def main():
    parser = argparse.ArgumentParser(description="霓虹疾跑体感跑酷游戏")
    parser.add_argument("--camera", type=int, default=0, help="摄像头编号（默认 0）")
    parser.add_argument("--debug", "--mouse", dest="debug_mode", action="store_true",
                        help="不开摄像头，使用键盘调试")
    parser.add_argument("--reduced-motion", action="store_true",
                        help="减少扫描线、粒子和跑步摆动")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return
    Game(args.camera, args.debug_mode, args.reduced_motion, args.smoke_test).run()


if __name__ == "__main__":
    main()
