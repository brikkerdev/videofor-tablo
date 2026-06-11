import asyncio
import logging
import os
import random
from datetime import datetime

import httpx

logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
logger = logging.getLogger("videofor-sim")

APP_URL = os.environ.get("APP_URL", "http://app:8000/api/events")
API_KEY = os.environ.get("API_KEY", "")
MIN_DELAY = float(os.environ.get("SIM_MIN_DELAY", "2"))
MAX_DELAY = float(os.environ.get("SIM_MAX_DELAY", "8"))

EVENTS = [
    ("violation", "transport", None, 4),
    ("student_in", "student", None, 3),
    ("student_out", "student", None, 2),
    ("instructor_in", "instructor", None, 1),
    ("instructor_out", "instructor", None, 1),
]


def make_event() -> dict:
    event_type, object_type, checkpoint, _ = random.choices(
        EVENTS, weights=[e[3] for e in EVENTS]
    )[0]
    return {
        "event_type": event_type,
        "event_time": datetime.now().isoformat(timespec="seconds"),
        "source": "Videofor",
        "object_type": object_type,
        "checkpoint": checkpoint,
        "value": 1,
    }


async def main() -> None:
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            event = make_event()
            try:
                resp = await client.post(APP_URL, json=event, headers=headers)
                logger.info(
                    "%s -> %s %s", event["event_type"], resp.status_code, resp.text
                )
            except Exception as exc:
                logger.warning("Отправка не удалась: %s", exc)
            await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


if __name__ == "__main__":
    asyncio.run(main())
