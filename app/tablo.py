import logging

import httpx

logger = logging.getLogger("app.tablo")


class TabloClient:
    """Клиент API табло. Формат API уточняется, контракт изолирован здесь."""

    def __init__(self, url: str, token: str = "", timeout: float = 5.0):
        self.url = url
        self.token = token
        self._client = httpx.AsyncClient(timeout=timeout)
        self._warned_no_url = False

    async def push(self, text: str, state: dict) -> None:
        if not self.url:
            if not self._warned_no_url:
                logger.warning("TABLO_URL не задан, push пропускается")
                self._warned_no_url = True
            return
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        resp = await self._client.post(
            self.url, json={"text": text, "state": state}, headers=headers
        )
        resp.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()
