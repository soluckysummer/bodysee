"""缩墙勇士 主程序。

带人形洞的泡沫墙从走廊深处压过来，在墙到达前摆出和洞一样的姿势
（手臂方向 + 是否下蹲 + 身体倾斜）就能穿过去得分；姿势不对撞墙掉命，
3 条命用完游戏结束。越往后墙越快、姿势越刁钻。

单人直接玩；两个人同时入画自动变双人模式——一面墙两个洞，
各自匹配自己那半边，各有 3 条命，比谁分高、谁活得久。

操作全靠身体：举手 1 秒开始/再来一局。Esc 退出，P 暂停，F 全屏。
"""

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

import pygame

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wallgame import sfx
from wallgame import poses as P
# 复用格斗游戏的通用组件（粒子/飘字/播报/中文字体）和双人追踪器
from fightgame.game import Particle, FloatText, Announcer, _find_cjk_font

W, H = 1280, 720
FPS = 60
FLOOR_Y = H - 70
CHAR_SH_W = 96
MAX_LIVES = 3
READY_SEC = 1.2
CALIB_SEC = 2.2

PLAYER_COLORS = [(80, 220, 255), (255, 165, 70)]
PLAYER_NAMES = ["青", "橙"]
SLOT_SOLO = W / 2
SLOTS_DUO = (W * 0.30, W * 0.70)

WALL_FACE = (172, 203, 234)      # 泡沫墙面
WALL_GRID = (140, 172, 208)
WALL_EDGE = (96, 128, 168)

HIGHSCORE_PATH = Path(__file__).parent / "highscore.json"

MENU, CALIB, PLAY, OVER = range(4)


