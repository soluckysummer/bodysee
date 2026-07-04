"""程序化绘制的游戏素材：西瓜、金瓜、炸弹、心形血量、暗角遮罩。

全部用 pygame 画出来，不依赖图片文件；启动时生成一次，之后旋转复用。
"""

import math
import random

import pygame

# 西瓜配色
RIND_DARK = (24, 110, 45)
RIND_LIGHT = (60, 168, 82)
RIND_STRIPE = (18, 82, 34)
RIND_INNER = (225, 245, 215)
FLESH = (235, 60, 70)
FLESH_DEEP = (205, 38, 52)
SEED = (35, 22, 20)

# 金瓜配色
GOLD_DARK = (190, 140, 20)
GOLD_LIGHT = (255, 208, 70)
GOLD_STRIPE = (160, 112, 12)
GOLD_FLESH = (255, 176, 40)

BOMB_BODY = (38, 38, 46)
BOMB_EDGE = (16, 16, 22)


def _circle_mask(size, center, radius):
    mask = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.circle(mask, (255, 255, 255, 255), center, radius)
    return mask


def _clip_circle(surface, center, radius):
    """把 surface 上圆外的像素裁掉（alpha 取 min）。"""
    surface.blit(_circle_mask(surface.get_size(), center, radius),
                 (0, 0), special_flags=pygame.BLEND_RGBA_MIN)


