"""《星核指挥家》的确定性节奏谱面。"""

from dataclasses import dataclass

BPM = 104
BEAT = 60.0 / BPM
APPROACH_TIME = 1.75
HIT_WINDOW = 0.30

LEFT = "left"
RIGHT = "right"
CHORD = "chord"
SQUAT = "squat"
STAR = "star"
KINDS = (LEFT, RIGHT, CHORD, SQUAT, STAR)


@dataclass
class Note:
    beat: float
    kind: str
    lane: int = 1
    resolved: bool = False
    result: str | None = None

    @property
    def due(self):
        return self.beat * BEAT


def build_chart():
    """生成约两分钟的单曲谱面，前缓后急并穿插全身动作。"""
    chart = []
    lanes = (0, 1, 2, 1)

    # 教学段：左右手交替，每两拍一次。
    for i, beat in enumerate(range(4, 36, 2)):
        chart.append(Note(float(beat), LEFT if i % 2 == 0 else RIGHT,
                          lanes[i % len(lanes)]))

    # 展开段：加入双手和星座定格。
    for i, beat in enumerate(range(36, 92, 2)):
        if beat % 16 == 12:
            kind = STAR
        elif beat % 8 == 4:
            kind = CHORD
        else:
            kind = LEFT if i % 2 == 0 else RIGHT
        chart.append(Note(float(beat), kind, lanes[(i + 1) % len(lanes)]))

    # 风暴段：加入下蹲，密度逐渐提高。
    for i, beat in enumerate(range(92, 148, 2)):
        if beat % 16 == 12:
            kind = SQUAT
        elif beat % 8 == 4:
            kind = CHORD
        else:
            kind = RIGHT if i % 2 == 0 else LEFT
        chart.append(Note(float(beat), kind, lanes[(i + 2) % len(lanes)]))

    # 终章：每拍一个动作，但四拍末用全身动作留出换气空间。
    for i, beat in enumerate(range(148, 196)):
        if beat % 16 == 15:
            kind = STAR
        elif beat % 16 == 11:
            kind = SQUAT
        elif beat % 8 == 3:
            kind = CHORD
        else:
            kind = LEFT if i % 2 == 0 else RIGHT
        chart.append(Note(float(beat), kind, lanes[i % len(lanes)]))

    return sorted(chart, key=lambda note: note.beat)


def song_duration(chart=None):
    chart = chart or build_chart()
    return chart[-1].due + 3.0
