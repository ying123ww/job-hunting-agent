from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol, Sequence

import httpx

from interview_agent.app.config import AppSettings


SyncMode = Literal["dry_run", "live"]
Region = Literal["china", "international"]


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

    def fetch_statuses(self, tasks: Sequence[TickTickSyncTask]) -> dict[str, str]:
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

    def fetch_statuses(self, tasks: Sequence[TickTickSyncTask]) -> dict[str, str]:
        return {}


@dataclass(slots=True)
class Dida365Config:
    access_token: str
    project_id: str
    project_name: str
    region: Region

    @property
    def api_base_url(self) -> str:
        if self.region == "international":
            return "https://api.ticktick.com/open/v1"
        return "https://api.dida365.com/open/v1"


class Dida365TickTickClient:
    def __init__(self, *, config: Dida365Config) -> None:
        self.config = config
        self._client = httpx.Client(
            base_url=self.config.api_base_url,
            headers={"Authorization": f"Bearer {self.config.access_token}"},
            timeout=30.0,
        )

    def sync(self, tasks: Sequence[TickTickSyncTask]) -> TickTickSyncResult:
        if not tasks:
            return TickTickSyncResult(mode="live", synced_count=0, synced_tasks=[])
        project_id = self._resolve_project_id()
        synced_tasks: list[TickTickSyncedTask] = []
        for task in tasks:
            payload = self._build_task_payload(task=task, project_id=project_id)
            if task.ticktick_id:
                remote_task_id = self._update_task(task.ticktick_id, payload)
            else:
                remote_task_id = self._create_task(payload, local_task_id=task.local_task_id)
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

    def fetch_statuses(self, tasks: Sequence[TickTickSyncTask]) -> dict[str, str]:
        tracked = [task for task in tasks if task.ticktick_id]
        if not tracked:
            return {}
        project_id = self._resolve_project_id()
        undone_ids = self._list_undone_task_ids(project_id)
        completed_ids = self._list_completed_task_ids(tracked, project_id)
        statuses: dict[str, str] = {}
        for task in tracked:
            remote_id = task.ticktick_id or ""
            if remote_id in completed_ids:
                statuses[task.local_task_id] = "completed"
            elif remote_id in undone_ids:
                statuses[task.local_task_id] = "pending"
        return statuses

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._client.request(method, path, **kwargs)
        response.raise_for_status()
        return response

    def _resolve_project_id(self) -> str:
        if self.config.project_id.strip():
            return self.config.project_id.strip()
        response = self._request("GET", "/project")
        projects = response.json()
        if isinstance(projects, list):
            for project in projects:
                if str(project.get("name") or "").strip() != self.config.project_name:
                    continue
                project_id = str(project.get("id") or "").strip()
                if project_id:
                    self.config.project_id = project_id
                    return project_id
        raise RuntimeError(
            "Dida365 sync could not resolve a project id. "
            f"Set INTERVIEW_AGENT_DIDA365_PROJECT_ID or create a project named {self.config.project_name!r}."
        )

    def _create_task(self, payload: dict[str, object], *, local_task_id: str) -> str:
        response = self._request("POST", "/task", json=payload)
        remote_task_id = self._extract_remote_task_id(response.json())
        if not remote_task_id:
            raise RuntimeError(f"Dida365 create_task returned no task id for local_task_id={local_task_id}.")
        return remote_task_id

    def _update_task(self, task_id: str, payload: dict[str, object]) -> str:
        response = self._request("POST", f"/task/{task_id}", json=payload)
        if response.text.strip():
            return self._extract_remote_task_id(response.json(), fallback=task_id)
        return task_id

    def _list_undone_task_ids(self, project_id: str) -> set[str]:
        response = self._request("GET", f"/project/{project_id}/data")
        payload = response.json()
        tasks = payload.get("tasks", []) if isinstance(payload, dict) else []
        return self._collect_task_like_ids(tasks)

    def _list_completed_task_ids(self, tasks: Sequence[TickTickSyncTask], project_id: str) -> set[str]:
        now = datetime.now()
        from_date = min(task.due_at for task in tasks) - timedelta(days=30)
        to_date = max(now, max(task.due_at for task in tasks)) + timedelta(days=1)
        response = self._request(
            "POST",
            "/task/completed",
            json={
                "projectIds": [project_id],
                "startDate": from_date.isoformat(timespec="seconds"),
                "endDate": to_date.isoformat(timespec="seconds"),
            },
        )
        return self._collect_task_like_ids(response.json())

    def _build_task_payload(self, *, task: TickTickSyncTask, project_id: str) -> dict[str, object]:
        return {
            "projectId": project_id,
            "title": task.title,
            "content": task.content,
            "dueDate": task.due_at.isoformat(timespec="seconds"),
            "priority": task.priority,
        }

    def _extract_remote_task_id(self, payload: object, *, fallback: str = "") -> str:
        task_id = self._find_task_id(payload)
        if task_id:
            return task_id
        return fallback

    def _find_task_id(self, payload: object) -> str:
        if isinstance(payload, dict):
            for key in ("task_id", "taskId", "id"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for value in payload.values():
                nested = self._find_task_id(value)
                if nested:
                    return nested
        if isinstance(payload, list):
            for item in payload:
                nested = self._find_task_id(item)
                if nested:
                    return nested
        if isinstance(payload, str):
            return payload.strip()
        return ""

    def _collect_task_like_ids(self, payload: object) -> set[str]:
        ids: set[str] = set()
        self._collect_task_like_ids_into(payload, ids)
        return ids

    def _collect_task_like_ids_into(self, payload: object, target: set[str]) -> None:
        if isinstance(payload, dict):
            candidate = None
            for key in ("task_id", "taskId", "id"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    candidate = value.strip()
                    break
            if candidate and any(
                key in payload
                for key in ("title", "content", "projectId", "project_id", "dueDate", "due_date", "priority", "status")
            ):
                target.add(candidate)
            for value in payload.values():
                self._collect_task_like_ids_into(value, target)
            return
        if isinstance(payload, list):
            for item in payload:
                self._collect_task_like_ids_into(item, target)


def build_ticktick_client(settings: AppSettings) -> TickTickClient:
    if not settings.dida365_enabled:
        return StubTickTickClient()
    if not settings.dida365_access_token.strip():
        raise RuntimeError("INTERVIEW_AGENT_DIDA365_ACCESS_TOKEN is required when dida365_enabled=true.")
    region = settings.dida365_region.strip() or "china"
    if region not in {"china", "international"}:
        raise RuntimeError("INTERVIEW_AGENT_DIDA365_REGION must be `china` or `international`.")
    validated_region: Region = "international" if region == "international" else "china"
    return Dida365TickTickClient(
        config=Dida365Config(
            access_token=settings.dida365_access_token,
            project_id=settings.dida365_project_id,
            project_name=settings.dida365_project_name,
            region=validated_region,
        )
    )