def make_melon(radius, gold=False):
    """整个西瓜，返回 Surface（含少量留白便于旋转）。"""
    dark, light, stripe = ((GOLD_DARK, GOLD_LIGHT, GOLD_STRIPE) if gold
                           else (RIND_DARK, RIND_LIGHT, RIND_STRIPE))
    pad = 6
    size = (radius + pad) * 2
    c = (size // 2, size // 2)
    surf = pygame.Surface((size, size), pygame.SRCALPHA)

    pygame.draw.circle(surf, dark, c, radius)
    pygame.draw.circle(surf, light, c, radius - 3)
    # 深色条纹：一组越来越扁的同心竖椭圆弧线
    for f in (0.25, 0.5, 0.75):
        w = int(radius * 2 * f)
        rect = pygame.Rect(0, 0, w, radius * 2 - 4)
        rect.center = c
        pygame.draw.ellipse(surf, stripe, rect, 5)
    pygame.draw.line(surf, stripe, (c[0], c[1] - radius + 3),
                     (c[0], c[1] + radius - 3), 5)
    _clip_circle(surf, c, radius - 3)
    # 补回外圈深色轮廓
    pygame.draw.circle(surf, dark, c, radius, 3)

    # 左上高光
    hl = pygame.Surface((size, size), pygame.SRCALPHA)
    rect = pygame.Rect(0, 0, int(radius * 0.9), int(radius * 0.5))
    rect.center = (c[0] - radius * 0.35, c[1] - radius * 0.5)
    pygame.draw.ellipse(hl, (255, 255, 255, 70), rect)
    _clip_circle(hl, c, radius - 4)
    surf.blit(hl, (0, 0))

    if gold:  # 金瓜外发光，一眼认出是高分目标
        glow_size = size + 24
        glow = pygame.Surface((glow_size, glow_size), pygame.SRCALPHA)
        gc = glow_size // 2
        for i, alpha in ((12, 40), (7, 70), (3, 110)):
            pygame.draw.circle(glow, (255, 220, 90, alpha), (gc, gc), radius + i)
        glow.blit(surf, (12, 12))
        return glow
    return surf


def make_melon_half(radius, gold=False):
    """半个西瓜（切面朝上），旋转后配合切割方向使用。"""
    dark, flesh = (GOLD_DARK, GOLD_FLESH) if gold else (RIND_DARK, FLESH)
    pad = 6
    size = (radius + pad) * 2
    c = (size // 2, size // 2)
    surf = pygame.Surface((size, size), pygame.SRCALPHA)

    pygame.draw.circle(surf, dark, c, radius)
    pygame.draw.circle(surf, RIND_INNER, c, radius - 5)
    pygame.draw.circle(surf, flesh, c, radius - 9)
    if not gold:
        # 果肉里的深色放射纹和瓜子
        for ang_deg in (210, 250, 290, 330):
            a = math.radians(ang_deg)
            x = c[0] + math.cos(a) * (radius - 16)
            y = c[1] + math.sin(a) * (radius - 16)
            pygame.draw.line(surf, FLESH_DEEP, c, (x, y), 2)
        rng = random.Random(42)
        for ang_deg in (200, 225, 255, 285, 315, 340):
            a = math.radians(ang_deg)
            dist = (radius - 9) * rng.uniform(0.45, 0.8)
            x = c[0] + math.cos(a) * dist
            y = c[1] + math.sin(a) * dist
            seed_rect = pygame.Rect(0, 0, 7, 10)
            seed_rect.center = (x, y)
            rot = pygame.Surface((12, 14), pygame.SRCALPHA)
            pygame.draw.ellipse(rot, SEED, pygame.Rect(2, 2, 7, 10))
            rot = pygame.transform.rotate(rot, math.degrees(-a) + 90)
            surf.blit(rot, rot.get_rect(center=(x, y)))

    # 只留下半圆（切面是上边缘的平直线）
    surf.fill((0, 0, 0, 0), pygame.Rect(0, 0, size, c[1]))
    pygame.draw.line(surf, RIND_INNER if not gold else GOLD_LIGHT,
                     (c[0] - radius, c[1]), (c[0] + radius, c[1]), 4)
    return surf


def make_bomb(radius):
    pad = 14  # 引信要伸出去
    size = (radius + pad) * 2
    c = (size // 2, size // 2 + 6)
    surf = pygame.Surface((size, size), pygame.SRCALPHA)

    # 引信
    fuse_top = (c[0] + 6, c[1] - radius - 14)
    pygame.draw.line(surf, (120, 90, 55), (c[0], c[1] - radius + 4), fuse_top, 5)
    # 弹体：径向渐变的黑球
    pygame.draw.circle(surf, BOMB_EDGE, c, radius)
    for i in range(radius, 0, -2):
        t = i / radius
        col = (int(BOMB_BODY[0] + (90 - BOMB_BODY[0]) * (1 - t) ** 2),
               int(BOMB_BODY[1] + (90 - BOMB_BODY[1]) * (1 - t) ** 2),
               int(BOMB_BODY[2] + (105 - BOMB_BODY[2]) * (1 - t) ** 2))
        pygame.draw.circle(surf, col,
                           (c[0] - (radius - i) * 0.3, c[1] - (radius - i) * 0.35), i)
    _clip_circle(surf, c, radius)
    pygame.draw.line(surf, (120, 90, 55), (c[0], c[1] - radius + 4), fuse_top, 5)
    pygame.draw.circle(surf, BOMB_EDGE, c, radius, 3)
    # 高光
    rect = pygame.Rect(0, 0, int(radius * 0.7), int(radius * 0.4))
    rect.center = (c[0] - radius * 0.35, c[1] - radius * 0.45)
    hl = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.ellipse(hl, (255, 255, 255, 60), rect)
    _clip_circle(hl, c, radius - 2)
    surf.blit(hl, (0, 0))
    # 危险标记
    skull = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.circle(skull, (225, 60, 60), c, int(radius * 0.42), 4)
    pygame.draw.line(skull, (225, 60, 60),
                     (c[0] - radius * 0.28, c[1] + radius * 0.28),
                     (c[0] + radius * 0.28, c[1] - radius * 0.28), 4)
    surf.blit(skull, (0, 0))
    # 引信火花挂点（游戏内在此叠加动态火花）
    return surf, (fuse_top[0] - size // 2, fuse_top[1] - size // 2)


def make_heart(h, alive=True):
    """心形血量图标；alive=False 画灰色空心。"""
    w = h
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    color = (235, 65, 80) if alive else (110, 110, 115)
    r = h * 0.27
    c1 = (w * 0.32, h * 0.34)
    c2 = (w * 0.68, h * 0.34)
    bottom = (w * 0.5, h * 0.92)
    left = (w * 0.06, h * 0.42)
    right = (w * 0.94, h * 0.42)
    pygame.draw.polygon(surf, color, (left, right, bottom))
    pygame.draw.circle(surf, color, c1, r)
    pygame.draw.circle(surf, color, c2, r)
    if not alive:
        inner = pygame.transform.smoothscale(surf, (int(w * 0.62), int(h * 0.62)))
        dark = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        dark.blit(inner, inner.get_rect(center=(w // 2, int(h * 0.52))))
        dark.fill((30, 30, 34, 255), special_flags=pygame.BLEND_RGBA_MULT)
        surf.blit(dark, (0, 0))
    else:
        pygame.draw.circle(surf, (255, 255, 255, 130),
                           (int(w * 0.3), int(h * 0.28)), int(r * 0.32))
    return surf


def make_vignette(size):
    """四周压暗的遮罩，让镜头画面更有"舞台感"。"""
    small_w, small_h = 160, 90
    small = pygame.Surface((small_w, small_h), pygame.SRCALPHA)
    cx, cy = small_w / 2, small_h / 2
    max_d = math.hypot(cx, cy)
    for y in range(small_h):
        for x in range(small_w):
            d = math.hypot(x - cx, y - cy) / max_d
            alpha = int(max(0.0, d - 0.55) / 0.45 * 170)
            small.set_at((x, y), (0, 0, 10, alpha))
    return pygame.transform.smoothscale(small, size)
