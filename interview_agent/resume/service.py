from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from interview_agent.app.config import AppSettings
from interview_agent.ingestion.extractors import TextExtractor
from interview_agent.ingestion.service import DocumentIngestionService, IngestedDocument


DEFAULT_RESUME_TEX = r"""\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage[hidelinks]{hyperref}
\usepackage{enumitem}
\setlist[itemize]{leftmargin=1.2em}
\setlength{\parindent}{0pt}
\begin{document}

\begin{center}
  {\LARGE Your Name}\\
  \vspace{4pt}
  your.email@example.com \quad|\quad +86 138-0000-0000 \quad|\quad \href{https://github.com/yourname}{github.com/yourname}
\end{center}

\section*{Summary}
Backend-focused engineer with experience in distributed systems, data products, and AI applications.

\section*{Experience}
\textbf{Example Company} \hfill 2024 -- Present\\
Software Engineer Intern
\begin{itemize}
  \item Built services with Python, SQL, and Redis for internal productivity workflows.
  \item Improved reliability and developer efficiency through automation and observability.
\end{itemize}

\section*{Projects}
\textbf{Interview Copilot Agent}
\begin{itemize}
  \item Designed an agentic workflow for resume, JD, and interview question analysis.
  \item Added retrieval, planning, and feedback loops to support targeted preparation.
\end{itemize}

\section*{Skills}
Python, SQL, Redis, FastAPI, Vue, RAG, LLM systems

\end{document}
"""


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value)


@dataclass(slots=True)
class ResumeState:
    last_saved_at: datetime | None = None
    last_compiled_at: datetime | None = None
    last_compile_status: str = "not_run"
    last_compile_error_summary: str | None = None
    last_resume_document_id: str | None = None

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "ResumeState":
        return cls(
            last_saved_at=_parse_datetime(payload.get("last_saved_at")),
            last_compiled_at=_parse_datetime(payload.get("last_compiled_at")),
            last_compile_status=str(payload.get("last_compile_status") or "not_run"),
            last_compile_error_summary=str(payload.get("last_compile_error_summary") or "") or None,
            last_resume_document_id=str(payload.get("last_resume_document_id") or "") or None,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "last_saved_at": _serialize_datetime(self.last_saved_at),
            "last_compiled_at": _serialize_datetime(self.last_compiled_at),
            "last_compile_status": self.last_compile_status,
            "last_compile_error_summary": self.last_compile_error_summary,
            "last_resume_document_id": self.last_resume_document_id,
        }


@dataclass(slots=True)
class ResumeSourceSnapshot:
    source: str
    last_saved_at: datetime | None
    last_compiled_at: datetime | None
    last_compile_status: str
    last_compile_error_summary: str | None
    last_resume_document_id: str | None
    compiler_available: bool
    pdf_exists: bool


@dataclass(slots=True)
class ResumeSaveResult(ResumeSourceSnapshot):
    content_hash: str
    chunk_count: int


@dataclass(slots=True)
class ResumeCompileResult:
    last_compiled_at: datetime
    last_compile_status: str
    last_compile_error_summary: str | None
    compiler_available: bool
    pdf_exists: bool
    log_excerpt: str


