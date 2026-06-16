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

TEXT_PAD = 4

# Ширина текста области (доля кегля на символ). Панель центрирует текст внутри
# области, а её шрифт заметно шире экранного Arial из предпросмотра — поэтому
# берём с запасом, чтобы текст гарантированно влезал и панель не включала
# прокрутку. Предпросмотр (drawCanvas) прижимает текст к краю области, поэтому
# выглядит так же, как на панели.
WIDTH_RATIO = 0.75


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
    return int(len(msg) * fontsize * WIDTH_RATIO) + TEXT_PAD


def _align_zone(slot_x: int, slot_w: int, msg: str, fontsize: int, pad: int, align: str):
    # Рамка по ширине текста, прижата к нужному краю (с отступом pad от края).
    tw = min(max(1, slot_w - 2 * pad), _text_w(msg, fontsize))
    if align == "center":
        return slot_x + (slot_w - tw) // 2, tw
    if align == "right":
        return slot_x + slot_w - pad - tw, tw
    return slot_x + pad, tw


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


def _area(msg, x, y, w, h, fontname, fontsize, color, stunt, align="left") -> dict:
    return {
        "msg": msg, "x": x, "y": y, "w": w, "h": h,
        "fontname": fontname, "fontsize": fontsize, "fontcolor": color, "stunt": stunt,
        # Подсказка предпросмотру, к какому краю области прижимать текст
        # (панель центрирует сама; на устройство не уходит — см. app/tablo.py).
        "align": align,
    }


def _effective_brightness(base: int, item: int) -> int:
    return min(255, int(base * item / 255))


def _line_areas(ind, val, ln, slot_x, col_w, board, fs, y, line_h,
                base_brightness: int = 255, threshold_since=None, now=None) -> list[dict]:
    th = ln.threshold
    label = f"{ind.display_name}:"
    value = str(val)

    eff = _effective_brightness(base_brightness, ln.brightness)
    label_color = value_color = _with_brightness(ln.color, eff)

    if th is not None:
        since = (threshold_since or {}).get(ind.key)
        if since is not None:
            value_color = _with_brightness(th.color, eff)
            if th.target == "line":
                label_color = value_color

    # Метка прижата к левому краю колонки, значение — к правому, оба с отступом
    # board.padding от краёв экрана. Рамки — по ширине текста (с запасом), чтобы
    # текст влезал; панель центрирует текст в рамке, предпросмотр — прижимает.
    pad = board.padding
    gap = max(2, fs // 4)
    vw = min(_text_w(value, fs), col_w - 2 * pad)
    vx = slot_x + col_w - pad - vw

    space = max(1, vx - gap - slot_x - pad)
    lw = min(_text_w(label, fs), space)
    lx = slot_x + pad

    return [
        _area(label, lx, y, lw, line_h, board.fontname, fs, label_color, board.stunt, "left"),
        _area(value, vx, y, vw, line_h, board.fontname, fs, value_color, board.stunt, "right"),
    ]


def render_areas(
    indicators: list[Indicator],
    values: dict[str, int],
    board: BoardConfig,
    now: datetime,
    online: bool,
    width: int = BOARD_W,
    height: int = BOARD_H,
    threshold_since: dict | None = None,
) -> list[dict]:
    areas: list[dict] = []

    top_h = board.top_panel.height if board.top_panel.enabled else 0
    if board.top_panel.enabled:
        msg = _top_text(board.top_panel, now, online)
        fs = _fit_font(board.top_panel.fontsize, top_h)
        zx, zw = _align_zone(0, width, msg, fs, board.padding, board.top_panel.align)
        top_eff = _effective_brightness(board.screen_brightness, board.top_panel.brightness)
        top_color = _with_brightness(board.top_panel.color, top_eff)
        areas.append(
            _area(msg, zx, 0, zw, top_h, board.top_panel.fontname, fs,
                  top_color, board.top_panel.stunt, board.top_panel.align)
        )

    # Порядок вывода задаётся порядком board.lines (drag&drop в редакторе);
    # показатели без строки в конфиге добавляются в конце по sort_order из БД.
    ind_by_key = {ind.key: ind for ind in indicators}
    ordered_keys = [ln.key for ln in board.lines if ln.key in ind_by_key]
    seen = set(ordered_keys)
    ordered_keys += [ind.key for ind in indicators if ind.key not in seen]
    visible = [ind_by_key[k] for k in ordered_keys if board.line(k).enabled]
    region_h = height - top_h
    n = len(visible)
    if n:
        cols = max(1, min(2, board.columns))
        rows = math.ceil(n / cols)
        line_h = region_h // rows
        col_w = width // cols
        fs = _fit_font(board.fontsize, line_h)

        def _widest_line(size: int) -> int:
            g = max(2, size // 4)
            return 2 * board.padding + max(
                _text_w(f"{ind.display_name}:", size) + g + _text_w(str(values.get(ind.key, 0)), size)
                for ind in visible
            )

        # Уменьшаем кегль, пока самая длинная строка «метка+значение» не влезет
        # в колонку — иначе панель не уместит текст и включит прокрутку.
        while fs > MIN_FONT and _widest_line(fs) > col_w:
            fs -= 1
        for i, ind in enumerate(visible):
            r, c = divmod(i, cols)
            ln = board.line(ind.key)
            val = values.get(ind.key, 0)
            areas.extend(
                _line_areas(ind, val, ln, c * col_w, col_w, board, fs,
                            top_h + r * line_h, line_h,
                            base_brightness=board.screen_brightness,
                            threshold_since=threshold_since,
                            now=now)
            )

    out: list[dict] = []
    for idx, a in enumerate(areas):
        out.append({"id": str(idx), **{k: str(v) for k, v in a.items()}})
    return out
