from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    event_type: str
    event_time: datetime
    source: str
    object_type: str | None = None
    checkpoint: str | None = None
    value: int


class TopPanel(BaseModel):
    enabled: bool = True
    show_clock: bool = True
    show_online: bool = True
    text: str = ""
    datetime_format: str = "%d.%m %H:%M"
    online_text: str = "ON"
    offline_text: str = "OFF"
    align: str = "left"
    color: str = "0xff00ffff"
    fontname: str = "Arial"
    fontsize: int = 14
    height: int = 16
    stunt: int = 0
    brightness: int = Field(default=255, ge=0, le=255)


class Threshold(BaseModel):
    value: int
    op: str = ">="
    color: str = "0xffff0000"
    target: str = "line"


class LineConfig(BaseModel):
    key: str
    enabled: bool = True
    color: str = "0xffffffff"
    brightness: int = Field(default=255, ge=0, le=255)
    smooth: bool = False
    threshold: Threshold | None = None


class BoardConfig(BaseModel):
    top_panel: TopPanel = Field(default_factory=TopPanel)
    lines: list[LineConfig] = Field(default_factory=list)
    columns: int = 1
    align: str = "left"
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


class RuleIn(BaseModel):
    event_type: str
    checkpoint: str | None = None
    indicator_key: str | None = None  # для создания показателя подставляется сервером
    op: Literal["inc", "dec", "set"] = "inc"


class IndicatorIn(BaseModel):
    key: str | None = None  # по умолчанию — slug из event_type/display_name
    display_name: str
    kind: Literal["daily", "gauge"] = "daily"
    sort_order: int | None = None
    rule: RuleIn | None = None


class IndicatorPatch(BaseModel):
    display_name: str | None = None
    kind: Literal["daily", "gauge"] | None = None
    sort_order: int | None = None
    enabled: bool | None = None
