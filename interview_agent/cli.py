from __future__ import annotations

import argparse
import logging
import os
import shutil
from datetime import date, datetime, time
from pathlib import Path
from typing import Sequence

import uvicorn

from interview_agent.app.config import AppSettings, get_settings
from interview_agent.app.workspace_init import InitSummary, init_workspace
from interview_agent.core.container import AppContainer
from interview_agent.qq_bot import QQBotClient, QQBotService
from interview_agent.telegram_bot import TelegramBotClient, TelegramBotService


logging.basicConfig(level=logging.INFO)


def _apply_workspace(workspace: Path | None) -> None:
    if workspace is not None:
        os.environ["INTERVIEW_AGENT_WORKSPACE_DIR"] = str(workspace)
    get_settings.cache_clear()


def _print_group(title: str, paths: list[Path]) -> None:
    if not paths:
        return
    print(title)
    for path in paths:
        print(f"  {path}")


def _print_init_summary(summary: InitSummary) -> None:
    _print_group("Created:", summary.created)
    _print_group("Overwritten:", summary.overwritten)
    _print_group("Skipped:", summary.skipped)
    if summary.notes:
        print("Notes:")
        for note in summary.notes:
            print(f"  {note}")
    if summary.next_steps:
        print("Next steps:")
        for step in summary.next_steps:
            print(f"  {step}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interview Copilot Agent unified CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a workspace with runtime files and local storage.")
    init_parser.add_argument("--workspace", type=Path, default=None)
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite workspace template files only. Does not clear app.db or chroma data.",
    )

    reset_parser = subparsers.add_parser("reset", help="Reset a workspace to a first-run state.")
    reset_parser.add_argument("--workspace", type=Path, default=None)

    api_parser = subparsers.add_parser("api", help="Run the FastAPI app.")
    api_parser.add_argument("--workspace", type=Path, default=None)
    api_parser.add_argument("--host", default="127.0.0.1")
    api_parser.add_argument("--port", type=int, default=8000)
    api_parser.add_argument("--reload", action="store_true")

    qq_parser = subparsers.add_parser("qq", help="Run the QQ bot.")
    qq_parser.add_argument("--workspace", type=Path, default=None)

    telegram_parser = subparsers.add_parser("telegram", help="Run the Telegram bot.")
    telegram_parser.add_argument("--workspace", type=Path, default=None)

    smoke_parser = subparsers.add_parser("smoke-sync", help="Run a TickTick/Dida smoke sync.")
    smoke_parser.add_argument("--workspace", type=Path, default=None)

    return parser


def _cmd_init(args: argparse.Namespace) -> None:
    _apply_workspace(args.workspace)
    settings = AppSettings()
    summary = init_workspace(settings=settings, force=args.force)
    _print_init_summary(summary)


def _remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _cmd_reset(args: argparse.Namespace) -> None:
    _apply_workspace(args.workspace)
    settings = AppSettings()

    _remove_path(settings.memory_path)
    _remove_path(settings.chroma_path)
    if settings.sqlite_path is not None:
        _remove_path(settings.sqlite_path)

    summary = init_workspace(settings=settings, force=False)

    print(f"workspace={settings.workspace_path}")
    print(f"db={settings.sqlite_path}")
    print(f"chroma={settings.chroma_path}")
    print(f"memory={settings.memory_path}")
    print(f"created={len(summary.created)}")


def _cmd_api(args: argparse.Namespace) -> None:
    _apply_workspace(args.workspace)
    uvicorn.run(
        "interview_agent.app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def _cmd_qq(args: argparse.Namespace) -> None:
    _apply_workspace(args.workspace)
    settings = get_settings()
    container = AppContainer.build(settings)
    client = QQBotClient(settings)
    service = QQBotService(container=container, client=client, settings=settings)
    service.run()


def _cmd_telegram(args: argparse.Namespace) -> None:
    _apply_workspace(args.workspace)
    settings = get_settings()
    container = AppContainer.build(settings)
    client = TelegramBotClient(settings)
    service = TelegramBotService(container=container, client=client, settings=settings)
    service.run()


def _cmd_smoke_sync(args: argparse.Namespace) -> None:
    _apply_workspace(args.workspace)
    settings = get_settings()
    container = AppContainer.build(settings)
    user_id = settings.default_user_id

    with container.db.session_scope() as session:
        plan = container.repository.latest_plan(session, user_id=user_id)
        if plan is None:
            today = date.today()
            plan = container.repository.create_plan(
                session,
                user_id=user_id,
                jd_id=None,
                start_date=today,
                end_date=today,
                summary="Smoke sync plan",
            )
            container.repository.create_task(
                session,
                user_id=user_id,
                plan_id=plan.id,
                title="Smoke test: sync one task to Dida365",
                dimension="execution",
                priority=4,
                due_at=datetime.combine(today, time(hour=21, minute=0)),
                duration_min=5,
                reason="Created by interview_agent.cli smoke-sync to verify Dida sync.",
            )

        summary = container.planning.sync_ticktick(session, user_id=user_id, plan_id=plan.id)

    print(f"mode={summary.mode}")
    print(f"synced={summary.synced_count}")
    for task in summary.tasks:
        print(f"{task.task_id} | {task.title} | {task.due_at.isoformat()} | status={task.status}")


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "init":
        _cmd_init(args)
        return
    if args.command == "reset":
        _cmd_reset(args)
        return
    if args.command == "api":
        _cmd_api(args)
        return
    if args.command == "qq":
        _cmd_qq(args)
        return
    if args.command == "telegram":
        _cmd_telegram(args)
        return
    if args.command == "smoke-sync":
        _cmd_smoke_sync(args)
        return

    parser.error(f"unknown command: {args.command}")
