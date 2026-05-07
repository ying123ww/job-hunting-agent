from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, Sequence

import httpx

from interview_agent.app.config import AppSettings


SyncMode = Literal["dry_run", "live"]


@dataclass(slots=True)
class TickTickSyncTask:
    local_task_id: str
    title: str
    content: str
    due_at: datetime
    priority: int
    ticktick_id: str | None = None


@dataclass(slots=True)
class TickTickSyncedTask:
    local_task_id: str
    remote_task_id: str
    project_id: str
    mode: SyncMode


@dataclass(slots=True)
class TickTickSyncResult:
    mode: SyncMode
    synced_count: int
    synced_tasks: list[TickTickSyncedTask]


class TickTickClient(Protocol):
    def sync(self, tasks: Sequence[TickTickSyncTask]) -> TickTickSyncResult:
        ...


@dataclass(slots=True)
class StubTickTickClient:
    synced_payloads: list[dict[str, object]] = field(default_factory=list)

    def sync(self, tasks: Sequence[TickTickSyncTask]) -> TickTickSyncResult:
        synced_tasks = [
            TickTickSyncedTask(
                local_task_id=task.local_task_id,
                remote_task_id=task.ticktick_id or f"dry_run_{task.local_task_id}",
                project_id="dry_run",
                mode="dry_run",
            )
            for task in tasks
        ]
        self.synced_payloads.append(
            {
                "mode": "dry_run",
                "count": len(tasks),
                "tasks": [task.local_task_id for task in tasks],
            }
        )
        return TickTickSyncResult(
            mode="dry_run",
            synced_count=len(synced_tasks),
            synced_tasks=synced_tasks,
        )


@dataclass(slots=True)
class Dida365Config:
    access_token: str
    project_id: str
    project_name: str
    base_url: str
    timeout_seconds: float = 15.0


class Dida365TickTickClient:
    def __init__(
        self,
        *,
        config: Dida365Config,
        client_factory=None,
    ) -> None:
        self.config = config
        self.client_factory = client_factory or self._default_client_factory
        self._resolved_project_id = config.project_id.strip() or None

    def sync(self, tasks: Sequence[TickTickSyncTask]) -> TickTickSyncResult:
        if not tasks:
            return TickTickSyncResult(mode="live", synced_count=0, synced_tasks=[])

        project_id = self._resolve_project_id()
        synced_tasks: list[TickTickSyncedTask] = []
        for task in tasks:
            payload = {
                "projectId": project_id,
                "title": task.title,
                "content": task.content,
                "dueDate": task.due_at.isoformat(timespec="seconds"),
                "priority": task.priority,
            }
            if task.ticktick_id:
                data = self._request("POST", f"/task/{task.ticktick_id}", json=payload)
                remote_task_id = str(data.get("id") or task.ticktick_id)
            else:
                data = self._request("POST", "/task", json=payload)
                remote_task_id = str(data.get("id") or "")
                if not remote_task_id:
                    raise RuntimeError(f"Dida365 create task did not return an id for local_task_id={task.local_task_id}.")
            synced_tasks.append(
                TickTickSyncedTask(
                    local_task_id=task.local_task_id,
                    remote_task_id=remote_task_id,
                    project_id=project_id,
                    mode="live",
                )
            )

        return TickTickSyncResult(
            mode="live",
            synced_count=len(synced_tasks),
            synced_tasks=synced_tasks,
        )

    def _resolve_project_id(self) -> str:
        if self._resolved_project_id is not None:
            return self._resolved_project_id

        projects = self._request("GET", "/project")
        if isinstance(projects, list):
            for project in projects:
                if str(project.get("name") or "").strip() == self.config.project_name:
                    project_id = str(project.get("id") or "").strip()
                    if project_id:
                        self._resolved_project_id = project_id
                        return project_id
        raise RuntimeError(
            "Dida365 project_id is not configured, and no project matched "
            f"project_name={self.config.project_name!r}."
        )

    def _request(self, method: str, path: str, *, json: dict[str, object] | None = None):
        with self.client_factory() as client:
            response = client.request(method, path, json=json)
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()

    def _default_client_factory(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.config.base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {self.config.access_token}",
                "Content-Type": "application/json",
            },
            timeout=self.config.timeout_seconds,
        )


def build_ticktick_client(settings: AppSettings) -> TickTickClient:
    if not settings.dida365_enabled or not settings.dida365_access_token.strip():
        return StubTickTickClient()
    return Dida365TickTickClient(
        config=Dida365Config(
            access_token=settings.dida365_access_token,
            project_id=settings.dida365_project_id,
            project_name=settings.dida365_project_name,
            base_url=settings.dida365_base_url,
            timeout_seconds=settings.dida365_timeout_seconds,
        )
    )
