import math
import re
from datetime import datetime

from .models import BoardConfig
from .state import Indicator

BOARD_W = 256
BOARD_H = 96

MIN_FONT = 6


def _with_brightness(color: str, brightness: int) -> str:
    if brightness >= 255:
        return color
    m = re.match(r'^0x[0-9a-fA-F]{2}([0-9a-fA-F]{6})$', color or '', re.IGNORECASE)
    return f'0x{brightness:02x}{m.group(1)}' if m else color

CHAR_W_RATIO = 0.75
TEXT_PAD = 4
LABEL_RATIO = 0.72


def render_text(indicators: list[Indicator], values: dict[str, int]) -> str:
    if not indicators:
        return ""
    width = max(len(ind.display_name) for ind in indicators) + 1
    return "\n".join(
        f"{(ind.display_name + ':').ljust(width)} {values.get(ind.key, 0)}"
        for ind in indicators
    )


def _fit_font(size: int, area_h: int) -> int:
    return max(MIN_FONT, min(size, area_h - 2))


def _text_w(msg: str, fontsize: int) -> int:
    return int(len(msg) * fontsize * CHAR_W_RATIO) + TEXT_PAD


def _align_zone(slot_x: int, slot_w: int, msg: str, fontsize: int, align: str):
    if align == "center":
        return slot_x, slot_w
    tw = min(slot_w, _text_w(msg, fontsize))
    if align == "right":
        return slot_x + slot_w - tw, tw
    return slot_x, tw


def _alert(th, val: int) -> bool:
    if th is None:
        return False
    t = th.value
    return {
        ">=": val >= t,
        ">": val > t,
        "<=": val <= t,
        "<": val < t,
        "==": val == t,
    }.get(th.op, False)


def _top_text(panel, now: datetime, online: bool) -> str:
    parts: list[str] = []
    if panel.show_clock:
        parts.append(now.strftime(panel.datetime_format))
    if panel.text:
        parts.append(panel.text)
    if panel.show_online:
        parts.append(panel.online_text if online else panel.offline_text)
    return "   ".join(parts)


def _area(msg, x, y, w, h, fontname, fontsize, color, stunt) -> dict:
    return {
        "msg": msg, "x": x, "y": y, "w": w, "h": h,
        "fontname": fontname, "fontsize": fontsize, "fontcolor": color, "stunt": stunt,
    }


def _effective_brightness(base: int, item: int) -> int:
    return min(255, int(base * item / 255))


def _lerp(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _parse_rgb(color: str) -> tuple:
    m = re.match(r'^0x[0-9a-fA-F]{2}([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$', color or '')
    if m:
        return int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16)
    return (255, 255, 255)


def _gradient_color(value: int, threshold_val: int, op: str, eff_brightness: int, base_color: str = "0xffffffff") -> str:
    GOOD   = _parse_rgb(base_color)
    YELLOW = (255, 200,   0)
    ORANGE = (255, 100,   0)
    RED    = (255,   0,   0)

    t = max(1, threshold_val)
    pct = max(0.0, value / t)

    above_is_bad = op in (">=", ">")

    if above_is_bad:
        kp = [(0.0, GOOD), (0.25, GOOD), (0.5, YELLOW), (0.75, ORANGE), (1.0, RED)]
    else:
        kp = [(0.0, RED), (0.25, ORANGE), (0.5, YELLOW), (0.75, GOOD), (1.0, GOOD)]

    pct = min(pct, kp[-1][0])

    r, g, b = kp[-1][1]
    for i in range(len(kp) - 1):
        p0, c0 = kp[i]
        p1, c1 = kp[i + 1]
        if pct <= p1:
            f = (pct - p0) / (p1 - p0) if p1 > p0 else 1.0
            r, g, b = _lerp(c0, c1, f)
            break

    return f'0x{eff_brightness:02x}{r:02x}{g:02x}{b:02x}'


def _line_areas(ind, val, ln, slot_x, col_w, board, fs, y, line_h, base_brightness: int = 255) -> list[dict]:
    th = ln.threshold
    label = f"{ind.display_name}:"
    value = str(val)

    lw = int(col_w * LABEL_RATIO)
    vw = col_w - lw

    eff = _effective_brightness(base_brightness, ln.brightness)
    if ln.smooth and th is not None:
        label_color = value_color = _gradient_color(val, th.value, th.op, eff, ln.color)
    else:
        label_color = value_color = _with_brightness(ln.color, eff)
        if _alert(th, val) and th is not None:
            value_color = _with_brightness(th.color, eff)
            if th.target == "line":
                label_color = value_color

    return [
        _area(label, slot_x,        y, lw, line_h, board.fontname, fs, label_color, board.stunt),
        _area(value, slot_x + lw,   y, vw, line_h, board.fontname, fs, value_color, board.stunt),
    ]


def render_areas(
    indicators: list[Indicator],
    values: dict[str, int],
    board: BoardConfig,
    now: datetime,
    online: bool,
    width: int = BOARD_W,
    height: int = BOARD_H,
) -> list[dict]:
    areas: list[dict] = []

    top_h = board.top_panel.height if board.top_panel.enabled else 0
    if board.top_panel.enabled:
        msg = _top_text(board.top_panel, now, online)
        fs = _fit_font(board.top_panel.fontsize, top_h)
        zx, zw = _align_zone(0, width, msg, fs, board.top_panel.align)
        top_eff = _effective_brightness(board.screen_brightness, board.top_panel.brightness)
        top_color = _with_brightness(board.top_panel.color, top_eff)
        areas.append(
            _area(msg, zx, 0, zw, top_h, board.top_panel.fontname, fs,
                  top_color, board.top_panel.stunt)
        )

    visible = [ind for ind in indicators if board.line(ind.key).enabled]
    region_h = height - top_h
    n = len(visible)
    if n:
        cols = max(1, min(2, board.columns))
        rows = math.ceil(n / cols)
        line_h = region_h // rows
        col_w = width // cols
        fs = _fit_font(board.fontsize, line_h)
        label_zone_w = int(col_w * LABEL_RATIO)
        longest_label = max(
            (f"{ind.display_name}:" for ind in visible),
            key=len, default="",
        )
        while fs > MIN_FONT and _text_w(longest_label, fs) > label_zone_w:
            fs -= 1
        for i, ind in enumerate(visible):
            r, c = divmod(i, cols)
            ln = board.line(ind.key)
            val = values.get(ind.key, 0)
            areas.extend(
                _line_areas(ind, val, ln, c * col_w, col_w, board, fs,
                            top_h + r * line_h, line_h,
                            base_brightness=board.screen_brightness)
            )

    out: list[dict] = []
    for idx, a in enumerate(areas):
        out.append({"id": str(idx), **{k: str(v) for k, v in a.items()}})
    return out
