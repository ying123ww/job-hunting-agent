from __future__ import annotations

import logging

from interview_agent.app.config import get_settings
from interview_agent.core.container import AppContainer
from interview_agent.qq_bot import QQBotClient, QQBotService


logging.basicConfig(level=logging.INFO)


def main() -> None:
    settings = get_settings()
    container = AppContainer.build(settings)
    client = QQBotClient(settings)
    service = QQBotService(
        container=container,
        client=client,
        settings=settings,
    )
    service.run()


if __name__ == "__main__":
    main()
