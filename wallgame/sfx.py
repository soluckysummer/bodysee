"""缩墙勇士音效，全部 numpy 合成（wallgame/assets/，git 忽略）。"""

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


def _pass_():
    """穿墙成功：上扬的呼啸 + 清亮的叮。"""
    n = int(SR * 0.3)
    noise = _noise(0.3, 7)
    mix = np.linspace(0, 1, n)
    wh = (_lowpass(noise, 30) * (1 - mix) + _lowpass(noise, 5) * mix)
    wh *= np.sin(np.pi * np.linspace(0, 1, n)) ** 2 * 0.5
    ding = _tone(1047, 0.5, k=6) + _tone(1568, 0.5, k=8) * 0.5
    out = np.zeros(int(SR * 0.7))
    out[:n] += wh
    out[int(SR * 0.12):int(SR * 0.12) + len(ding)] += ding * 0.55
    return out


def _perfect():
    """满分：三连上行琶音。"""
    notes = [(784, 0.1), (1047, 0.1), (1319, 0.35)]
    parts = [_tone(f, d, k=6, harmonics=((1, 1.0), (2, 0.4))) for f, d in notes]
    return np.concatenate(parts) * 0.6


def _crash():
    """撞墙：闷响 + 泡沫碎裂的碎屑声。"""
    dur = 0.7
    n = int(SR * dur)
    thud = _lowpass(_noise(dur, 3), 40) * _env_decay(n, 8) + _tone(70, dur, k=6)
    crackle = _noise(dur, 8) * (np.random.default_rng(4).random(n) > 0.92)
    crackle = _lowpass(crackle, 2) * _env_decay(n, 5)
    return np.tanh((thud * 1.3 + crackle * 0.8) * 1.6) * 0.9


def _tick():
    return _tone(1500, 0.05, k=10) * 0.4


def _start():
    return np.concatenate([_tone(523, 0.12, k=6), _tone(784, 0.25, k=5)]) * 0.6


def _ready():
    return np.concatenate([_tone(660, 0.1, k=8), _tone(990, 0.2, k=7)]) * 0.6


def _combo():
    return (_tone(880, 0.3, k=7) + _tone(1320, 0.3, k=9) * 0.5) * 0.5


def _game_over():
    notes = [(392, 0.22), (330, 0.22), (262, 0.55)]
    parts = [_tone(f, d, k=5, harmonics=((1, 1.0), (2, 0.3))) for f, d in notes]
    return np.concatenate(parts) * 0.6


def _record():
    notes = [(523, 0.14), (659, 0.14), (784, 0.14), (1047, 0.5)]
    parts = [_tone(f, d, k=5, harmonics=((1, 1.0), (2, 0.35))) for f, d in notes]
    return np.concatenate(parts) * 0.55


_GENERATORS = {
    "pass": _pass_, "perfect": _perfect, "crash": _crash, "tick": _tick,
    "start": _start, "ready": _ready, "combo": _combo,
    "game_over": _game_over, "record": _record,
}

_VOLUMES = {
    "pass": 0.85, "perfect": 0.85, "crash": 1.0, "tick": 0.5,
    "start": 0.8, "ready": 0.7, "combo": 0.7, "game_over": 0.9, "record": 0.85,
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
