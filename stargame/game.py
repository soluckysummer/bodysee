"""《星核指挥家》主循环：用全身动作完成一段自适应星际乐曲。"""

import argparse
import json
import math
import os
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pygame

from stargame import sfx, sprites
from stargame.notes import (APPROACH_TIME, BEAT, BPM, CHORD, HIT_WINDOW,
                            KINDS, LEFT, RIGHT, SQUAT, STAR, build_chart,
                            song_duration)

W, H = 1280, 720
FPS = 60

BG = (5, 8, 24)
CYAN = (85, 231, 255)
ORANGE = (255, 173, 66)
PURPLE = (181, 124, 255)
GOLD = (255, 216, 107)
RED = (255, 102, 122)
WHITE = (242, 247, 255)
MUTED = (168, 180, 205)

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
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyh.ttf",
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


def grade_from_offset(offset):
    offset = abs(offset)
    if offset <= 0.09:
        return "perfect", 100
    if offset <= 0.17:
        return "great", 82
    if offset <= HIT_WINDOW:
        return "good", 62
    return "miss", 0


def combo_multiplier(combo):
    if combo >= 50:
        return 2.0
    if combo >= 25:
        return 1.5
    if combo >= 10:
        return 1.2
    return 1.0


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    color: tuple
    born: float
    life: float
    radius: float

    def draw(self, surface, now):
        age = (now - self.born) / self.life
        if age >= 1:
            return False
        x = self.x + self.vx * (now - self.born)
        y = self.y + self.vy * (now - self.born)
        radius = max(1, int(self.radius * (1 - age)))
        color = (*self.color, int(220 * (1 - age)))
        pygame.draw.circle(surface, color, (int(x), int(y)), radius)
        return True


@dataclass
class Feedback:
    text: str
    color: tuple
    x: float
    y: float
    born: float
    life: float = 0.85

    def draw(self, surface, font, now):
        age = (now - self.born) / self.life
        if age >= 1:
            return False
        image = font.render(self.text, True, self.color)
        image.set_alpha(int(255 * (1 - age * age)))
        rect = image.get_rect(center=(self.x, self.y - age * 42))
        surface.blit(image, rect)
        return True


