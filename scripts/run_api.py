from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the FastAPI app against a target workspace.")
    parser.add_argument("--workspace", type=Path, default=None, help="Override INTERVIEW_AGENT_WORKSPACE_DIR.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    if args.workspace is not None:
        os.environ["INTERVIEW_AGENT_WORKSPACE_DIR"] = str(args.workspace)

    uvicorn.run(
        "interview_agent.app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
