from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from interview_agent.app.config import get_settings
from interview_agent.core.container import AppContainer
from interview_agent.qq_bot import QQBotClient, QQBotService


logging.basicConfig(level=logging.INFO)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the QQ bot against a target workspace.")
    parser.add_argument("--workspace", type=Path, default=None, help="Override INTERVIEW_AGENT_WORKSPACE_DIR.")
    args = parser.parse_args()

    if args.workspace is not None:
        os.environ["INTERVIEW_AGENT_WORKSPACE_DIR"] = str(args.workspace)

    get_settings.cache_clear()
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
