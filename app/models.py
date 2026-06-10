from datetime import datetime

from pydantic import BaseModel


class EventIn(BaseModel):
    event_type: str
    event_time: datetime
    source: str
    object_type: str | None = None
    checkpoint: str | None = None
    value: int
