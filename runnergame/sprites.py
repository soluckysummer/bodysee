"""霓虹城市与跑酷场景的程序化静态素材。"""

import random

import pygame


def make_city(size):
    rng = random.Random(88)
    surface = pygame.Surface(size, pygame.SRCALPHA)
    horizon = int(size[1] * 0.33)
    x = 0
    palette = ((12, 20, 48, 235), (17, 27, 62, 240), (22, 31, 72, 230))
    while x < size[0]:
        width = rng.randint(48, 105)
        height = rng.randint(70, 210)
        rect = pygame.Rect(x, horizon - height, width, height)
        pygame.draw.rect(surface, rng.choice(palette), rect)
        for wx in range(x + 11, x + width - 8, 18):
            for wy in range(rect.top + 14, rect.bottom - 8, 22):
                if rng.random() < 0.38:
                    color = rng.choice(((85, 231, 255, 85), (255, 173, 66, 75),
                                        (181, 124, 255, 70)))
                    pygame.draw.rect(surface, color, (wx, wy, 6, 9))
        x += width + rng.randint(5, 16)
    pygame.draw.line(surface, (85, 231, 255, 95), (0, horizon),
                     (size[0], horizon), 2)
    return surface


def make_scanlines(size):
    surface = pygame.Surface(size, pygame.SRCALPHA)
    for y in range(0, size[1], 5):
        pygame.draw.line(surface, (5, 8, 24, 16), (0, y), (size[0], y))
    return surface


def make_vignette(size):
    surface = pygame.Surface(size, pygame.SRCALPHA)
    edge = 88
    for index in range(edge):
        alpha = int((1 - index / edge) ** 2 * 95)
        pygame.draw.rect(surface, (2, 4, 15, alpha),
                         (index, index, size[0] - index * 2, size[1] - index * 2), 1)
    return surface
