"""程序合成的立体声音效和四层自适应音乐。"""

import math
import wave
from pathlib import Path

import numpy as np
import pygame

from stargame.notes import BEAT

SR = 22050
ASSETS = Path(__file__).parent / "assets"

_sounds = {}
_music_channels = []
_ready = False


def _envelope(length, attack=0.02, release=0.18):
    env = np.ones(length)
    a = min(length, int(SR * attack))
    r = min(length, int(SR * release))
    if a:
        env[:a] = np.linspace(0.0, 1.0, a)
    if r:
        env[-r:] *= np.linspace(1.0, 0.0, r)
    return env


def _tone(freq, duration, amp=0.6, kind="sine"):
    length = max(1, int(SR * duration))
    t = np.arange(length) / SR
    phase = 2 * np.pi * freq * t
    if kind == "triangle":
        signal = 2 / np.pi * np.arcsin(np.sin(phase))
    else:
        signal = np.sin(phase)
    return signal * _envelope(length) * amp


def _sweep(start_freq, end_freq, duration, amp=0.6):
    length = max(1, int(SR * duration))
    freqs = np.linspace(start_freq, end_freq, length)
    phase = 2 * np.pi * np.cumsum(freqs) / SR
    return np.sin(phase) * _envelope(length, 0.01, duration * 0.45) * amp


def _stereo(mono, pan=0.0):
    pan = max(-1.0, min(1.0, pan))
    angle = (pan + 1.0) * math.pi / 4.0
    return np.column_stack((mono * math.cos(angle), mono * math.sin(angle)))


def _event_sounds():
    perfect = (_tone(880, 0.34, 0.55) + _tone(1320, 0.34, 0.32)
               + _tone(1760, 0.34, 0.18))
    great = _tone(660, 0.25, 0.55) + _tone(990, 0.25, 0.24)
    good = _tone(440, 0.18, 0.48, "triangle")
    miss = _sweep(190, 105, 0.28, 0.42)
    tick = _tone(1000, 0.07, 0.35)
    start = np.concatenate((_tone(392, 0.13, 0.45), _tone(523, 0.13, 0.5),
                            _tone(784, 0.28, 0.65)))
    supernova = _sweep(90, 720, 0.8, 0.48)
    supernova += _tone(110, 0.8, 0.35)
    finish = np.concatenate((_tone(523, 0.18, 0.45), _tone(659, 0.18, 0.5),
                             _tone(784, 0.18, 0.55), _tone(1047, 0.55, 0.65)))
    return {
        "perfect": _stereo(perfect),
        "great": _stereo(great),
        "good": _stereo(good),
        "miss": _stereo(miss),
        "tick": _stereo(tick),
        "start": _stereo(start),
        "supernova": _stereo(supernova),
        "finish": _stereo(finish),
    }


def _add_note(buffer, start, duration, freq, amp, pan=0.0, kind="sine"):
    mono = _tone(freq, duration, amp, kind)
    stereo = _stereo(mono, pan)
    offset = int(start * SR)
    end = min(len(buffer), offset + len(stereo))
    if end > offset:
        buffer[offset:end] += stereo[:end - offset]


def _music_stems():
    duration = 8 * BEAT
    length = int(duration * SR)
    ambient = np.zeros((length, 2))
    beat = np.zeros((length, 2))
    melody = np.zeros((length, 2))
    power = np.zeros((length, 2))

    chords = ((130.81, 164.81, 196.00), (110.00, 130.81, 164.81),
              (87.31, 110.00, 130.81), (98.00, 123.47, 146.83))
    for index, chord in enumerate(chords):
        start = index * 2 * BEAT
        for frequency in chord:
            _add_note(ambient, start, 2 * BEAT, frequency, 0.11)
            _add_note(ambient, start, 2 * BEAT, frequency * 2, 0.035,
                      pan=-0.35 if index % 2 == 0 else 0.35)

    rng = np.random.default_rng(17)
    for index in range(8):
        start = index * BEAT
        kick_len = int(0.22 * SR)
        t = np.arange(kick_len) / SR
        kick = np.sin(2 * np.pi * (85 - 48 * t / 0.22) * t)
        kick *= np.exp(-18 * t) * 0.58
        beat[int(start * SR):int(start * SR) + kick_len] += _stereo(kick)
        bass_freq = (65.41, 55.00, 43.65, 49.00)[index // 2]
        _add_note(beat, start, BEAT * 0.72, bass_freq, 0.20, kind="triangle")
        for half in (0.0, 0.5):
            offset = int((start + half * BEAT) * SR)
            hat_len = int(0.045 * SR)
            noise = rng.standard_normal(hat_len) * np.exp(
                -np.linspace(0, 8, hat_len)) * 0.07
            beat[offset:offset + hat_len] += _stereo(noise, 0.45 if half else -0.45)

    scale = (523.25, 659.25, 783.99, 659.25, 587.33, 698.46, 880.00, 783.99)
    for index, frequency in enumerate(scale):
        _add_note(melody, index * BEAT, BEAT * 0.65, frequency, 0.19,
                  pan=-0.5 + index / 7.0, kind="triangle")

    arp = (1046.50, 1318.51, 1567.98, 2093.00)
    for index in range(16):
        _add_note(power, index * BEAT / 2, BEAT * 0.28,
                  arp[index % len(arp)], 0.13,
                  pan=-0.75 if index % 2 == 0 else 0.75)

    return {"ambient": ambient, "beat": beat, "melody": melody, "power": power}


def _write_wav(path, data):
    peak = max(1.0, float(np.max(np.abs(data))))
    pcm = np.clip(data / peak, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SR)
        wav.writeframes(pcm.tobytes())


def init():
    global _ready
    ASSETS.mkdir(exist_ok=True)
    generated = {**_event_sounds(), **_music_stems()}
    for name, samples in generated.items():
        path = ASSETS / f"{name}.wav"
        if not path.exists():
            _write_wav(path, samples)
        _sounds[name] = pygame.mixer.Sound(str(path))
    pygame.mixer.set_num_channels(12)
    _ready = True


def start_music():
    global _music_channels
    if not _ready:
        return
    stop_music()
    _music_channels = []
    for channel_index, name in enumerate(("ambient", "beat", "melody", "power")):
        channel = pygame.mixer.Channel(channel_index)
        channel.play(_sounds[name], loops=-1)
        _music_channels.append(channel)
    update_music(0, 60, False)


def update_music(combo, energy, supernova):
    if len(_music_channels) != 4:
        return
    targets = (0.34, 0.28 if combo >= 4 else 0.16,
               0.24 if combo >= 10 else 0.0,
               0.24 if supernova else (0.10 if combo >= 25 else 0.0))
    if energy < 25:
        targets = (0.28, 0.12, 0.0, 0.0)
    for channel, volume in zip(_music_channels, targets):
        channel.set_volume(volume)


def stop_music(fade_ms=350):
    global _music_channels
    for channel in _music_channels:
        channel.fadeout(fade_ms)
    _music_channels = []


def play(name, pan=0.0):
    if not _ready or name not in _sounds:
        return
    channel = pygame.mixer.find_channel(True)
    channel.play(_sounds[name])
    pan = max(-1.0, min(1.0, pan))
    channel.set_volume(0.72 * (1.0 - max(0.0, pan)),
                       0.72 * (1.0 + min(0.0, pan)))
