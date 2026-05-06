from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StubTickTickClient:
    synced_payloads: list[dict[str, Any]] = field(default_factory=list)

    def sync(self, tasks) -> None:
        self.synced_payloads.append(
            {
                "mode": "dry_run",
                "count": len(tasks),
                "tasks": [getattr(task, "task_id", None) for task in tasks],
            }
        )
