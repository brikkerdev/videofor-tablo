from datetime import datetime

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    event_type: str
    event_time: datetime
    source: str
    object_type: str | None = None
    checkpoint: str | None = None
    value: int


# --- Конфигурация вывода на табло ---------------------------------------
#
# Что и как показывать на панели 256x96: верхняя панель (часы, онлайн,
# произвольный текст) и строки показателей. Хранится в таблице config
# под ключом display_config, редактируется через /api/display/config.


class TopPanel(BaseModel):
    """Верхняя строка-плашка: онлайн, дата-время, произвольный текст."""

    enabled: bool = True
    show_clock: bool = True
    show_online: bool = True
    text: str = ""
    datetime_format: str = "%d.%m %H:%M"
    online_text: str = "ON"
    offline_text: str = "OFF"
    align: str = "left"  # left | center | right
    color: str = "0xff00ffff"
    fontname: str = "Arial"
    fontsize: int = 14
    height: int = 16
    stunt: int = 0
    brightness: int = Field(default=255, ge=0, le=255)


class Threshold(BaseModel):
    """Порог по значению показателя. При срабатывании условия меняется
    цвет: всей строки (target=line) или только числа (target=value)."""

    value: int
    op: str = ">="  # >= | > | <= | < | ==
    color: str = "0xffff0000"
    target: str = "line"  # line | value


class LineConfig(BaseModel):
    """Переопределение вывода одного показателя. Порядок строк берётся
    из sort_order показателя, здесь видимость, цвет и порог."""

    key: str
    enabled: bool = True
    color: str = "0xffffffff"
    brightness: int = Field(default=255, ge=0, le=255)
    threshold: Threshold | None = None


class BoardConfig(BaseModel):
    top_panel: TopPanel = Field(default_factory=TopPanel)
    lines: list[LineConfig] = Field(default_factory=list)
    columns: int = 1  # 1 или 2 столбца показателей
    align: str = "left"  # выравнивание строк: left | center | right
    fontname: str = "Arial"
    fontsize: int = 16
    stunt: int = 0
    online_window_seconds: int = 120
    screen_brightness: int = Field(default=255, ge=0, le=255)

    def line(self, key: str) -> LineConfig:
        for ln in self.lines:
            if ln.key == key:
                return ln
        return LineConfig(key=key)