class Game:
    def __init__(self, camera_index=0, debug_mode=False, reduced_motion=False,
                 smoke_test=False):
        pygame.mixer.pre_init(sfx.SR, -16, 2, 512)
        pygame.init()
        pygame.display.set_caption("星核指挥家")
        self.screen = pygame.display.set_mode((W, H), pygame.SCALED)
        self.scene = pygame.Surface((W, H))
        self.clock = pygame.time.Clock()
        self.audio_ready = False
        try:
            sfx.init()
            self.audio_ready = True
        except pygame.error:
            pass

        font_path = _find_cjk_font()
        self.font_title = pygame.font.Font(font_path, 76)
        self.font_large = pygame.font.Font(font_path, 54)
        self.font_medium = pygame.font.Font(font_path, 34)
        self.font_small = pygame.font.Font(font_path, 23)
        self.font_tiny = pygame.font.Font(font_path, 18)

        self.debug_mode = debug_mode
        self.reduced_motion = reduced_motion
        self.smoke_test = smoke_test
        self.tracker = None
        if not debug_mode:
            from stargame.tracker import BodyTracker
            self.tracker = BodyTracker(camera_index, (W, H))
            self.tracker.start()

        self.starfield = sprites.make_starfield((W, H))
        self.vignette = sprites.make_vignette((W, H))
        self.veil = pygame.Surface((W, H))
        self.veil.fill((3, 7, 25))
        self.veil.set_alpha(150)
        self.bg_surface = None
        self.bg_seq = -1
        self.points = {}
        self.tracker_error = None
        self.state = MENU
        self.state_started = time.monotonic()
        self.hold_progress = 0.0
        self.calibration_samples = []
        self.baseline = None
        self.last_hands = {}
        self.paused = False
        self.pause_started = 0.0
        self.best = self._load_best()
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
        self.chart = build_chart()
        self.duration = song_duration(self.chart)
        self.score = 0
        self.combo = 0
        self.max_combo = 0
        self.energy = 60.0
        self.super_until = -1.0
        self.super_active = False
        self.recovery_hits = 0
        self.failures = 0
        self.results = Counter()
        self.quality_total = 0
        self.particles = []
        self.feedbacks = []
        self.play_started = 0.0
        self.ended_early = False

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
                    if self.state in (CALIBRATING, COUNTDOWN, PLAYING, RESULTS):
                        sfx.stop_music()
                        self._set_state(MENU, now)
                    else:
                        return False
                elif event.key == pygame.K_f:
                    pygame.display.toggle_fullscreen()
                elif event.key == pygame.K_p and self.state == PLAYING:
                    self._toggle_pause(now)
                elif event.key == pygame.K_SPACE and self.state in (MENU, RESULTS):
                    self._begin_calibration(now)
                elif self.state == PLAYING and event.key in (
                        pygame.K_a, pygame.K_d, pygame.K_s, pygame.K_w, pygame.K_j):
                    mapping = {pygame.K_a: LEFT, pygame.K_d: RIGHT,
                               pygame.K_j: CHORD, pygame.K_s: SQUAT,
                               pygame.K_w: STAR}
                    self._attempt_kind(mapping[event.key], now, forced=True)
            elif event.type == pygame.MOUSEBUTTONDOWN and self.state in (MENU, RESULTS):
                self._begin_calibration(now)
        return True

    def _toggle_pause(self, now):
        self.paused = not self.paused
        if self.paused:
            self.pause_started = now
            pygame.mixer.pause()
        else:
            self.play_started += now - self.pause_started
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
            self.baseline = {"shoulder_y": H * 0.38, "torso": H * 0.22,
                             "shoulder_width": W * 0.20}
            self._set_state(COUNTDOWN, now)
        else:
            self._set_state(CALIBRATING, now)

    def _update(self, dt, now):
        if self.state == MENU:
            self._update_hold_start(dt, now)
        elif self.state == CALIBRATING:
            self._update_calibration(dt, now)
        elif self.state == COUNTDOWN:
            if now - self.state_started >= 3.0:
                self._set_state(PLAYING, now)
                self.play_started = now
                sfx.start_music()
                sfx.play("start")
        elif self.state == PLAYING and not self.paused:
            self._update_playing(dt, now)
        elif self.state == RESULTS:
            self._update_hold_start(dt, now)

        self.particles = [p for p in self.particles if now - p.born < p.life][-420:]
        self.feedbacks = [f for f in self.feedbacks if now - f.born < f.life][-12:]

    def _update_hold_start(self, dt, now):
        if self.debug_mode:
            return
        if self._hands_overhead():
            self.hold_progress = min(1.0, self.hold_progress + dt / 1.0)
            if self.hold_progress >= 1.0:
                self._begin_calibration(now)
        else:
            self.hold_progress = max(0.0, self.hold_progress - dt * 2.2)

    def _hands_overhead(self):
        required = ("left_wrist", "right_wrist", "left_shoulder", "right_shoulder")
        if not all(name in self.points for name in required):
            return False
        shoulder_y = (self.points["left_shoulder"][1]
                      + self.points["right_shoulder"][1]) / 2
        return (self.points["left_wrist"][1] < shoulder_y - 28
                and self.points["right_wrist"][1] < shoulder_y - 28)

    def _update_calibration(self, dt, now):
        required = ("left_shoulder", "right_shoulder", "left_hip", "right_hip",
                    "left_wrist", "right_wrist")
        if not all(name in self.points for name in required):
            self.hold_progress = max(0.0, self.hold_progress - dt)
            return
        shoulder_y = (self.points["left_shoulder"][1]
                      + self.points["right_shoulder"][1]) / 2
        hip_y = (self.points["left_hip"][1] + self.points["right_hip"][1]) / 2
        shoulder_width = abs(self.points["left_shoulder"][0]
                             - self.points["right_shoulder"][0])
        torso = hip_y - shoulder_y
        if torso < 45 or shoulder_width < 35:
            self.hold_progress = max(0.0, self.hold_progress - dt)
            return
        self.calibration_samples.append((shoulder_y, torso, shoulder_width))
        self.hold_progress = min(1.0, self.hold_progress + dt / 2.0)
        if self.hold_progress >= 1.0 and len(self.calibration_samples) >= 12:
            self.baseline = {
                "shoulder_y": statistics.median(x[0] for x in self.calibration_samples),
                "torso": statistics.median(x[1] for x in self.calibration_samples),
                "shoulder_width": statistics.median(x[2] for x in self.calibration_samples),
            }
            self._set_state(COUNTDOWN, now)

    def _update_playing(self, dt, now):
        game_time = now - self.play_started
        self._attempt_pose_actions(now)
        for note in self.chart:
            if not note.resolved and game_time - note.due > HIT_WINDOW:
                self._resolve_miss(note, now)
                if self.state != PLAYING:
                    return

        was_super = self.super_active
        self.super_active = game_time < self.super_until
        if was_super and not self.super_active:
            self.energy = min(self.energy, 55.0)
        sfx.update_music(self.combo, self.energy, self.super_active)
        if game_time >= self.duration:
            self._finish_round(now)

    def _screen_hands(self):
        if "left_wrist" not in self.points or "right_wrist" not in self.points:
            return {}
        pair = sorted((self.points["left_wrist"], self.points["right_wrist"]),
                      key=lambda point: point[0])
        return {LEFT: pair[0], RIGHT: pair[1]}

    def _attempt_pose_actions(self, now):
        game_time = now - self.play_started
        hands = self._screen_hands()
        for kind in (LEFT, RIGHT):
            point = hands.get(kind)
            note = self._active_note(kind, game_time)
            if point and note:
                target = self._targets(note)[0]
                if math.hypot(point[0] - target[0], point[1] - target[1]) <= 92:
                    self._attempt_kind(kind, now)

        chord = self._active_note(CHORD, game_time)
        if chord and LEFT in hands and RIGHT in hands:
            targets = self._targets(chord)
            left_ok = math.dist(hands[LEFT][:2], targets[0]) <= 108
            right_ok = math.dist(hands[RIGHT][:2], targets[1]) <= 108
            if left_ok and right_ok:
                self._attempt_kind(CHORD, now)

        if self._active_note(SQUAT, game_time) and self._is_squatting():
            self._attempt_kind(SQUAT, now)
        if self._active_note(STAR, game_time) and self._is_star_pose():
            self._attempt_kind(STAR, now)

    def _is_squatting(self):
        if not self.baseline:
            return False
        shoulders = ("left_shoulder", "right_shoulder")
        if not all(name in self.points for name in shoulders):
            return False
        shoulder_y = sum(self.points[name][1] for name in shoulders) / 2
        threshold = max(38.0, self.baseline["torso"] * 0.30)
        return shoulder_y - self.baseline["shoulder_y"] > threshold

    def _is_star_pose(self):
        required = ("left_wrist", "right_wrist", "left_shoulder", "right_shoulder")
        if not all(name in self.points for name in required):
            return False
        wrists = (self.points["left_wrist"], self.points["right_wrist"])
        shoulders = (self.points["left_shoulder"], self.points["right_shoulder"])
        shoulder_y = (shoulders[0][1] + shoulders[1][1]) / 2
        spread = abs(wrists[0][0] - wrists[1][0])
        expected = max(180.0, abs(shoulders[0][0] - shoulders[1][0]) * 2.0)
        level = all(abs(wrist[1] - shoulder_y) < 100 for wrist in wrists)
        return spread > expected and level

    def _active_note(self, kind, game_time):
        candidates = [note for note in self.chart
                      if not note.resolved and note.kind == kind
                      and abs(note.due - game_time) <= HIT_WINDOW]
        return min(candidates, key=lambda note: abs(note.due - game_time), default=None)

    def _attempt_kind(self, kind, now, forced=False):
        if kind not in KINDS or self.state != PLAYING or self.paused:
            return False
        game_time = now - self.play_started
        note = self._active_note(kind, game_time)
        if note is None:
            return False
        grade, quality = grade_from_offset(game_time - note.due)
        note.resolved = True
        note.result = grade
        self.results[grade] += 1
        self.quality_total += quality
        if grade in ("perfect", "great"):
            self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        multiplier = combo_multiplier(self.combo) * (1.5 if self.super_active else 1.0)
        self.score += int(quality * multiplier)
        self.energy = min(100.0, self.energy + {"perfect": 3, "great": 2,
                                                "good": 0}[grade])
        if self.recovery_hits:
            self.recovery_hits -= 1
            if self.recovery_hits == 0:
                self.energy = max(self.energy, 42)
                self.feedbacks.append(Feedback("星核恢复", CYAN, W / 2, H * 0.27, now, 1.2))
        if self.energy >= 100 and not self.super_active:
            self.super_until = game_time + 8.0
            self.super_active = True
            sfx.play("supernova")
            self.feedbacks.append(Feedback("超新星", GOLD, W / 2, H * 0.24, now, 1.3))
        pan = -0.7 if kind == LEFT else (0.7 if kind == RIGHT else 0.0)
        sfx.play(grade, pan)
        label = {"perfect": "PERFECT", "great": "GREAT", "good": "GOOD"}[grade]
        target = self._targets(note)[0]
        self.feedbacks.append(Feedback(label, self._grade_color(grade),
                                       target[0], target[1], now))
        self._burst(target, self._kind_color(note.kind), now, 22 if grade == "perfect" else 12)
        return True

    def _resolve_miss(self, note, now):
        note.resolved = True
        note.result = "miss"
        self.results["miss"] += 1
        self.combo = 0
        if self.recovery_hits:
            self.energy = max(5.0, self.energy - 2.0)
        else:
            self.energy = max(0.0, self.energy - 8.0)
        sfx.play("miss")
        target = self._targets(note)[0]
        self.feedbacks.append(Feedback("MISS", RED, target[0], target[1], now, 0.65))
        if self.energy <= 0 and not self.recovery_hits:
            self.failures += 1
            if self.failures >= 3:
                self.ended_early = True
                self._finish_round(now)
            else:
                self.energy = 15.0
                self.recovery_hits = 3
                self.feedbacks.append(Feedback(
                    f"星核失速 · 连续命中 3 次恢复", RED, W / 2, H * 0.26, now, 1.6))

    def _finish_round(self, now):
        if self.state != PLAYING:
            return
        sfx.stop_music()
        sfx.play("finish")
        if self.score > self.best:
            self.best = self.score
            self._save_best()
        self._set_state(RESULTS, now)

    def _targets(self, note):
        y = (H * 0.31, H * 0.48, H * 0.65)[note.lane]
        if note.kind == LEFT:
            return ((W * 0.28, y),)
        if note.kind == RIGHT:
            return ((W * 0.72, y),)
        if note.kind == CHORD:
            return ((W * 0.30, y), (W * 0.70, y))
        return ((W / 2, H * 0.50),)

    @staticmethod
    def _kind_color(kind):
        return {LEFT: CYAN, RIGHT: ORANGE, CHORD: PURPLE,
                SQUAT: GOLD, STAR: PURPLE}[kind]

    @staticmethod
    def _grade_color(grade):
        return {"perfect": GOLD, "great": CYAN, "good": WHITE, "miss": RED}[grade]

    def _burst(self, target, color, now, count):
        if self.reduced_motion:
            count = min(count, 5)
        for index in range(count):
            angle = index / max(1, count) * math.tau
            speed = 75 + (index % 5) * 32
            self.particles.append(Particle(
                target[0], target[1], math.cos(angle) * speed,
                math.sin(angle) * speed, color, now, 0.55, 4.5))

    def _draw(self, now):
        self._draw_background(now)
        self._draw_body_aura(now)
        if self.state == PLAYING:
            self._draw_notes(now)
            self._draw_hud(now)
        for particle in self.particles:
            particle.draw(self.scene, now)
        for feedback in self.feedbacks:
            feedback.draw(self.scene, self.font_medium, now)

        if self.state == MENU:
            self._draw_menu(now)
        elif self.state == CALIBRATING:
            self._draw_calibration()
        elif self.state == COUNTDOWN:
            self._draw_countdown(now)
        elif self.state == RESULTS:
            self._draw_results(now)
        if self.state == PLAYING and self.paused:
            self._draw_pause()
        self.screen.blit(self.scene, (0, 0))
        pygame.display.flip()

    def _draw_background(self, now):
        if self.bg_surface is not None:
            self.scene.blit(self.bg_surface, (0, 0))
            self.scene.blit(self.veil, (0, 0))
        else:
            self.scene.fill(BG)
        star_alpha = int(100 + 80 * self.energy / 100)
        self.starfield.set_alpha(star_alpha)
        self.scene.blit(self.starfield, (0, 0))
        self.scene.blit(self.vignette, (0, 0))
        if self.super_active and not self.reduced_motion:
            pulse = pygame.Surface((W, H), pygame.SRCALPHA)
            alpha = int(18 + 10 * math.sin(now * 5))
            pulse.fill((*GOLD, alpha))
            self.scene.blit(pulse, (0, 0))

    def _draw_body_aura(self, now):
        if not self.points:
            return
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        bones = (("left_shoulder", "right_shoulder"),
                 ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
                 ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
                 ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"),
                 ("left_hip", "right_hip"), ("left_hip", "left_knee"),
                 ("left_knee", "left_ankle"), ("right_hip", "right_knee"),
                 ("right_knee", "right_ankle"))
        for start, end in bones:
            if start in self.points and end in self.points:
                pygame.draw.line(overlay, (*CYAN, 105), self.points[start][:2],
                                 self.points[end][:2], 5)
                pygame.draw.line(overlay, (*WHITE, 150), self.points[start][:2],
                                 self.points[end][:2], 1)
        hands = self._screen_hands()
        for kind, point in hands.items():
            color = CYAN if kind == LEFT else ORANGE
            radius = 14 if self.reduced_motion else 14 + int(2 * math.sin(now * 6))
            pygame.draw.circle(overlay, (*color, 55), point[:2], radius + 9)
            pygame.draw.circle(overlay, (*color, 220), point[:2], radius, 3)
        self.scene.blit(overlay, (0, 0))

    def _draw_notes(self, now):
        game_time = now - self.play_started
        for note in self.chart:
            delta = note.due - game_time
            if note.resolved or delta > APPROACH_TIME or delta < -HIT_WINDOW:
                continue
            progress = max(0.0, min(1.0, 1.0 - delta / APPROACH_TIME))
            progress = 1.0 - (1.0 - progress) ** 3
            color = self._kind_color(note.kind)
            targets = self._targets(note)
            if note.kind in (LEFT, RIGHT, CHORD):
                for index, target in enumerate(targets):
                    side = LEFT if target[0] < W / 2 else RIGHT
                    start_x = -70 if side == LEFT else W + 70
                    x = start_x + (target[0] - start_x) * progress
                    y = target[1] - math.sin(progress * math.pi) * 48
                    pygame.draw.line(self.scene, (*color, 160), (x, y), target, 4)
                    pygame.draw.circle(self.scene, color, (int(x), int(y)), 11)
                    ring = max(34, int(88 - progress * 48))
                    pygame.draw.circle(self.scene, color, target, ring, 3)
                    pygame.draw.circle(self.scene, WHITE, target, 6, 2)
            elif note.kind == SQUAT:
                self._draw_portal(progress, GOLD, "下蹲")
            elif note.kind == STAR:
                self._draw_constellation(progress)

    def _draw_portal(self, progress, color, label):
        width = int(W * (0.28 + 0.34 * progress))
        height = int(H * (0.20 + 0.18 * progress))
        rect = pygame.Rect(0, 0, width, height)
        rect.center = (W / 2, H * 0.53)
        pygame.draw.arc(self.scene, color, rect, math.pi, math.tau, 7)
        self._text(self.font_medium, label, color, (W / 2, H * 0.61))

    def _draw_constellation(self, progress):
        cx, cy = W / 2, H * 0.48
        span = 115 + progress * 105
        points = ((cx - span, cy), (cx - 55, cy - 8), (cx, cy - 72),
                  (cx + 55, cy - 8), (cx + span, cy))
        for first, second in zip(points, points[1:]):
            pygame.draw.line(self.scene, PURPLE, first, second, 3)
        for point in points:
            pygame.draw.circle(self.scene, WHITE, point, 7)
        self._text(self.font_medium, "展开双臂", PURPLE, (cx, H * 0.64))

    def _draw_hud(self, now):
        game_time = max(0.0, now - self.play_started)
        self._text(self.font_medium, f"{self.score:06d}", WHITE, (105, 48))
        self._text(self.font_tiny, f"BEST {self.best:06d}", MUTED, (105, 82))
        if self.combo >= 2:
            color = GOLD if self.super_active else CYAN
            self._text(self.font_large, f"{self.combo} COMBO", color, (W / 2, 62))
        bar = pygame.Rect(W - 270, 38, 220, 18)
        pygame.draw.rect(self.scene, (26, 34, 58), bar, border_radius=9)
        fill = bar.copy()
        fill.width = int(bar.width * self.energy / 100)
        pygame.draw.rect(self.scene, GOLD if self.super_active else CYAN,
                         fill, border_radius=9)
        self._text(self.font_tiny, "星核能量", WHITE, (W - 160, 78))
        progress = min(1.0, game_time / self.duration)
        pygame.draw.rect(self.scene, (27, 34, 55), (80, H - 28, W - 160, 5))
        pygame.draw.rect(self.scene, PURPLE,
                         (80, H - 28, int((W - 160) * progress), 5))
        if self.recovery_hits:
            self._text(self.font_small, f"恢复序列  {3 - self.recovery_hits}/3",
                       RED, (W / 2, 112))

    def _draw_menu(self, now):
        self._text(self.font_title, "星核指挥家", WHITE, (W / 2, H * 0.20))
        self._text(self.font_small, "挥动双手、下蹲、展开身体，让沉寂的星河重新奏响",
                   MUTED, (W / 2, H * 0.31))
        center = (W // 2, int(H * 0.56))
        radius = 86 + (0 if self.reduced_motion else int(5 * math.sin(now * 2.4)))
        pygame.draw.circle(self.scene, (20, 35, 70), center, radius)
        pygame.draw.circle(self.scene, CYAN, center, radius, 3)
        if self.hold_progress:
            rect = pygame.Rect(0, 0, radius * 2 + 18, radius * 2 + 18)
            rect.center = center
            pygame.draw.arc(self.scene, GOLD, rect, -math.pi / 2,
                            -math.pi / 2 + math.tau * self.hold_progress, 8)
        self._text(self.font_medium, "双手举过头顶", WHITE, (center[0], center[1] - 12))
        self._text(self.font_small, "保持 1 秒开始", CYAN, (center[0], center[1] + 32))
        hint = "空格开始 · F 全屏 · Esc 退出"
        if self.debug_mode:
            hint = "调试操作：A/D 左右手 · J 双手 · S 下蹲 · W 星座 · " + hint
        self._text(self.font_tiny, hint, MUTED, (W / 2, H * 0.91))
        if self.tracker_error:
            self._text(self.font_small, self.tracker_error, RED, (W / 2, H * 0.83))

    def _draw_calibration(self):
        self._text(self.font_large, "建立身体星图", WHITE, (W / 2, H * 0.24))
        self._text(self.font_small, "自然站立，双手放松，保持肩部与髋部在画面内",
                   MUTED, (W / 2, H * 0.34))
        self._progress_ring((W / 2, H * 0.57), 82, self.hold_progress, CYAN)
        percent = int(self.hold_progress * 100)
        self._text(self.font_medium, f"{percent}%", WHITE, (W / 2, H * 0.57))
        if not self.points:
            self._text(self.font_small, "正在寻找身体…", RED, (W / 2, H * 0.76))

    def _draw_countdown(self, now):
        remaining = max(1, 3 - int(now - self.state_started))
        self._text(self.font_large, "准备聆听节拍", MUTED, (W / 2, H * 0.30))
        self._text(self.font_title, str(remaining), GOLD, (W / 2, H * 0.52))
        self._text(self.font_small, "青色控制屏幕左侧 · 橙色控制屏幕右侧",
                   WHITE, (W / 2, H * 0.68))

    def _draw_results(self, now):
        total = sum(self.results.values())
        accuracy = self.quality_total / max(1, total)
        rank = "S" if accuracy >= 92 else "A" if accuracy >= 80 else (
            "B" if accuracy >= 68 else "C" if accuracy >= 50 else "D")
        self._text(self.font_large, "星河演奏完成" if not self.ended_early else "星核暂时休眠",
                   WHITE, (W / 2, H * 0.15))
        self._text(self.font_title, rank, GOLD if rank in "SA" else CYAN,
                   (W * 0.28, H * 0.39))
        self._text(self.font_large, f"{self.score:06d}", WHITE, (W * 0.62, H * 0.31))
        self._text(self.font_small, f"最高连击  {self.max_combo}", MUTED,
                   (W * 0.62, H * 0.40))
        summary = (f"PERFECT {self.results['perfect']}    GREAT {self.results['great']}    "
                   f"GOOD {self.results['good']}    MISS {self.results['miss']}")
        self._text(self.font_small, summary, WHITE, (W / 2, H * 0.56))
        self._progress_ring((W / 2, H * 0.74), 54, self.hold_progress, PURPLE)
        self._text(self.font_small, "再次举起双手", WHITE, (W / 2, H * 0.72))
        self._text(self.font_tiny, "保持 1 秒重演 · 空格也可以开始", MUTED,
                   (W / 2, H * 0.78))

    def _draw_pause(self):
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((2, 4, 14, 205))
        self.scene.blit(overlay, (0, 0))
        self._text(self.font_large, "演奏暂停", WHITE, (W / 2, H / 2 - 20))
        self._text(self.font_small, "按 P 继续", MUTED, (W / 2, H / 2 + 48))

    def _progress_ring(self, center, radius, progress, color):
        pygame.draw.circle(self.scene, (31, 42, 70), center, radius, 7)
        rect = pygame.Rect(0, 0, radius * 2, radius * 2)
        rect.center = center
        pygame.draw.arc(self.scene, color, rect, -math.pi / 2,
                        -math.pi / 2 + math.tau * progress, 8)

    def _text(self, font, text, color, center):
        shadow = font.render(str(text), True, (0, 0, 0))
        shadow.set_alpha(170)
        image = font.render(str(text), True, color)
        rect = image.get_rect(center=center)
        self.scene.blit(shadow, rect.move(2, 3))
        self.scene.blit(image, rect)
        return rect


def run_self_test():
    chart = build_chart()
    assert len(chart) >= 100
    assert all(first.beat <= second.beat for first, second in zip(chart, chart[1:]))
    assert set(note.kind for note in chart) == set(KINDS)
    assert song_duration(chart) > 100
    assert grade_from_offset(0.0) == ("perfect", 100)
    assert grade_from_offset(0.12) == ("great", 82)
    assert grade_from_offset(0.25) == ("good", 62)
    assert grade_from_offset(0.31) == ("miss", 0)
    assert combo_multiplier(9) == 1.0
    assert combo_multiplier(10) == 1.2
    assert combo_multiplier(50) == 2.0
    print(f"self-test passed: {len(chart)} notes, {song_duration(chart):.1f}s, {BPM} BPM")


def main():
    parser = argparse.ArgumentParser(description="星核指挥家体感节奏游戏")
    parser.add_argument("--camera", type=int, default=0, help="摄像头编号（默认 0）")
    parser.add_argument("--mouse", "--debug", dest="debug_mode", action="store_true",
                        help="不开摄像头，使用键盘调试动作")
    parser.add_argument("--reduced-motion", action="store_true",
                        help="减少粒子、脉冲和动态背景效果")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return
    Game(camera_index=args.camera, debug_mode=args.debug_mode,
         reduced_motion=args.reduced_motion, smoke_test=args.smoke_test).run()


if __name__ == "__main__":
    main()
