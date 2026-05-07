from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, Sequence

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
class Dida365McpConfig:
    command: str
    args: list[str]
    env: dict[str, str]
    project_id: str
    project_name: str


class Dida365McpTickTickClient:
    def __init__(self, *, config: Dida365McpConfig) -> None:
        self.config = config

    def sync(self, tasks: Sequence[TickTickSyncTask]) -> TickTickSyncResult:
        if not tasks:
            return TickTickSyncResult(mode="live", synced_count=0, synced_tasks=[])
        return asyncio.run(self._sync_async(tasks))

    async def _sync_async(self, tasks: Sequence[TickTickSyncTask]) -> TickTickSyncResult:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise RuntimeError(
                "MCP client dependency is missing. Add `mcp` to the environment before enabling Dida365 MCP sync."
            ) from exc

        server_params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_response = await session.list_tools()
                tools = {tool.name: tool for tool in tools_response.tools}
                project_id = await self._resolve_project_id(session, tools)
                synced_tasks: list[TickTickSyncedTask] = []
                for task in tasks:
                    if task.ticktick_id:
                        remote_task_id = await self._update_task(session, tools, task, project_id)
                    else:
                        remote_task_id = await self._create_task(session, tools, task, project_id)
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

    async def _resolve_project_id(self, session, tools: dict[str, object]) -> str:
        if self.config.project_id.strip():
            return self.config.project_id.strip()
        tool_name = "dida365_list_projects"
        if tool_name not in tools:
            raise RuntimeError(f"Required MCP tool `{tool_name}` was not exposed by the Dida365 MCP server.")
        result = await session.call_tool(tool_name, arguments={})
        structured = self._extract_structured_content(result)
        projects = structured if isinstance(structured, list) else structured.get("projects", [])
        if isinstance(projects, list):
            for project in projects:
                if not isinstance(project, dict):
                    continue
                if str(project.get("name") or "").strip() == self.config.project_name:
                    project_id = str(project.get("id") or "").strip()
                    if project_id:
                        self.config.project_id = project_id
                        return project_id
        raise RuntimeError(
            "Dida365 MCP sync could not resolve a project id. "
            f"Set INTERVIEW_AGENT_DIDA365_PROJECT_ID or create a project named {self.config.project_name!r}."
        )

    async def _create_task(self, session, tools: dict[str, object], task: TickTickSyncTask, project_id: str) -> str:
        tool_name = "dida365_create_task"
        tool = self._require_tool(tools, tool_name)
        arguments = self._build_task_arguments(tool=tool, task=task, project_id=project_id, for_update=False)
        result = await session.call_tool(tool_name, arguments=arguments)
        remote_task_id = self._extract_remote_task_id(result, fallback="")
        if not remote_task_id:
            raise RuntimeError(f"Dida365 MCP create_task returned no task id for local_task_id={task.local_task_id}.")
        return remote_task_id

    async def _update_task(self, session, tools: dict[str, object], task: TickTickSyncTask, project_id: str) -> str:
        tool_name = "dida365_update_task"
        tool = self._require_tool(tools, tool_name)
        arguments = self._build_task_arguments(tool=tool, task=task, project_id=project_id, for_update=True)
        result = await session.call_tool(tool_name, arguments=arguments)
        return self._extract_remote_task_id(result, fallback=task.ticktick_id or "")

    def _require_tool(self, tools: dict[str, object], tool_name: str):
        if tool_name not in tools:
            raise RuntimeError(f"Required MCP tool `{tool_name}` was not exposed by the Dida365 MCP server.")
        return tools[tool_name]

    def _build_task_arguments(
        self,
        *,
        tool: object,
        task: TickTickSyncTask,
        project_id: str,
        for_update: bool,
    ) -> dict[str, object]:
        properties = self._tool_properties(tool)
        arguments: dict[str, object] = {}

        self._set_first(
            arguments,
            properties,
            ["task_id", "taskId", "id"],
            task.ticktick_id,
        )
        self._set_first(
            arguments,
            properties,
            ["project_id", "projectId", "project"],
            project_id,
        )
        self._set_first(arguments, properties, ["title", "name"], task.title)
        self._set_first(arguments, properties, ["content", "description", "desc"], task.content)
        self._set_first(
            arguments,
            properties,
            ["due_date", "dueDate", "due_at", "dueAt"],
            task.due_at.isoformat(timespec="seconds"),
        )
        self._set_first(arguments, properties, ["priority"], task.priority)

        if for_update and not any(key in arguments for key in ("task_id", "taskId", "id")):
            arguments["task_id"] = task.ticktick_id or ""
        if not any(key in arguments for key in ("project_id", "projectId", "project")):
            arguments["project_id"] = project_id
        if not any(key in arguments for key in ("title", "name")):
            arguments["title"] = task.title
        if not any(key in arguments for key in ("content", "description", "desc")):
            arguments["content"] = task.content
        if not any(key in arguments for key in ("due_date", "dueDate", "due_at", "dueAt")):
            arguments["dueDate"] = task.due_at.isoformat(timespec="seconds")
        if "priority" not in arguments:
            arguments["priority"] = task.priority

        return arguments

    def _tool_properties(self, tool: object) -> dict[str, object]:
        schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
        if not isinstance(schema, dict):
            return {}
        properties = schema.get("properties", {})
        return properties if isinstance(properties, dict) else {}

    def _set_first(
        self,
        arguments: dict[str, object],
        properties: dict[str, object],
        names: list[str],
        value: object,
    ) -> None:
        if value in (None, ""):
            return
        for name in names:
            if name in properties:
                arguments[name] = value
                return

    def _extract_structured_content(self, result: object) -> object:
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return structured
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            return structured
        content = getattr(result, "content", None)
        if isinstance(content, list):
            for item in content:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parsed = self._try_parse_json(text)
                    if parsed is not None:
                        return parsed
        return {}

    def _extract_remote_task_id(self, result: object, *, fallback: str) -> str:
        structured = self._extract_structured_content(result)
        task_id = self._find_task_id(structured)
        if task_id:
            return task_id
        content = getattr(result, "content", None)
        if isinstance(content, list):
            for item in content:
                text = getattr(item, "text", None)
                if not isinstance(text, str):
                    continue
                task_id = self._find_task_id(text)
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
            parsed = self._try_parse_json(payload)
            if parsed is not None:
                nested = self._find_task_id(parsed)
                if nested:
                    return nested
            match = re.search(r'"(?:task_id|taskId|id)"\s*:\s*"([^"]+)"', payload)
            if match:
                return match.group(1)
        return ""

    def _try_parse_json(self, text: str) -> object | None:
        text = text.strip()
        if not text or text[0] not in "[{":
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None


def build_ticktick_client(settings: AppSettings) -> TickTickClient:
    if not settings.dida365_enabled:
        return StubTickTickClient()
    if not settings.dida365_mcp_command.strip():
        raise RuntimeError("INTERVIEW_AGENT_DIDA365_MCP_COMMAND is required when dida365_enabled=true.")
    return Dida365McpTickTickClient(
        config=Dida365McpConfig(
            command=settings.dida365_mcp_command,
            args=shlex.split(settings.dida365_mcp_args),
            env=_build_mcp_env(settings),
            project_id=settings.dida365_project_id,
            project_name=settings.dida365_project_name,
        )
    )


def _build_mcp_env(settings: AppSettings) -> dict[str, str]:
    env = dict(os.environ)
    env["DIDA365_REGION"] = settings.dida365_region
    if settings.dida365_access_token.strip():
        env["DIDA365_ACCESS_TOKEN"] = settings.dida365_access_token
    return env
