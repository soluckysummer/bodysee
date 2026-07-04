"""程序合成的游戏音效。

不依赖任何外部音频素材：首次运行用 numpy 合成各音效并缓存为 wav
（fruitgame/assets/，已 git 忽略），之后直接加载。
"""

import wave
from pathlib import Path

import numpy as np
import pygame

SR = 22050
ASSETS = Path(__file__).parent / "assets"

_sounds = {}


def _env_decay(n, k=6.0):
    """指数衰减包络。"""
    return np.exp(-k * np.linspace(0, 1, n))


def _lowpass(x, width):
    """滑动平均低通，width 越大声音越闷。"""
    kernel = np.ones(width) / width
    return np.convolve(x, kernel, mode="same")


def _tone(freq, dur, k=6.0, harmonics=((1, 1.0),)):
    n = int(SR * dur)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for mult, amp in harmonics:
        x += amp * np.sin(2 * np.pi * freq * mult * t)
    return x * _env_decay(n, k)


def _sweep(f0, f1, dur, k=5.0):
    n = int(SR * dur)
    t = np.arange(n) / SR
    freq = np.linspace(f0, f1, n)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return np.sin(phase) * _env_decay(n, k)


def _whoosh():
    """挥刀破空声：带包络的噪声，低通宽度扫掠出"嗖"的动感。"""
    dur = 0.22
    n = int(SR * dur)
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n)
    bright = _lowpass(noise, 6)
    dull = _lowpass(noise, 40)
    mix = np.linspace(0, 1, n)          # 由闷到亮再收尾
    x = dull * (1 - mix) + bright * mix
    env = np.sin(np.pi * np.linspace(0, 1, n)) ** 2
    return x * env * 0.8


def _splat():
    """切开西瓜：湿润的噗声 = 噪声爆发 + 低频顿感。"""
    n = int(SR * 0.18)
    rng = np.random.default_rng(3)
    burst = _lowpass(rng.standard_normal(n), 18) * _env_decay(n, 14)
    thump = _tone(95, 0.18, k=12)
    return burst * 0.9 + thump * 0.7


def _explosion():
    """炸弹爆炸：轰隆 = 重低音 + 长尾闷噪声，轻微过载增加冲击感。"""
    dur = 1.0
    n = int(SR * dur)
    rng = np.random.default_rng(11)
    rumble = _lowpass(rng.standard_normal(n), 60) * _env_decay(n, 5)
    boom = _tone(52, dur, k=4) + _tone(38, dur, k=3.5) * 0.8
    return np.tanh((rumble * 1.6 + boom * 1.2) * 2.0) * 0.95


def _launch():
    """水果出场：短促上扬的"啵"。"""
    return _sweep(260, 620, 0.1, k=6) * 0.5


def _ding():
    """连击/金瓜：清脆铃声。"""
    x = _tone(880, 0.4, k=7) + _tone(1760, 0.4, k=9) * 0.5 + _tone(2640, 0.4, k=12) * 0.25
    return x * 0.5


def _hurt():
    """掉血：下坠的低鸣。"""
    return _sweep(340, 130, 0.35, k=5) * 0.7


def _start():
    n1 = _sweep(392, 523, 0.12, k=4)
    n2 = _sweep(523, 784, 0.22, k=5)
    return np.concatenate([n1, n2]) * 0.6


def _game_over():
    notes = [(392, 0.22), (330, 0.22), (262, 0.5)]
    parts = [_tone(f, d, k=5, harmonics=((1, 1.0), (2, 0.3))) for f, d in notes]
    return np.concatenate(parts) * 0.6


_GENERATORS = {
    "whoosh": _whoosh,
    "splat": _splat,
    "explosion": _explosion,
    "launch": _launch,
    "ding": _ding,
    "hurt": _hurt,
    "start": _start,
    "game_over": _game_over,
}

_VOLUMES = {
    "whoosh": 0.35,
    "splat": 0.9,
    "explosion": 1.0,
    "launch": 0.4,
    "ding": 0.7,
    "hurt": 0.8,
    "start": 0.8,
    "game_over": 0.9,
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
    """生成缺失的音效文件并加载。需在 pygame.mixer 初始化后调用。"""
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
