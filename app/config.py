from datetime import datetime
from functools import cached_property
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://app:app@db:5432/tablo"
    app_timezone: str = ""
    api_key: str = ""

    tablo_url: str = ""
    tablo_token: str = ""

    tablo_matrix_ip: str = ""
    tablo_matrix_pass: str = "guest"

    push_retry_seconds: int = 10
    log_level: str = "INFO"

    @cached_property
    def tz(self):
        if self.app_timezone:
            return ZoneInfo(self.app_timezone)
        return datetime.now().astimezone().tzinfo


settings = Settings()
