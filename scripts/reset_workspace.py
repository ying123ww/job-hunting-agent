from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from interview_agent.app.config import AppSettings, get_settings
from interview_agent.app.workspace_init import init_workspace


def _remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset the app runtime data in a target workspace."
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Override INTERVIEW_AGENT_WORKSPACE_DIR for this reset.",
    )
    args = parser.parse_args()

    if args.workspace is not None:
        os.environ["INTERVIEW_AGENT_WORKSPACE_DIR"] = str(args.workspace)

    get_settings.cache_clear()
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


if __name__ == "__main__":
    main()
