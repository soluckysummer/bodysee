"""星核舞台的程序化静态素材。"""

import math
import random

import pygame


def make_starfield(size, count=150):
    rng = random.Random(29)
    surface = pygame.Surface(size, pygame.SRCALPHA)
    for _ in range(count):
        x = rng.randrange(size[0])
        y = rng.randrange(size[1])
        radius = rng.choice((1, 1, 1, 2))
        alpha = rng.randrange(55, 170)
        color = rng.choice(((85, 231, 255, alpha), (181, 124, 255, alpha),
                            (255, 255, 255, alpha)))
        pygame.draw.circle(surface, color, (x, y), radius)
    return surface


def make_vignette(size):
    small_size = (160, 90)
    surface = pygame.Surface(small_size, pygame.SRCALPHA)
    cx, cy = small_size[0] / 2, small_size[1] / 2
    max_distance = math.hypot(cx, cy)
    for y in range(small_size[1]):
        for x in range(small_size[0]):
            distance = math.hypot(x - cx, y - cy) / max_distance
            alpha = int(max(0.0, distance - 0.40) / 0.60 * 205)
            surface.set_at((x, y), (2, 5, 18, alpha))
    return pygame.transform.smoothscale(surface, size)


def make_glow(radius, color, strength=150):
    size = radius * 4
    center = size // 2
    surface = pygame.Surface((size, size), pygame.SRCALPHA)
    for current in range(radius * 2, 2, -3):
        ratio = 1.0 - current / (radius * 2)
        alpha = int(strength * ratio * ratio * 0.16)
        pygame.draw.circle(surface, (*color, alpha), (center, center), current)
    pygame.draw.circle(surface, (*color, min(255, strength)),
                       (center, center), max(2, radius // 3), 2)
    return surface
