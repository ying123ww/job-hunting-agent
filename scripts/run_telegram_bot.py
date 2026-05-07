from __future__ import annotations

import logging

from interview_agent.app.config import get_settings
from interview_agent.core.container import AppContainer
from interview_agent.telegram_bot import TelegramBotClient, TelegramBotService


logging.basicConfig(level=logging.INFO)


def main() -> None:
    settings = get_settings()
    container = AppContainer.build(settings)
    client = TelegramBotClient(settings)
    service = TelegramBotService(
        container=container,
        client=client,
        settings=settings,
    )
    service.run()


if __name__ == "__main__":
    main()