class ResumeWorkspaceService:
    def __init__(
        self,
        *,
        settings: AppSettings,
        document_ingestion: DocumentIngestionService,
    ) -> None:
        self.settings = settings
        self.document_ingestion = document_ingestion
        self.extractor = TextExtractor()

    def ensure_workspace_files(self) -> None:
        self.settings.resume_path.mkdir(parents=True, exist_ok=True)
        if not self.settings.resume_source_path.exists():
            self.settings.resume_source_path.write_text(DEFAULT_RESUME_TEX, encoding="utf-8")
        if not self.settings.resume_compile_log_path.exists():
            self.settings.resume_compile_log_path.write_text("", encoding="utf-8")
        if not self.settings.resume_state_path.exists():
            self._write_state(ResumeState())

    def get_source_snapshot(self) -> ResumeSourceSnapshot:
        self.ensure_workspace_files()
        state = self._read_state()
        return ResumeSourceSnapshot(
            source=self.settings.resume_source_path.read_text(encoding="utf-8"),
            last_saved_at=state.last_saved_at,
            last_compiled_at=state.last_compiled_at,
            last_compile_status=state.last_compile_status,
            last_compile_error_summary=state.last_compile_error_summary,
            last_resume_document_id=state.last_resume_document_id,
            compiler_available=self.compiler_available(),
            pdf_exists=self.settings.resume_pdf_path.exists(),
        )

    def save_source(self, session, *, user_id: str, source: str) -> ResumeSaveResult:
        self.ensure_workspace_files()
        previous_source = self.settings.resume_source_path.read_text(encoding="utf-8")
        self.settings.resume_source_path.write_text(source, encoding="utf-8")
        try:
            result = self.document_ingestion.replace_resume_representation(
                session,
                user_id=user_id,
                text=source,
                filename=self.settings.resume_source_path.name,
            )
        except Exception:
            self.settings.resume_source_path.write_text(previous_source, encoding="utf-8")
            raise

        state = self._read_state()
        state.last_saved_at = _utcnow()
        state.last_resume_document_id = result.document_id
        self._write_state(state)
        snapshot = self.get_source_snapshot()
        return ResumeSaveResult(
            source=snapshot.source,
            last_saved_at=snapshot.last_saved_at,
            last_compiled_at=snapshot.last_compiled_at,
            last_compile_status=snapshot.last_compile_status,
            last_compile_error_summary=snapshot.last_compile_error_summary,
            last_resume_document_id=snapshot.last_resume_document_id,
            compiler_available=snapshot.compiler_available,
            pdf_exists=snapshot.pdf_exists,
            content_hash=result.content_hash,
            chunk_count=result.chunk_count,
        )

    def save_imported_source(
        self,
        session,
        *,
        user_id: str,
        text: str | None,
        content_base64: str | None,
        filename: str | None,
    ) -> ResumeSaveResult:
        extracted = self.extractor.extract(text=text, content_base64=content_base64, filename=filename)
        return self.save_source(session, user_id=user_id, source=extracted.text)

    def compile_source(self) -> ResumeCompileResult:
        self.ensure_workspace_files()
        compile_time = _utcnow()
        state = self._read_state()
        compiler_path = self._resolve_compiler_path()
        if compiler_path is None:
            summary = (
                "Tectonic compiler is not available. Set INTERVIEW_AGENT_TECTONIC_BIN "
                "or install `tectonic`."
            )
            self.settings.resume_compile_log_path.write_text(summary + "\n", encoding="utf-8")
            state.last_compiled_at = compile_time
            state.last_compile_status = "missing_compiler"
            state.last_compile_error_summary = summary
            self._write_state(state)
            return ResumeCompileResult(
                last_compiled_at=compile_time,
                last_compile_status="missing_compiler",
                last_compile_error_summary=summary,
                compiler_available=False,
                pdf_exists=self.settings.resume_pdf_path.exists(),
                log_excerpt=summary,
            )

        previous_pdf = self.settings.resume_pdf_path.read_bytes() if self.settings.resume_pdf_path.exists() else None
        process = subprocess.run(
            [
                compiler_path,
                "-X",
                "compile",
                self.settings.resume_source_path.name,
                "--outdir",
                str(self.settings.resume_path),
                "--keep-logs",
            ],
            cwd=self.settings.resume_path,
            capture_output=True,
            text=True,
            check=False,
        )
        full_log = self._collect_compile_log(stdout=process.stdout, stderr=process.stderr)
        self.settings.resume_compile_log_path.write_text(full_log, encoding="utf-8")

        if process.returncode == 0 and self.settings.resume_pdf_path.exists():
            state.last_compiled_at = compile_time
            state.last_compile_status = "success"
            state.last_compile_error_summary = None
            self._write_state(state)
            return ResumeCompileResult(
                last_compiled_at=compile_time,
                last_compile_status="success",
                last_compile_error_summary=None,
                compiler_available=True,
                pdf_exists=True,
                log_excerpt=self._excerpt(full_log),
            )

        if previous_pdf is not None:
            self.settings.resume_pdf_path.write_bytes(previous_pdf)
        elif self.settings.resume_pdf_path.exists():
            self.settings.resume_pdf_path.unlink()

        summary = self._summarize_compile_failure(full_log)
        state.last_compiled_at = compile_time
        state.last_compile_status = "failed"
        state.last_compile_error_summary = summary
        self._write_state(state)
        return ResumeCompileResult(
            last_compiled_at=compile_time,
            last_compile_status="failed",
            last_compile_error_summary=summary,
            compiler_available=True,
            pdf_exists=self.settings.resume_pdf_path.exists(),
            log_excerpt=self._excerpt(full_log),
        )

    def compiler_available(self) -> bool:
        return self._resolve_compiler_path() is not None

    def _resolve_compiler_path(self) -> str | None:
        candidate = self.settings.tectonic_bin.strip() or "tectonic"
        if "/" in candidate:
            path = Path(candidate).expanduser()
            return str(path) if path.exists() else None
        return shutil.which(candidate)

    def _read_state(self) -> ResumeState:
        self.ensure_workspace_files()
        payload = json.loads(self.settings.resume_state_path.read_text(encoding="utf-8"))
        return ResumeState.from_json(payload if isinstance(payload, dict) else {})

    def _write_state(self, state: ResumeState) -> None:
        self.settings.resume_state_path.write_text(
            json.dumps(state.to_json(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _collect_compile_log(self, *, stdout: str, stderr: str) -> str:
        log_path = self.settings.resume_path / "resume.log"
        parts: list[str] = []
        if log_path.exists():
            parts.append(log_path.read_text(encoding="utf-8", errors="replace").strip())
        combined_stream = "\n".join(part for part in [stdout.strip(), stderr.strip()] if part)
        if combined_stream:
            parts.append(combined_stream)
        return "\n\n".join(part for part in parts if part).strip() + "\n"

    def _summarize_compile_failure(self, full_log: str) -> str:
        lines = [line.strip() for line in full_log.splitlines() if line.strip()]
        for line in lines:
            lowered = line.lower()
            if line.startswith("!") or lowered.startswith("error:") or lowered.startswith("fatal error"):
                return line[:300]
        return (lines[-1] if lines else "LaTeX compilation failed.")[:300]

    def _excerpt(self, full_log: str, *, max_lines: int = 40, max_chars: int = 4000) -> str:
        lines = full_log.strip().splitlines()
        excerpt = "\n".join(lines[-max_lines:]).strip()
        return excerpt[-max_chars:]
