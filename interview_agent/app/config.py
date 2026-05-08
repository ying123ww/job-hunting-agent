from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    app_name: str = Field(default="Interview Copilot Agent")
    env: str = Field(default="dev")
    default_user_id: str = Field(default="u_demo")
    workspace_dir: str = Field(default="./workspace")
    database_url: str = Field(default="")
    chroma_dir: str = Field(default="")
    memory_dir: str = Field(default="")
    llm_base_url: str = Field(default="")
    llm_api_key: str = Field(default="")
    llm_chat_model: str = Field(default="gpt-4o-mini")
    embedding_base_url: str = Field(default="")
    embedding_api_key: str = Field(default="")
    llm_embedding_model: str = Field(default="text-embedding-3-small")
    embedding_dimensions: int = Field(default=64)
    text_chunk_size: int = Field(default=600)
    text_chunk_overlap: int = Field(default=80)
    dida365_enabled: bool = Field(default=False)
    dida365_access_token: str = Field(default="")
    dida365_project_id: str = Field(default="")
    dida365_project_name: str = Field(default="Interview Copilot Agent")
    dida365_region: str = Field(default="china")
    telegram_bot_token: str = Field(default="")
    telegram_api_base_url: str = Field(default="https://api.telegram.org")
    telegram_poll_timeout_sec: int = Field(default=30)
    telegram_poll_max_backoff_sec: int = Field(default=30)
    telegram_drop_pending_updates: bool = Field(default=True)
    telegram_allowed_chat_ids: str = Field(default="")
    qqbot_app_id: str = Field(default="")
    qqbot_client_secret: str = Field(default="")
    qqbot_api_base_url: str = Field(default="https://api.sgroup.qq.com")
    qqbot_token_url: str = Field(default="https://bots.qq.com/app/getAppAccessToken")
    qqbot_gateway_backoff_sec: int = Field(default=5)
    qqbot_allowed_openids: str = Field(default="")

    model_config = SettingsConfigDict(
        env_prefix="INTERVIEW_AGENT_",
        env_file=".env",
        extra="ignore",
    )

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace_dir).resolve()

    @property
    def resolved_database_url(self) -> str:
        raw = self.database_url.strip()
        if raw == "":
            return f"sqlite:///{(self.workspace_path / 'app.db').resolve()}"
        prefix = "sqlite:///"
        if raw.startswith(prefix):
            sqlite_path = Path(raw.removeprefix(prefix))
            return f"sqlite:///{sqlite_path.resolve()}"
        return raw

    @property
    def chroma_path(self) -> Path:
        raw = self.chroma_dir.strip()
        if raw == "":
            return (self.workspace_path / "chroma").resolve()
        return Path(raw).resolve()

    @property
    def memory_path(self) -> Path:
        raw = self.memory_dir.strip()
        if raw == "":
            return (self.workspace_path / "memory").resolve()
        return Path(raw).resolve()

    @property
    def sqlite_path(self) -> Path | None:
        prefix = "sqlite:///"
        database_url = self.resolved_database_url
        if not database_url.startswith(prefix):
            return None
        return Path(database_url.removeprefix(prefix)).resolve()

    @property
    def telegram_allowed_chat_id_set(self) -> set[int]:
        values: set[int] = set()
        for raw in self.telegram_allowed_chat_ids.split(","):
            item = raw.strip()
            if not item:
                continue
            values.add(int(item))
        return values

    @property
    def qqbot_allowed_openid_set(self) -> set[str]:
        values: set[str] = set()
        for raw in self.qqbot_allowed_openids.split(","):
            item = raw.strip()
            if not item:
                continue
            values.add(item)
        return values

    def ensure_data_dirs(self) -> None:
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self.memory_path.mkdir(parents=True, exist_ok=True)
        if self.sqlite_path is not None:
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    settings = AppSettings()
    settings.ensure_data_dirs()
    return settings