def _mid(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


class Puppet:
    """玩家的舞台化身：骨架实时镜像动作，手臂按匹配度染色。"""

    def __init__(self, idx, color):
        self.idx = idx
        self.color = color
        self.slot_x = SLOT_SOLO
        self.tracked = False
        self.last_tracked = 0.0
        self.pts = None
        self.joints = {}
        self.stand_nose_y = None
        self.stand_hip_y = None
        self.raised = False
        self.live_detail = None       # 逼近阶段各分项得分，用于手臂染色
        self.live_score = 0.0

    def update(self, pts, now):
        if pts is None:
            self.tracked = False
            return
        self.tracked = True
        self.last_tracked = now
        self.pts = pts

        l_sh, r_sh = pts["l_sh"], pts["r_sh"]
        sh_c = _mid(l_sh, r_sh)
        sw = max(math.dist(l_sh, r_sh), 0.05)
        if "l_hip" in pts and "r_hip" in pts:
            hip_c = _mid(pts["l_hip"], pts["r_hip"])
        else:
            hip_c = (sh_c[0], sh_c[1] + sw * 1.15)
        scale = min(CHAR_SH_W / sw, 2400.0)

        # 下蹲时化身也蹲下去：髋部相对站立基线的下沉量
        drop = 0.0
        if self.stand_hip_y is not None:
            drop = max(-40.0, min(170.0, (hip_c[1] - self.stand_hip_y) * scale))
        hip_w = (self.slot_x, FLOOR_Y - 205 + drop)

        def world(p):
            return (hip_w[0] + (p[0] - hip_c[0]) * scale,
                    hip_w[1] + (p[1] - hip_c[1]) * scale)

        j = {name: world(p) for name, p in pts.items()
             if name not in ("t", "_cx")}
        j["sh_c"] = world(sh_c)
        j["hip_c"] = hip_w
        j["head"] = (j["nose"][0], j["nose"][1] - 8) if "nose" in j else \
                    (j["sh_c"][0], j["sh_c"][1] - 46)
        self.joints = j

        nose = pts.get("nose")
        wrists = [pts.get("l_wr"), pts.get("r_wr")]
        self.raised = any(w is not None and nose is not None
                          and w[1] < nose[1] - 0.03 for w in wrists)

    def draw(self, scene, now, dead=False):
        if not self.joints:
            return
        j = self.joints
        base = (90, 90, 100) if dead else self.color

        def arm_color(side):
            if dead or self.live_detail is None:
                return base
            s = self.live_detail.get(side, 1.0)
            bad, good = (235, 85, 85), (95, 230, 125)
            return tuple(int(bad[i] + (good[i] - bad[i]) * s) for i in range(3))

        def glow_line(p0, p1, wid, col):
            dim = tuple(int(v * 0.32) for v in col)
            pygame.draw.line(scene, dim, p0, p1, wid + 8)
            pygame.draw.line(scene, col, p0, p1, wid)
            core = tuple(min(255, v + 120) for v in col)
            pygame.draw.line(scene, core, p0, p1, max(2, wid - 7))

        def PT(p):
            return (int(p[0]), int(p[1]))

        hip = j["hip_c"]
        # 腿：脚固定在地板，髋下沉时膝盖外弯
        bend = max(0.0, (hip[1] - (FLOOR_Y - 205)) * 0.55)
        for sgn in (-1, 1):
            foot = (self.slot_x + sgn * 34, FLOOR_Y)
            knee = ((hip[0] + foot[0]) / 2 + sgn * (10 + bend),
                    (hip[1] + foot[1]) / 2)
            glow_line(PT(hip), PT(knee), 12, base)
            glow_line(PT(knee), PT(foot), 11, base)
        pygame.draw.ellipse(scene, tuple(int(v * 0.4) for v in base),
                            (int(self.slot_x) - 52, FLOOR_Y - 6, 104, 14))

        # 躯干
        if "l_sh" in j and "r_sh" in j:
            l_hip = j.get("l_hip", (hip[0] - 22, hip[1]))
            r_hip = j.get("r_hip", (hip[0] + 22, hip[1]))
            poly = [PT(j["l_sh"]), PT(j["r_sh"]), PT(r_hip), PT(l_hip)]
            pygame.draw.polygon(scene, tuple(int(v * 0.42) for v in base), poly)
            pygame.draw.polygon(scene, base, poly, 3)
        glow_line(PT(j["sh_c"]), PT(hip), 10, base)

        # 头
        head = PT(j["head"])
        pygame.draw.circle(scene, tuple(int(v * 0.35) for v in base), head, 33)
        pygame.draw.circle(scene, base, head, 28)
        pygame.draw.circle(scene, (15, 15, 22), head, 21)
        pygame.draw.line(scene, tuple(min(255, v + 120) for v in base),
                         (head[0] - 8, head[1] - 4), (head[0] + 8, head[1] - 4), 5)

        # 手臂（按匹配度染色）
        for side, sh, el, wr in (("l", "l_sh", "l_el", "l_wr"),
                                  ("r", "r_sh", "r_el", "r_wr")):
            col = arm_color(side)
            if sh in j and el in j:
                glow_line(PT(j[sh]), PT(j[el]), 11, col)
                if wr in j:
                    glow_line(PT(j[el]), PT(j[wr]), 10, col)
            elif sh in j and wr in j:
                glow_line(PT(j[sh]), PT(j[wr]), 10, col)
            if wr in j:
                fist = PT(j[wr])
                pygame.draw.circle(scene, col, fist, 13)
                pygame.draw.circle(scene, (255, 255, 255), fist, 6)


def build_stage():
    """演播室走廊背景：透视线 + 地板条纹 + 聚光灯。"""
    s = pygame.Surface((W, H))
    for y in range(H):
        t = y / H
        s.fill((int(16 + 20 * t), int(20 + 24 * t), int(34 + 32 * t)),
               (0, y, W, 1))
    vx, vy = W / 2, H * 0.44
    # 走廊侧壁线
    for frac in (0.0, 0.12, 0.26, 0.42):
        for side in (frac, 1 - frac):
            x = W * side
            pygame.draw.line(s, (52, 62, 96), (x, H), (vx, vy), 2)
    pygame.draw.line(s, (70, 84, 128), (0, vy), (W, vy), 2)
    # 地板横条（透视间距）
    y = vy + 8
    step = 5.0
    while y < H:
        c = int(46 + (y - vy) / (H - vy) * 26)
        pygame.draw.line(s, (c, c + 8, c + 26), (0, int(y)), (W, int(y)), 2)
        y += step
        step *= 1.5
    return s


class Wall:
    def __init__(self, no, pose_map, dur, slots):
        self.no = no
        self.pose_map = pose_map       # 玩家 idx -> pose（死亡玩家没有洞）
        self.dur = dur
        self.slots = slots             # 玩家 idx -> 洞中心 x（与化身站位一致）
        self.t0 = time.monotonic()
        self.judged = False
        self.result_t = None
        self.results = {}              # idx -> (score, passed, detail)
        self.ticks_played = set()
        self.surf = self._build()

    def _build(self):
        surf = pygame.Surface((W, H), pygame.SRCALPHA)
        surf.fill((*WALL_FACE, 255))
        for x in range(0, W, 92):
            pygame.draw.line(surf, WALL_GRID, (x, 0), (x, H), 3)
        for y in range(0, H, 92):
            pygame.draw.line(surf, WALL_GRID, (0, y), (W, y), 3)
        pygame.draw.rect(surf, WALL_EDGE, (0, 0, W, H), 20)
        for idx, pose in self.pose_map.items():
            P.cut_hole(surf, pose, self.slots[idx], H - 64)
            # 洞口描边，远处也看得清
            lines, _circles = P.silhouette(pose, self.slots[idx], H - 64)
            for p0, p1, w_ in lines:
                pygame.draw.line(surf, WALL_EDGE, p0, p1, 6)
        return surf

    def progress(self, now):
        # 双向钳制：跟丢暂停会往前挪 t0，帧时长抖动可能让 t 短暂为负，
        # 负数的非整数次幂是复数，必须挡住
        return max(0.0, min(1.0, (now - self.t0) / self.dur))

    def draw(self, scene, now):
        t = self.progress(now)
        if self.result_t is None:
            s = 0.14 + 0.86 * t ** 1.6
            alpha = int(95 + 160 * t)
        else:
            # 判定后：墙飞过镜头并淡出
            rt = (now - self.result_t) / 0.5
            s = 1.0 + rt * 0.7
            alpha = int(max(0, 255 * (1 - rt)))
        if alpha <= 0:
            return
        size = (max(2, int(W * s)), max(2, int(H * s)))
        scale_fn = (pygame.transform.smoothscale if s <= 1.0
                    else pygame.transform.scale)
        img = scale_fn(self.surf, size)
        img.set_alpha(alpha)
        cy = H * 0.44 + (H * 0.5 - H * 0.44) * t
        scene.blit(img, img.get_rect(center=(W / 2, cy)))


class Game:
    def __init__(self, camera_index=0, force_players=None):
        pygame.mixer.pre_init(sfx.SR, -16, 1, 512)
        pygame.init()
        pygame.display.set_caption("缩墙勇士")
        self.screen = pygame.display.set_mode((W, H), pygame.SCALED)
        self.scene = pygame.Surface((W, H))
        self.clock = pygame.time.Clock()
        try:
            sfx.init()
        except pygame.error:
            pass

        font_path = _find_cjk_font()
        self.font_huge = pygame.font.Font(font_path, 92)
        self.font_big = pygame.font.Font(font_path, 56)
        self.font_mid = pygame.font.Font(font_path, 36)
        self.font_small = pygame.font.Font(font_path, 24)
        self.announcer = Announcer(self.font_huge, self.font_mid)

        self.force_players = force_players
        self.tracker = None
        if force_players is None:
            from fightgame.tracker2 import DuoTracker
            self.tracker = DuoTracker(camera_index)
            self.tracker.start()
        self.tracker_error = None
        self.pip_surface = None

        self.stage = build_stage()
        self.puppets = [Puppet(0, PLAYER_COLORS[0]), Puppet(1, PLAYER_COLORS[1])]
        self.particles = []
        self.texts = []

        self.best = self._load_best()
        self.state = MENU
        self.state_t0 = time.monotonic()
        self.ready_t = [0.0, 0.0]
        self.paused = False
        self.shake_until = 0.0
        self.flash = 0.0

        self.active = []          # 本局参战玩家 idx
        self.lives = {}
        self.scores = {}
        self.combos = {}
        self.wall = None
        self.wall_no = 0
        self.next_wall_at = 0.0
        self.last_pose = None
        self._calib_samples = {}
        self.new_record = False
        self.rng = random.Random()
        self.test_feed = None      # 测试注入口：now -> [pts0, pts1]

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

    # ---------------- 主循环

    def run(self):
        running = True
        while running:
            raw_dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            now = time.monotonic()
            running = self._handle_events()
            dt = 0.0 if self.paused else raw_dt

            self._feed_poses(now)

            if self.state == MENU:
                self._update_menu(now, raw_dt)
            elif self.state == CALIB:
                self._update_calib(now)
            elif self.state == PLAY and not self.paused:
                self._update_play(now, raw_dt)
            elif self.state == OVER:
                self._update_over(now, raw_dt)

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
                elif event.key == pygame.K_p and self.state == PLAY:
                    self.paused = not self.paused
                    if not self.paused and self.wall is not None:
                        pass
                elif event.key == pygame.K_SPACE and self.state in (MENU, OVER):
                    self._start_game()
                elif event.key == pygame.K_r and self.state == OVER:
                    self._start_game()
        return True

    # ---------------- 输入

    def _feed_poses(self, now):
        players = [None, None]
        if self.test_feed is not None:
            players = self.test_feed(now)
        elif self.tracker:
            players, pip, self.tracker_error = self.tracker.get_state()
            if pip is not None:
                self.pip_surface = pygame.image.frombuffer(
                    pip.tobytes(), (pip.shape[1], pip.shape[0]), "RGB")
        # 菜单和单人局里：画面里唯一的人无论站哪都算 0 号玩家
        solo_ctx = self.state == MENU or self.active == [0]
        if solo_ctx and players[0] is None and players[1] is not None:
            players = [players[1], None]
        for idx, pup in enumerate(self.puppets):
            pup.update(players[idx], now)
        # 菜单阶段化身站位跟随人数，避免两人重叠
        if self.state == MENU:
            tracked = self._tracked_players()
            if len(tracked) >= 2:
                for i in tracked:
                    self.puppets[i].slot_x = SLOTS_DUO[i]
            elif tracked:
                self.puppets[tracked[0]].slot_x = SLOT_SOLO

    def _tracked_players(self):
        return [i for i in (0, 1) if self.puppets[i].tracked]

    # ---------------- 状态机

    def _back_to_menu(self):
        self.state = MENU
        self.state_t0 = time.monotonic()
        self.wall = None
        self.paused = False
        self.ready_t = [0.0, 0.0]
        for pup in self.puppets:
            pup.live_detail = None
            pup.live_score = 0.0

    def _start_game(self):
        if self.force_players is not None:
            self.active = list(self.force_players)
        else:
            tracked = self._tracked_players()
            self.active = tracked if tracked else [0]
        if len(self.active) == 1:
            self.puppets[self.active[0]].slot_x = SLOT_SOLO
        else:
            for i in self.active:
                self.puppets[i].slot_x = SLOTS_DUO[i]
        self.lives = {i: MAX_LIVES for i in self.active}
        self.scores = {i: 0 for i in self.active}
        self.combos = {i: 0 for i in self.active}
        self.wall = None
        self.wall_no = 0
        self.last_pose = None
        self.new_record = False
        self._calib_samples = {i: {"nose": [], "hip": []} for i in self.active}
        self.state = CALIB
        self.state_t0 = time.monotonic()
        self.announcer.say("站直别动，记录站姿…", dur=CALIB_SEC, big=False, y=0.30)
        sfx.play("ready")

    def _update_menu(self, now, dt):
        for idx in (0, 1):
            pup = self.puppets[idx]
            if pup.tracked and pup.raised:
                self.ready_t[idx] = min(READY_SEC, self.ready_t[idx] + dt)
            else:
                self.ready_t[idx] = max(0.0, self.ready_t[idx] - dt * 2)
        if any(t >= READY_SEC for t in self.ready_t):
            tracked = self._tracked_players()
            raisers = [i for i in tracked if self.ready_t[i] >= READY_SEC]
            # 有人举满 1 秒即开始；双人都在画面里就是双人局
            if raisers:
                self.ready_t = [0.0, 0.0]
                self._start_game()

    def _update_calib(self, now):
        for i in self.active:
            pup = self.puppets[i]
            if pup.tracked and pup.pts:
                if "nose" in pup.pts:
                    self._calib_samples[i]["nose"].append(pup.pts["nose"][1])
                if "l_hip" in pup.pts and "r_hip" in pup.pts:
                    hy = (pup.pts["l_hip"][1] + pup.pts["r_hip"][1]) / 2
                    self._calib_samples[i]["hip"].append(hy)
        if now - self.state_t0 >= CALIB_SEC:
            for i in self.active:
                pup = self.puppets[i]
                for key, attr in (("nose", "stand_nose_y"), ("hip", "stand_hip_y")):
                    samples = sorted(self._calib_samples[i][key])
                    if samples:
                        setattr(pup, attr, samples[len(samples) // 2])
            self.state = PLAY
            self.state_t0 = now
            self.next_wall_at = now + 0.9
            self.announcer.say("墙来了！", dur=1.0, color=(255, 220, 120))
            sfx.play("start")

    def _alive(self):
        return [i for i in self.active if self.lives[i] > 0]

    def _update_play(self, now, raw_dt):
        # 玩家跟丢：墙暂停逼近
        lost = [i for i in self._alive()
                if not self.puppets[i].tracked
                and now - self.puppets[i].last_tracked > 0.8]
        if lost and self.force_players is None:
            if self.wall is not None and not self.wall.judged:
                self.wall.t0 = min(self.wall.t0 + raw_dt, now)
            self.next_wall_at += raw_dt
            return

        if self.wall is None:
            if now >= self.next_wall_at:
                self._spawn_wall(now)
            return

        wall = self.wall
        if wall.judged:
            if now - wall.result_t > 0.9:
                self.wall = None
                self.next_wall_at = now + 0.5
            return

        # 实时匹配反馈
        for i in self._alive():
            pup = self.puppets[i]
            score, detail = P.match_score(wall.pose_map[i], pup.pts,
                                          pup.stand_nose_y)
            pup.live_score, pup.live_detail = score, detail

        remain = wall.dur - (now - wall.t0)
        for th in (1.0, 0.5):
            if remain <= th and th not in wall.ticks_played:
                wall.ticks_played.add(th)
                sfx.play("tick")
        if wall.progress(now) >= 1.0:
            self._judge_wall(wall, now)

    def _spawn_wall(self, now):
        self.wall_no += 1
        tier = 1 if self.wall_no < 4 else (2 if self.wall_no < 9 else 3)
        dur = max(2.4, 4.6 - self.wall_no * 0.14)
        pose_map = {}
        for i in self._alive():
            pose = P.random_pose(tier, exclude=self.last_pose, rng=self.rng)
            pose_map[i] = pose
            self.last_pose = pose
        slots = {i: self.puppets[i].slot_x for i in pose_map}
        self.wall = Wall(self.wall_no, pose_map, dur, slots)
        if self.wall_no in (4, 9):
            self.announcer.say("新姿势解锁！", dur=1.2, big=False,
                               color=(255, 220, 120), y=0.24)

    def _judge_wall(self, wall, now):
        wall.judged = True
        wall.result_t = now
        slots = wall.slots
        any_fail = False
        for i, pose in wall.pose_map.items():
            pup = self.puppets[i]
            score, detail = P.match_score(pose, pup.pts if pup.tracked else None,
                                          pup.stand_nose_y)
            passed = score >= P.PASS_SCORE
            wall.results[i] = (score, passed, detail)
            x = slots[i]
            if passed:
                self.combos[i] += 1
                gained = int(score * 100) + self.combos[i] * 5
                self.scores[i] += gained
                if score >= 0.9:
                    grade, col = "完美穿越！", (255, 230, 120)
                    sfx.play("perfect")
                else:
                    grade, col = "穿过！", (140, 255, 160)
                    sfx.play("pass")
                surf = self.font_mid.render(f"{grade} +{gained}", True, col)
                self.texts.append(FloatText(surf, x, H * 0.42, life=1.1))
                if self.combos[i] >= 3:
                    sfx.play("combo")
                    csurf = self.font_small.render(
                        f"连穿 {self.combos[i]} 面墙！", True,
                        self.puppets[i].color)
                    self.texts.append(FloatText(csurf, x, H * 0.50, life=1.0))
            else:
                any_fail = True
                self.combos[i] = 0
                self.lives[i] -= 1
                # 指出问题最大的部位
                worst = min(detail, key=detail.get)
                msg = f"撞墙！{P.COMPONENT_NAMES[worst]}不对"
                surf = self.font_mid.render(msg, True, (255, 110, 100))
                self.texts.append(FloatText(surf, x, H * 0.42, life=1.3))
                for _ in range(30):   # 泡沫碎块
                    a = random.uniform(0, math.tau)
                    spd = random.uniform(120, 620)
                    self.particles.append(Particle(
                        x + random.uniform(-90, 90),
                        H * 0.4 + random.uniform(-120, 120),
                        math.cos(a) * spd, math.sin(a) * spd - 150,
                        random.uniform(4, 9),
                        random.choice((WALL_FACE, WALL_GRID, (220, 235, 250))),
                        random.uniform(0.5, 0.9), grav=1100))
            pup.live_detail = None
        if any_fail:
            sfx.play("crash")
            self.flash = 0.45
            self.shake_until = now + 0.4
        if not self._alive():
            self._game_over(now)

    def _game_over(self, now):
        self.state = OVER
        self.state_t0 = now
        self.ready_t = [0.0, 0.0]
        if len(self.active) == 1:
            score = self.scores[self.active[0]]
            if score > self.best:
                self.best = score
                self.new_record = True
                self._save_best()
                sfx.play("record")
        sfx.play("game_over")

    def _update_over(self, now, dt):
        if now - self.state_t0 < 1.5:
            return
        for idx in self.active:
            pup = self.puppets[idx]
            if pup.tracked and pup.raised:
                self.ready_t[idx] = min(READY_SEC, self.ready_t[idx] + dt)
            else:
                self.ready_t[idx] = max(0.0, self.ready_t[idx] - dt * 2)
        if any(t >= READY_SEC for t in self.ready_t):
            self._start_game()

    # ---------------- 绘制

    def _draw_hud(self, now):
        # 每个参战玩家：分数 / 连击 / 命
        for i in self.active:
            left = (i == 0) if len(self.active) > 1 else True
            x0 = 36 if left else W - 36
            col = self.puppets[i].color
            s = self.font_big.render(f"{self.scores[i]}", True, (255, 255, 255))
            rect = s.get_rect(topleft=(x0, 24)) if left else \
                s.get_rect(topright=(x0, 24))
            self.scene.blit(s, rect)
            name = self.font_small.render(
                f"{PLAYER_NAMES[i]}方" if len(self.active) > 1 else
                (f"最高 {self.best}" if self.best else ""), True, col)
            nrect = name.get_rect(topleft=(x0, 84)) if left else \
                name.get_rect(topright=(x0, 84))
            self.scene.blit(name, nrect)
            for k in range(MAX_LIVES):
                alive = k < self.lives[i]
                cx = (x0 + 14 + k * 34) if left else (x0 - 14 - k * 34)
                color = (235, 70, 85) if alive else (80, 80, 90)
                pygame.draw.circle(self.scene, color, (cx, 130), 11)
                pygame.draw.circle(self.scene, (240, 240, 245), (cx, 130), 11, 2)

        title = self.font_mid.render(f"第 {self.wall_no} 面墙", True,
                                     (220, 225, 240))
        self.scene.blit(title, title.get_rect(center=(W / 2, 40)))

        # 逼近阶段：每人头顶的实时匹配条
        if self.wall is not None and not self.wall.judged:
            for i in self._alive():
                pup = self.puppets[i]
                if not pup.joints:
                    continue
                head = pup.joints.get("head", (pup.slot_x, H * 0.4))
                bx, by = int(head[0]) - 70, int(head[1]) - 76
                pct = pup.live_score
                fill_col = (95, 230, 125) if pct >= P.PASS_SCORE else (235, 95, 85)
                pygame.draw.rect(self.scene, (25, 25, 38), (bx, by, 140, 16))
                pygame.draw.rect(self.scene, fill_col,
                                 (bx, by, int(140 * pct), 16))
                pygame.draw.rect(self.scene, (235, 235, 245),
                                 (bx - 1, by - 1, 142, 18), 2)
                mark = bx + int(140 * P.PASS_SCORE)
                pygame.draw.line(self.scene, (255, 230, 120),
                                 (mark, by - 3), (mark, by + 18), 2)

    def _draw_pip(self):
        pw, ph = 256, 144
        x0, y0 = W - pw - 16, H - ph - 16
        if self.pip_surface is not None:
            img = pygame.transform.smoothscale(self.pip_surface, (pw, ph))
            self.scene.blit(img, (x0, y0))
            if len(self.active) > 1 or (self.state == MENU and
                                        len(self._tracked_players()) > 1):
                pygame.draw.line(self.scene, (255, 220, 100),
                                 (x0 + pw // 2, y0), (x0 + pw // 2, y0 + ph), 2)
        elif self.tracker is not None:
            pygame.draw.rect(self.scene, (20, 20, 30), (x0, y0, pw, ph))
            msg = self.tracker_error or "正在打开摄像头…"
            surf = self.font_small.render(msg[:18], True, (230, 150, 150))
            self.scene.blit(surf, surf.get_rect(center=(x0 + pw / 2, y0 + ph / 2)))
        else:
            return
        players = self._tracked_players()
        ok = bool(players) and all(
            i in players for i in (self.active or players))
        pygame.draw.rect(self.scene, (90, 220, 120) if ok else (235, 90, 80),
                         (x0 - 2, y0 - 2, pw + 4, ph + 4), 3)

    def _draw_menu(self, now):
        title = self.font_huge.render("缩墙勇士", True, (255, 255, 255))
        shadow = self.font_huge.render("缩墙勇士", True, (80, 120, 200))
        rect = title.get_rect(center=(W / 2, H * 0.16))
        self.scene.blit(shadow, rect.move(5, 5))
        self.scene.blit(title, rect)
        lines = [
            "带人形洞的墙会压过来——在它到达前摆出洞的姿势！",
            "手臂方向、下蹲、身体左右倾斜都要对上，匹配条变绿才能穿过",
            "撞墙掉一条命，3 条命用完游戏结束；越往后墙越快",
            "一个人玩是闯关；两个人同时入画自动双人对抗，各有各的洞",
        ]
        for i, line in enumerate(lines):
            surf = self.font_small.render(line, True, (222, 226, 238))
            self.scene.blit(surf, surf.get_rect(center=(W / 2, H * 0.28 + i * 33)))
        n = len(self._tracked_players())
        status = f"当前检测到 {n} 位玩家" + ("（双人模式）" if n >= 2 else
                                              "（单人模式）" if n == 1 else
                                              "——请站到摄像头前")
        col = (140, 255, 160) if n else (235, 110, 100)
        surf = self.font_mid.render(status, True, col)
        self.scene.blit(surf, surf.get_rect(center=(W / 2, H * 0.52)))
        prompt = self.font_mid.render("举手保持 1 秒开始（或按空格）", True,
                                      (160, 255, 180))
        self.scene.blit(prompt, prompt.get_rect(center=(W / 2, H * 0.60)))
        for idx in (0, 1):
            if self.ready_t[idx] > 0:
                cx = W * (0.5 if n <= 1 else (0.3 if idx == 0 else 0.7))
                pygame.draw.arc(self.scene, (255, 230, 140),
                                (cx - 36, H * 0.66, 72, 72), math.pi / 2,
                                math.pi / 2 + self.ready_t[idx] / READY_SEC
                                * math.tau, 6)
        if self.best:
            surf = self.font_small.render(f"单人最高纪录 {self.best}", True,
                                          (255, 225, 140))
            self.scene.blit(surf, surf.get_rect(center=(W / 2, H * 0.90)))

    def _draw_over(self, now):
        overlay = pygame.Surface((W, H))
        overlay.set_alpha(130)
        self.scene.blit(overlay, (0, 0))
        title = self.font_huge.render("游戏结束", True, (255, 120, 105))
        self.scene.blit(title, title.get_rect(center=(W / 2, H * 0.24)))
        if len(self.active) == 1:
            i = self.active[0]
            s = self.font_big.render(f"挑战到第 {self.wall_no} 面墙 · 得分 {self.scores[i]}",
                                     True, (255, 255, 255))
            self.scene.blit(s, s.get_rect(center=(W / 2, H * 0.40)))
            if self.new_record:
                pulse = 1 + 0.05 * math.sin(now * 6)
                surf = self.font_mid.render("新纪录！", True, (255, 225, 120))
                img = pygame.transform.rotozoom(surf, 0, pulse)
                self.scene.blit(img, img.get_rect(center=(W / 2, H * 0.50)))
            else:
                surf = self.font_small.render(f"最高纪录 {self.best}", True,
                                              (230, 230, 170))
                self.scene.blit(surf, surf.get_rect(center=(W / 2, H * 0.50)))
        else:
            s0, s1 = self.scores.get(0, 0), self.scores.get(1, 0)
            if s0 == s1:
                verdict = "平手！"
                col = (255, 255, 255)
            else:
                wi = 0 if s0 > s1 else 1
                verdict = f"{PLAYER_NAMES[wi]}方获胜！"
                col = self.puppets[wi].color
            s = self.font_big.render(verdict, True, col)
            self.scene.blit(s, s.get_rect(center=(W / 2, H * 0.38)))
            sc = self.font_mid.render(f"{s0} : {s1}", True, (255, 255, 255))
            self.scene.blit(sc, sc.get_rect(center=(W / 2, H * 0.48)))
        if now - self.state_t0 > 1.5:
            hint = self.font_mid.render("举手 1 秒再来一局（或按 R）", True,
                                        (160, 255, 180))
            self.scene.blit(hint, hint.get_rect(center=(W / 2, H * 0.62)))

    def _draw(self, now):
        self.scene.blit(self.stage, (0, 0))
        if self.wall is not None:
            self.wall.draw(self.scene, now)
        show = self.active if self.state in (PLAY, CALIB, OVER) else \
            self._tracked_players()
        for i in show:
            dead = self.state in (PLAY, OVER) and self.lives.get(i, 1) <= 0
            self.puppets[i].draw(self.scene, now, dead=dead)
        for p in self.particles:
            p.draw(self.scene, now)
        self.texts = [t for t in self.texts if t.draw(self.scene, now)]

        if self.state == MENU:
            self._draw_menu(now)
        elif self.state in (PLAY, CALIB):
            self._draw_hud(now)
        elif self.state == OVER:
            self._draw_hud(now)
            self._draw_over(now)
        if self.paused:
            surf = self.font_big.render("已暂停（按 P 继续）", True,
                                        (255, 255, 255))
            self.scene.blit(surf, surf.get_rect(center=(W / 2, H / 2)))
        self._draw_pip()
        self.announcer.draw(self.scene, now)

        if self.flash > 0:
            white = pygame.Surface((W, H))
            white.fill((255, 248, 240))
            white.set_alpha(int(180 * self.flash))
            self.scene.blit(white, (0, 0))
        ox = oy = 0
        if now < self.shake_until:
            amp = 12 * (self.shake_until - now) / 0.4
            ox, oy = int(random.uniform(-amp, amp)), int(random.uniform(-amp, amp))
            self.screen.fill((0, 0, 0))
        self.screen.blit(self.scene, (ox, oy))
        pygame.display.flip()


def main():
    parser = argparse.ArgumentParser(description="缩墙勇士：体感穿墙")
    parser.add_argument("--camera", type=int, default=0, help="摄像头编号")
    args = parser.parse_args()
    Game(camera_index=args.camera).run()


if __name__ == "__main__":
    main()
