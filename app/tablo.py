import asyncio
import json
import logging

import httpx

logger = logging.getLogger("app.tablo")

BATCH_SIZE = 4
INTER_BATCH_DELAY = 0.4

# Поля, которые понимает шлюз. Лишние ключи (например подсказка `align`
# для предпросмотра) в message.json не отправляем.
_DEVICE_KEYS = ("id", "msg", "x", "y", "w", "h", "fontname", "fontsize", "fontcolor", "stunt")


def _device_area(area: dict) -> dict:
    return {k: area[k] for k in _DEVICE_KEYS if k in area}


def _clear_area(area_id: str) -> dict:
    return {
        "id": area_id,
        "msg": "",
        "x": "0",
        "y": "0",
        "w": "1",
        "h": "1",
        "fontname": "Arial",
        "fontsize": "12",
        "fontcolor": "0xffffffff",
        "stunt": "0",
    }


class TabloClient:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        matrix_ip: str = "",
        matrix_pass: str = "guest",
        timeout: float = 5.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.matrix_ip = matrix_ip
        self.matrix_pass = matrix_pass
        self._stream_client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=5.0))
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        )
        self._req_lock = asyncio.Lock()
        self._last_max: int | None = None
        self._warned_no_url = False
        self._sse_task: asyncio.Task | None = None
        self._stop = False
        self.device: dict | None = None
        self.connected = False

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path}"

    def start(self) -> None:
        if self.base_url and self._sse_task is None:
            self._stop = False
            self._sse_task = asyncio.create_task(self._sse_keeper())

    async def _sse_keeper(self) -> None:
        url = self._url("sse.json")
        while not self._stop:
            try:
                async with self._stream_client.stream("GET", url) as resp:
                    await asyncio.sleep(2)
                    # Источник правды о связи — GET /connect.json: SSE может молчать,
                    # а уже подключённый шлюз отдаёт connected/размеры сразу.
                    await self.refresh_status()
                    # matrix IP нужен только чтобы поднять связь, если её нет.
                    if not self.connected and self.matrix_ip:
                        await self._post_connect(self.matrix_ip, self.matrix_pass)
                        await asyncio.sleep(1)
                        await self.refresh_status()
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            self._consume(line[5:].strip())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("SSE к табло прервался: %s", exc)
            self.connected = False
            if not self._stop:
                await asyncio.sleep(3)

    def _consume(self, data: str) -> None:
        try:
            obj = json.loads(data)
        except Exception:
            return
        if obj.get("login") is False:
            self.connected = False
        dev = obj.get("device")
        if isinstance(dev, dict):
            self.device = {**(self.device or {}), **dev}
            self.connected = True
        fonts = obj.get("fonts")
        if isinstance(fonts, list):
            self.device = {**(self.device or {}), "fontlist": fonts}

    async def _stop_sse(self) -> None:
        self._stop = True
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except (asyncio.CancelledError, Exception):
                pass
            self._sse_task = None
        self.connected = False

    async def _post_connect(self, matrix_ip: str, matrix_pass: str) -> None:
        try:
            async with self._req_lock:
                resp = await self._client.post(
                    self._url("connect.json"),
                    json={"bx-ip": matrix_ip, "bx-pass": matrix_pass},
                )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("connect.json не удался: %s", exc)

    async def get_device(self) -> dict | None:
        """Состояние шлюза: GET /connect.json (connected, ip матрицы, размеры)."""
        if not self.base_url:
            return None
        try:
            async with self._req_lock:
                resp = await self._client.get(self._url("connect.json"))
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Не удалось прочитать connect.json: %s", exc)
            return None

    async def refresh_status(self) -> bool:
        """Перечитать состояние шлюза и обновить connected/device по факту.

        Уже подключённый к матрице шлюз отдаёт connected:true и размеры панели,
        даже если SSE-событие device не пришло. При сетевой ошибке прежнее
        состояние сохраняется.
        """
        info = await self.get_device()
        if info is None:
            return self.connected
        self.device = {**(self.device or {}), **info}
        self.connected = bool(info.get("connected"))
        return self.connected

    async def reconnect(self) -> bool:
        await self._stop_sse()
        self.start()
        for _ in range(16):
            if self.connected:
                return True
            await asyncio.sleep(0.5)
        return self.connected

    async def push_areas(self, areas: list[dict]) -> None:
        if not self.base_url:
            if not self._warned_no_url:
                logger.warning("TABLO_URL не задан, push пропускается")
                self._warned_no_url = True
            return
        if not self.connected:
            # SSE мог не прислать device — спросим состояние напрямую.
            await self.refresh_status()
        if not self.connected:
            raise RuntimeError("табло не подключено, push отложен")

        payload = [_device_area(a) for a in areas]
        count = len(areas)
        if self._last_max is not None:
            payload.extend(_clear_area(str(i)) for i in range(count, self._last_max + 1))

        if not payload:
            return

        for j in range(0, len(payload), BATCH_SIZE):
            chunk = payload[j : j + BATCH_SIZE]
            async with self._req_lock:
                resp = await self._client.post(self._url("message.json"), json=chunk)
            resp.raise_for_status()
            if j + BATCH_SIZE < len(payload):
                await asyncio.sleep(INTER_BATCH_DELAY)
        self._last_max = count - 1 if count else None

    async def set_brightness(self, value: int) -> bool:
        if not self.base_url:
            return False
        try:
            async with self._req_lock:
                resp = await self._client.post(
                    self._url("brightness.json"),
                    json={"brightness": value},
                )
            resp.raise_for_status()
            if self.device is not None:
                self.device["brightness"] = value
            return True
        except Exception as exc:
            logger.warning("set_brightness failed: %s", exc)
            return False

    async def close(self) -> None:
        await self._stop_sse()
        await self._client.aclose()
        await self._stream_client.aclose()
