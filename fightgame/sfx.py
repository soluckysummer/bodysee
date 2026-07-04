"""格斗游戏音效，全部 numpy 合成（fightgame/assets/，git 忽略）。"""

import wave
from pathlib import Path

import numpy as np
import pygame

SR = 22050
ASSETS = Path(__file__).parent / "assets"

_sounds = {}


def _env_decay(n, k=6.0):
    return np.exp(-k * np.linspace(0, 1, n))


def _lowpass(x, width):
    return np.convolve(x, np.ones(width) / width, mode="same")


def _tone(freq, dur, k=6.0, harmonics=((1, 1.0),)):
    n = int(SR * dur)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for mult, amp in harmonics:
        x += amp * np.sin(2 * np.pi * freq * mult * t)
    return x * _env_decay(n, k)


def _sweep(f0, f1, dur, k=5.0):
    n = int(SR * dur)
    freq = np.linspace(f0, f1, n)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return np.sin(phase) * _env_decay(n, k)


def _noise(dur, seed=0):
    return np.random.default_rng(seed).standard_normal(int(SR * dur))


def _gong():
    """回合开始的锣声：不谐和分音慢衰减 + 敲击噪声。"""
    dur = 1.6
    partials = ((98, 1.0), (147.3, 0.7), (210.7, 0.5), (265.1, 0.35), (351.9, 0.2))
    x = sum(_tone(f, dur, k=3.0) * a for f, a in partials)
    strike = _lowpass(_noise(0.05, 5), 4) * _env_decay(int(SR * 0.05), 20)
    x[:len(strike)] += strike * 1.2
    return np.tanh(x * 1.2) * 0.9


def _ko_bell():
    """KO：低沉大钟 + 轰。"""
    dur = 2.2
    x = (_tone(65, dur, k=2.2) + _tone(97.6, dur, k=2.6) * 0.7
         + _tone(130.5, dur, k=3.0) * 0.5)
    boom = _lowpass(_noise(0.5, 9), 50) * _env_decay(int(SR * 0.5), 7)
    x[:len(boom)] += boom * 1.4
    return np.tanh(x * 1.4) * 0.95


def _whoosh():
    dur = 0.18
    n = int(SR * dur)
    noise = _noise(dur, 7)
    mix = np.linspace(0, 1, n)
    x = _lowpass(noise, 40) * (1 - mix) + _lowpass(noise, 6) * mix
    return x * np.sin(np.pi * np.linspace(0, 1, n)) ** 2 * 0.8


def _hit_body():
    n = int(SR * 0.13)
    burst = _lowpass(_noise(0.13, 3), 20) * _env_decay(n, 16)
    return burst * 0.9 + _tone(85, 0.13, k=13) * 0.9


def _hit_head():
    n = int(SR * 0.12)
    burst = _lowpass(_noise(0.12, 4), 7) * _env_decay(n, 18)
    ring = _tone(1250, 0.12, k=22) * 0.25
    return burst * 0.8 + _tone(170, 0.12, k=14) * 0.6 + ring


def _block():
    """格挡：金属叮 + 短促噪声。"""
    x = (_tone(920, 0.28, k=9) + _tone(1370, 0.28, k=11) * 0.6
         + _tone(2050, 0.28, k=14) * 0.35)
    tick = _lowpass(_noise(0.03, 8), 3) * _env_decay(int(SR * 0.03), 25)
    x[:len(tick)] += tick
    return x * 0.6


def _charge():
    """蓄力：上升的嗡鸣带颤音。"""
    dur = 0.9
    n = int(SR * dur)
    t = np.arange(n) / SR
    freq = np.linspace(160, 640, n)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    trem = 1 + 0.35 * np.sin(2 * np.pi * 13 * t)
    env = np.linspace(0.2, 1.0, n)
    return np.sin(phase) * trem * env * 0.45


def _fireball():
    dur = 0.4
    x = _sweep(700, 220, dur, k=4)
    return (x + _lowpass(_noise(dur, 6), 10) * _env_decay(int(SR * dur), 6)) * 0.7


def _boom():
    dur = 0.7
    n = int(SR * dur)
    rumble = _lowpass(_noise(dur, 11), 55) * _env_decay(n, 6)
    return np.tanh((rumble * 1.6 + _tone(58, dur, k=5)) * 2) * 0.9


def _win():
    notes = [(523, 0.16), (659, 0.16), (784, 0.16)]
    parts = [_tone(f, d, k=6, harmonics=((1, 1.0), (2, 0.4))) for f, d in notes]
    chord_dur = 0.9
    chord = sum(_tone(f, chord_dur, k=3.2, harmonics=((1, 1.0), (2, 0.3)))
                for f in (523, 659, 784, 1047))
    return np.concatenate(parts + [chord * 0.5]) * 0.5


def _beep():
    return _tone(1100, 0.09, k=8) * 0.5


def _ready():
    return np.concatenate([_tone(660, 0.1, k=8), _tone(990, 0.2, k=7)]) * 0.6


_GENERATORS = {
    "gong": _gong, "ko": _ko_bell, "whoosh": _whoosh,
    "hit_body": _hit_body, "hit_head": _hit_head, "block": _block,
    "charge": _charge, "fireball": _fireball, "boom": _boom,
    "win": _win, "beep": _beep, "ready": _ready,
}

_VOLUMES = {
    "gong": 0.9, "ko": 1.0, "whoosh": 0.3, "hit_body": 0.9, "hit_head": 0.95,
    "block": 0.7, "charge": 0.7, "fireball": 0.8, "boom": 0.9,
    "win": 0.8, "beep": 0.5, "ready": 0.7,
}


def _write_wav(path, data):
    data = np.clip(data, -1.0, 1.0)
    pcm = (data * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def init():
    ASSETS.mkdir(exist_ok=True)
    for name, gen in _GENERATORS.items():
        path = ASSETS / f"{name}.wav"
        if not path.exists():
            _write_wav(path, gen())
        snd = pygame.mixer.Sound(str(path))
        snd.set_volume(_VOLUMES[name])
        _sounds[name] = snd


def play(name):
    snd = _sounds.get(name)
    if snd is not None:
        snd.play()
