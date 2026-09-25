"""Run the Discord delivery API with environment-only configuration."""

import os
import stat
import threading
import logging
from datetime import datetime, timezone

import uvicorn

from discord_delivery.api import create_app
from discord_delivery.config import Config
from discord_delivery.discord_gateway import DiscordGateway
from discord_delivery.store import DeliveryStore
from discord_delivery.worker import DeliveryWorker


def _read_bot_token(config: Config) -> str:
    fd = os.open(config.bot_token_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        mode = os.fstat(fd).st_mode
        if not stat.S_ISREG(mode) or mode & 0o077:
            raise ValueError("bot token file must be private")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            return stream.read(4096).strip()
    finally:
        if fd >= 0:
            os.close(fd)


def main() -> None:
    config = Config.from_environment()
    store = DeliveryStore(config.state_path, config.media_path)
    gateway = DiscordGateway(_read_bot_token(config))
    worker = DeliveryWorker(store, gateway)
    app = create_app(config, store, query_executor=gateway.query)
    stop = threading.Event()

    def deliver() -> None:
        while not stop.is_set():
            try:
                worker.run_once(datetime.now(timezone.utc))
            except Exception:
                # The worker keeps its durable claim; the next pass recovers it.
                logging.error("discord delivery worker iteration failed")
            stop.wait(1)

    thread = threading.Thread(target=deliver, name="discord-delivery-worker", daemon=True)
    thread.start()
    try:
        uvicorn.run(app, host=config.host, port=config.port, workers=1)
    finally:
        stop.set()
        thread.join(timeout=20)


if __name__ == "__main__":
    main()
