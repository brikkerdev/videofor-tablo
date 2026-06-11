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
CHAR_W_RATIO = 0.85  # оценка ширины символа от кегля (с запасом)
TEXT_PAD = 10  # запас, чтобы прошивка не пускала текст по кругу


def render_text(indicators: list[Indicator], values: dict[str, int]) -> str:
    """Текстовое представление состояния. Используется для отладки и
    превью, на табло уходит через render_areas."""
    if not indicators:
        return ""
    width = max(len(ind.display_name) for ind in indicators) + 1
    return "\n".join(
        f"{(ind.display_name + ':').ljust(width)} {values.get(ind.key, 0)}"
        for ind in indicators
    )


def _fit_font(size: int, area_h: int) -> int:
    """Не дать кеглю вылезти за высоту области."""
    return max(MIN_FONT, min(size, area_h - 2))


def _text_w(msg: str, fontsize: int) -> int:
    return int(len(msg) * fontsize * CHAR_W_RATIO) + TEXT_PAD


def _align_zone(slot_x: int, slot_w: int, msg: str, fontsize: int, align: str):
    """Координаты зоны внутри слота под нужное выравнивание.

    Матрица центрирует текст в зоне, поэтому выравнивание задаём
    геометрией: для left/right сужаем зону под оценочную ширину текста
    и прижимаем к краю слота. center — зона во весь слот.
    """
    if align == "center":
        return slot_x, slot_w
    tw = min(slot_w, _text_w(msg, fontsize))
    if align == "right":
        return slot_x + slot_w - tw, tw
    return slot_x, tw  # left


def _alert(th, val: int) -> bool:
    """Сработал ли порог для значения."""
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


def _line_areas(ind, val, ln, slot_x, col_w, board, fs, y, line_h) -> list[dict]:
    """Две раздельные зоны строки: метка и число. Раздельные всегда —
    чтобы их можно было красить независимо. Порог красит число
    (target=value) или обе зоны (target=line)."""
    th = ln.threshold
    alert = _alert(th, val)
    label = f"{ind.display_name}:"
    value = str(val)

    lw = _text_w(label, fs)
    vw = _text_w(value, fs)
    gap = max(4, int(fs * 0.3))
    # не вылезать за слот: при нехватке места ужимаем метку
    if lw + gap + vw > col_w:
        vw = min(vw, col_w)
        lw = max(0, col_w - gap - vw)
    total = lw + gap + vw
    if board.align == "center":
        bx = slot_x + (col_w - total) // 2
    elif board.align == "right":
        bx = slot_x + col_w - total
    else:
        bx = slot_x
    bx = min(max(slot_x, bx), slot_x + col_w - total)

    label_color = value_color = _with_brightness(ln.color, ln.brightness)
    if alert and th is not None:
        value_color = _with_brightness(th.color, ln.brightness)
        if th.target == "line":
            label_color = value_color

    return [
        _area(label, bx, y, lw, line_h, board.fontname, fs, label_color, board.stunt),
        _area(value, bx + lw + gap, y, vw, line_h, board.fontname, fs, value_color, board.stunt),
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
    """Собрать список областей для POST /message.json.

    Раскладка: опциональная верхняя плашка во всю ширину, ниже —
    включённые показатели в board.columns столбцов. Выравнивание — через
    геометрию зоны, пороги — сменой цвета строки или числа.
    id областей назначаются подряд от "0": клиент гасит хвостовые id
    при уменьшении их числа (см. TabloClient).
    """
    areas: list[dict] = []

    top_h = board.top_panel.height if board.top_panel.enabled else 0
    if board.top_panel.enabled:
        msg = _top_text(board.top_panel, now, online)
        fs = _fit_font(board.top_panel.fontsize, top_h)
        zx, zw = _align_zone(0, width, msg, fs, board.top_panel.align)
        top_color = _with_brightness(board.top_panel.color, board.top_panel.brightness)
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
        # единый кегль: по высоте строки, затем ужимаем под ширину столбца
        # по самой длинной строке, чтобы прошивка не гоняла текст по кругу
        fs = _fit_font(board.fontsize, line_h)
        longest = max(
            (f"{ind.display_name}: {values.get(ind.key, 0)}" for ind in visible),
            key=len, default="",
        )
        while fs > MIN_FONT and _text_w(longest, fs) > col_w:
            fs -= 1
        for i, ind in enumerate(visible):
            r, c = divmod(i, cols)
            ln = board.line(ind.key)
            val = values.get(ind.key, 0)
            areas.extend(
                _line_areas(ind, val, ln, c * col_w, col_w, board, fs,
                            top_h + r * line_h, line_h)
            )

    # Идентификаторы подряд, значения строками — как у штатного интерфейса
    out: list[dict] = []
    for idx, a in enumerate(areas):
        out.append({"id": str(idx), **{k: str(v) for k, v in a.items()}})
    return out
