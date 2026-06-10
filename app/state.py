from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Indicator:
    key: str
    display_name: str
    kind: str
    sort_order: int


class StateCache:
    """Текущее состояние показателей в памяти процесса.

    Источник правды для чтения: GET /api/state и push на табло
    в БД не ходят. БД получает только записи при событиях.
    """

    def __init__(self, tz):
        self.tz = tz
        self.day: date | None = None
        self.indicators: list[Indicator] = []
        self.values: dict[str, int] = {}
        self.updated_at: datetime | None = None
        self.last_event_at: datetime | None = None

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def is_online(self, window_seconds: int) -> bool:
        """Считаем источник онлайн, если событие приходило недавно."""
        if not self.last_event_at:
            return False
        return (self.now() - self.last_event_at).total_seconds() <= window_seconds

    def today(self) -> date:
        return self.now().date()

    def load(
        self,
        indicators: list[Indicator],
        today_values: dict[str, int],
        prev_values: dict[str, int],
        day: date,
    ) -> None:
        self.indicators = sorted(indicators, key=lambda i: i.sort_order)
        self.day = day
        self.values = {}
        for ind in self.indicators:
            if ind.key in today_values:
                self.values[ind.key] = today_values[ind.key]
            elif ind.kind == "gauge":
                self.values[ind.key] = prev_values.get(ind.key, 0)
            else:
                self.values[ind.key] = 0

    def rollover_if_needed(self) -> bool:
        """Смена календарного дня: daily в ноль, gauge переносится."""
        today = self.today()
        if self.day == today:
            return False
        self.values = {
            ind.key: self.values.get(ind.key, 0) if ind.kind == "gauge" else 0
            for ind in self.indicators
        }
        self.day = today
        return True

    def snapshot(self) -> dict:
        return {
            "date": self.day.isoformat() if self.day else None,
            "updated_at": (
                self.updated_at.isoformat(timespec="seconds")
                if self.updated_at
                else None
            ),
            "indicators": [
                {
                    "key": ind.key,
                    "display_name": ind.display_name,
                    "value": self.values.get(ind.key, 0),
                }
                for ind in self.indicators
            ],
        }
