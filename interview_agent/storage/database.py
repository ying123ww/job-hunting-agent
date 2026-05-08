from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from interview_agent.storage.models import Base


class DatabaseManager:
    def __init__(self, database_url: str) -> None:
        connect_args: dict[str, object] = {}
        if database_url.startswith("sqlite:///"):
            connect_args["check_same_thread"] = False
        self.engine = create_engine(database_url, future=True, connect_args=connect_args)
        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            class_=Session,
        )

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)
        self._repair_schema()

    def supports_fts5(self) -> bool:
        with self.engine.begin() as connection:
            try:
                connection.execute(text("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(content)"))
                connection.execute(text("DROP TABLE temp.fts5_probe"))
            except Exception:
                return False
        return True

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _repair_schema(self) -> None:
        dialect = self.engine.dialect.name
        if dialect != "sqlite":
            return
        if not self.supports_fts5():
            raise RuntimeError("SQLite FTS5 is required for lexical retrieval but is not available in this runtime.")

        question_columns = {
            "normalized_text": "TEXT",
            "question_fingerprint": "TEXT",
            "source_scope": "TEXT",
            "is_active": "BOOLEAN NOT NULL DEFAULT 1",
            "superseded_by": "TEXT",
        }
        with self.engine.begin() as connection:
            existing_columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(questions)")).all()
            }
            for name, ddl in question_columns.items():
                if name in existing_columns:
                    continue
                connection.execute(text(f"ALTER TABLE questions ADD COLUMN {name} {ddl}"))

            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_questions_user_scope_active "
                    "ON questions (user_id, source_scope, is_active)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_questions_user_fingerprint_active "
                    "ON questions (user_id, question_fingerprint, is_active)"
                )
            )
            connection.execute(
                text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS retrieval_fts USING fts5("
                    "item_id UNINDEXED, "
                    "item_type UNINDEXED, "
                    "searchable_text, "
                    "is_active UNINDEXED, "
                    "user_id UNINDEXED, "
                    "source_scope UNINDEXED, "
                    "source_type UNINDEXED, "
                    "dimension UNINDEXED, "
                    "tokenize = 'unicode61'"
                    ")"
                )
            )
