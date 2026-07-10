"""程序合成的跑酷音效和三层自适应电子音乐。"""

import math
import wave
from pathlib import Path

import numpy as np
import pygame

SR = 22050
BPM = 112
BEAT = 60.0 / BPM
ASSETS = Path(__file__).parent / "assets"

_sounds = {}
_music_channels = []
_ready = False


def _env(length, attack=0.01, release=0.14):
    result = np.ones(length)
    a = min(length, int(SR * attack))
    r = min(length, int(SR * release))
    if a:
        result[:a] = np.linspace(0, 1, a)
    if r:
        result[-r:] *= np.linspace(1, 0, r)
    return result


def _tone(freq, duration, amp=0.5, triangle=False):
    length = max(1, int(SR * duration))
    t = np.arange(length) / SR
    phase = 2 * np.pi * freq * t
    signal = 2 / np.pi * np.arcsin(np.sin(phase)) if triangle else np.sin(phase)
    return signal * _env(length, release=min(duration * 0.55, 0.22)) * amp


def _sweep(start, end, duration, amp=0.55):
    length = max(1, int(SR * duration))
    frequencies = np.linspace(start, end, length)
    phase = 2 * np.pi * np.cumsum(frequencies) / SR
    return np.sin(phase) * _env(length, release=duration * 0.6) * amp


def _stereo(mono, pan=0.0):
    angle = (max(-1.0, min(1.0, pan)) + 1) * math.pi / 4
    return np.column_stack((mono * math.cos(angle), mono * math.sin(angle)))


def _mix(parts):
    length = max(len(part) for part in parts)
    result = np.zeros(length)
    for part in parts:
        result[:len(part)] += part
    return result


def _events():
    rng = np.random.default_rng(41)
    noise = rng.standard_normal(int(SR * 0.24))
    hit = noise * np.exp(-np.linspace(0, 9, len(noise))) * 0.32
    hit += _tone(74, 0.24, 0.65)
    shield = _mix((_sweep(900, 260, 0.42, 0.4), _tone(1240, 0.42, 0.26)))
    power = _mix((_sweep(280, 920, 0.5, 0.42), _tone(660, 0.5, 0.28)))
    start = np.concatenate((_tone(330, 0.12, 0.45), _tone(494, 0.12, 0.5),
                            _tone(740, 0.28, 0.62)))
    game_over = np.concatenate((_tone(330, 0.20, 0.42), _tone(247, 0.20, 0.42),
                                _tone(165, 0.48, 0.5)))
    result = {
        "move": _stereo(_sweep(520, 240, 0.16, 0.36)),
        "jump": _stereo(_sweep(260, 760, 0.28, 0.45)),
        "slide": _stereo(_sweep(310, 120, 0.25, 0.34)),
        "punch": _stereo(_sweep(180, 620, 0.13, 0.50)),
        "smash": _stereo(_mix((hit, _tone(520, 0.24, 0.24)))),
        "hit": _stereo(hit),
        "shield": _stereo(shield),
        "power": _stereo(power),
        "warning": _stereo(_tone(880, 0.10, 0.32, triangle=True)),
        "start": _stereo(start),
        "game_over": _stereo(game_over),
    }
    scale = (880, 988, 1109, 1319, 1480, 1760)
    for index, freq in enumerate(scale):
        result[f"coin{index}"] = _stereo(_tone(freq, 0.13, 0.34),
                                          -0.45 + index * 0.18)
    return result


def _add(buffer, start, duration, frequency, amp, pan=0.0, triangle=False):
    data = _stereo(_tone(frequency, duration, amp, triangle), pan)
    offset = int(start * SR)
    end = min(len(buffer), offset + len(data))
    if end > offset:
        buffer[offset:end] += data[:end - offset]


def _music():
    duration = 8 * BEAT
    length = int(duration * SR)
    ambient = np.zeros((length, 2))
    drive = np.zeros((length, 2))
    rush = np.zeros((length, 2))
    chords = ((110.0, 164.81, 220.0), (98.0, 146.83, 196.0),
              (82.41, 123.47, 164.81), (98.0, 146.83, 196.0))
    for chord_index, chord in enumerate(chords):
        start = chord_index * 2 * BEAT
        for frequency in chord:
            _add(ambient, start, 2 * BEAT, frequency, 0.085,
                 pan=-0.22 if chord_index % 2 == 0 else 0.22)

    rng = np.random.default_rng(73)
    bass = (55.0, 49.0, 41.20, 49.0)
    for index in range(8):
        start = index * BEAT
        _add(drive, start, BEAT * 0.68, bass[index // 2], 0.21, triangle=True)
        kick_len = int(SR * 0.17)
        t = np.arange(kick_len) / SR
        kick = np.sin(2 * np.pi * (92 - t * 250) * t) * np.exp(-21 * t) * 0.55
        offset = int(start * SR)
        drive[offset:offset + kick_len] += _stereo(kick)
        for half in (0.0, 0.5):
            offset = int((start + half * BEAT) * SR)
            hat_len = int(SR * 0.035)
            hat = rng.standard_normal(hat_len) * np.exp(-np.linspace(0, 7, hat_len)) * 0.055
            drive[offset:offset + hat_len] += _stereo(hat, 0.55 if half else -0.55)

    arp = (440.0, 659.25, 880.0, 987.77)
    for index in range(16):
        _add(rush, index * BEAT / 2, BEAT * 0.26, arp[index % 4], 0.12,
             pan=-0.68 if index % 2 == 0 else 0.68, triangle=True)
    return {"ambient": ambient, "drive": drive, "rush": rush}


def _write(path, data):
    peak = max(1.0, float(np.max(np.abs(data))))
    pcm = (np.clip(data / peak, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SR)
        wav.writeframes(pcm.tobytes())


def init():
    global _ready
    ASSETS.mkdir(exist_ok=True)
    generated = {**_events(), **_music()}
    for name, data in generated.items():
        path = ASSETS / f"{name}.wav"
        if not path.exists():
            _write(path, data)
        _sounds[name] = pygame.mixer.Sound(str(path))
    pygame.mixer.set_num_channels(12)
    _ready = True


def start_music():
    global _music_channels
    if not _ready:
        return
    stop_music(0)
    _music_channels = []
    for index, name in enumerate(("ambient", "drive", "rush")):
        channel = pygame.mixer.Channel(index)
        channel.play(_sounds[name], loops=-1)
        _music_channels.append(channel)
    update_music(0, False)


def update_music(combo, boosting):
    if len(_music_channels) != 3:
        return
    volumes = (0.30, 0.24 if combo >= 3 else 0.15,
               0.25 if boosting else (0.12 if combo >= 12 else 0.0))
    for channel, volume in zip(_music_channels, volumes):
        channel.set_volume(volume)


def stop_music(fade_ms=300):
    global _music_channels
    for channel in _music_channels:
        channel.fadeout(fade_ms)
    _music_channels = []


def play(name, pan=0.0, volume=0.72):
    if not _ready or name not in _sounds:
        return
    channel = pygame.mixer.find_channel(True)
    channel.play(_sounds[name])
    pan = max(-1.0, min(1.0, pan))
    channel.set_volume(volume * (1 - max(0.0, pan)),
                       volume * (1 + min(0.0, pan)))
