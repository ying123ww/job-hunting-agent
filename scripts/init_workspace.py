from __future__ import annotations

import argparse
import os
from pathlib import Path

from interview_agent.app.config import AppSettings
from interview_agent.app.workspace_init import InitSummary, init_workspace


def _print_group(title: str, paths: list[Path]) -> None:
    if not paths:
        return
    print(title)
    for path in paths:
        print(f"  {path}")


def _print_summary(summary: InitSummary) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize a workspace with runtime files and local storage."
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Target workspace directory. Defaults to INTERVIEW_AGENT_WORKSPACE_DIR or ./workspace.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite workspace template files only. Does not clear app.db or chroma data.",
    )
    args = parser.parse_args()

    if args.workspace is not None:
        os.environ["INTERVIEW_AGENT_WORKSPACE_DIR"] = str(args.workspace)

    settings = AppSettings()
    summary = init_workspace(settings=settings, force=args.force)
    _print_summary(summary)


if __name__ == "__main__":
    main()
