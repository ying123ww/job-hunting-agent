from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from interview_agent.app.config import AppSettings
from interview_agent.app.providers import OpenAICompatibleProvider
from interview_agent.ingestion.chunking import split_text
from interview_agent.ingestion.extractors import TextExtractor
from interview_agent.ingestion.parser import (
    build_reference_answer,
    evaluate_answer,
    extract_jd_requirements,
    extract_projects_from_resume,
    infer_dimension,
    infer_topics,
    normalize_text,
    parse_question_batch,
)
from interview_agent.storage.repositories import (
    InterviewRepository,
    build_chunk_searchable_text,
    build_question_searchable_text,
)
from interview_agent.storage.vector_store import ChromaVectorStore


@dataclass(slots=True)
class IngestedDocument:
    document_id: str
    chunk_count: int
    content_hash: str
    raw_text: str


@dataclass(slots=True)
class QuestionCandidate:
    question: str
    answer: str
    source_company: str | None
    source_role: str | None
    dimension: str
    topics: list[str]
    reference_answer: str
    block_text: str


@dataclass(slots=True)
class QuestionIngestionResult:
    ingested_document: IngestedDocument
    records: list[dict[str, Any]]
    processed_count: int
    skipped_count: int
    inactive_count: int
    fallback_used: bool
    pipeline_version: str = "question_ingestion_v2"


def _question_fingerprint(normalized_text: str) -> str:
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


class DocumentIngestionService:
    def __init__(
        self,
        *,
        settings: AppSettings,
        repository: InterviewRepository,
        vector_store: ChromaVectorStore,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.vector_store = vector_store
        self.extractor = TextExtractor()

    def _sync_chunk_fts(self, session, *, chunk, source_scope: str | None = None) -> None:
        metadata = chunk.metadata_json or {}
        if source_scope and not metadata.get("source_scope"):
            metadata = {**metadata, "source_scope": source_scope}
            chunk.metadata_json = metadata
        self.repository.update_retrieval_fts(
            session,
            item_id=chunk.id,
            item_type="chunk",
            searchable_text=build_chunk_searchable_text(chunk),
            is_active=True,
            user_id=chunk.user_id,
            source_scope=str(metadata.get("source_scope") or "") or None,
            source_type=chunk.source_type,
            dimension=str(metadata.get("dimension") or "") or None,
        )

    def _mark_chunks_inactive(self, session, *, chunks: list[Any]) -> None:
        grouped: dict[str, list[Any]] = {}
        for chunk in chunks:
            grouped.setdefault(chunk.vector_collection, []).append(chunk)
            self.repository.delete_retrieval_fts(session, item_id=chunk.id)

        for collection_name, items in grouped.items():
            self.vector_store.upsert(
                collection_name=collection_name,
                ids=[chunk.vector_id or chunk.id for chunk in items],
                texts=[chunk.text for chunk in items],
                metadatas=[
                    {
                        "user_id": chunk.user_id,
                        "source_type": chunk.source_type,
                        "document_id": chunk.document_id,
                        "chunk_id": chunk.id,
                        "question_id": str(chunk.metadata_json.get("question_id", "")),
                        "dimension": str(chunk.metadata_json.get("dimension", "")),
                        "topics_text": str(chunk.metadata_json.get("topics_text", "")),
                        "is_active": False,
                    }
                    for chunk in items
                ],
            )

    def _delete_chunks(self, session, *, chunks: list[Any]) -> None:
        grouped: dict[str, list[str]] = {}
        for chunk in chunks:
            grouped.setdefault(chunk.vector_collection, []).append(chunk.vector_id or chunk.id)
            self.repository.delete_retrieval_fts(session, item_id=chunk.id)
        for collection_name, ids in grouped.items():
            self.vector_store.delete(collection_name=collection_name, ids=ids)

    def _create_document_chunks(
        self,
        session,
        *,
        document_id: str,
        user_id: str,
        source_type: str,
        text: str,
        filename: str | None,
        metadata: dict[str, Any],
    ) -> int:
        chunks = split_text(
            text,
            chunk_size=self.settings.text_chunk_size,
            chunk_overlap=self.settings.text_chunk_overlap,
        )
        vector_ids: list[str] = []
        texts: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for index, chunk_text in enumerate(chunks):
            metadata_json = {
                **metadata,
                "filename": filename,
                "chunk_kind": "document",
            }
            chunk = self.repository.create_document_chunk(
                session,
                document_id=document_id,
                user_id=user_id,
                source_type=source_type,
                chunk_index=index,
                text=chunk_text,
                metadata_json=metadata_json,
                vector_collection="interview_chunks",
                vector_id=None,
            )
            vector_ids.append(chunk.id)
            texts.append(chunk_text)
            metadatas.append(
                {
                    "user_id": user_id,
                    "source_type": source_type,
                    "document_id": document_id,
                    "chunk_id": chunk.id,
                    "question_id": "",
                    "dimension": metadata.get("dimension", ""),
                    "topics_text": metadata.get("topics_text", ""),
                    "is_active": True,
                }
            )
            chunk.vector_id = chunk.id
        if texts:
            self.vector_store.upsert(
                collection_name="interview_chunks",
                ids=vector_ids,
                texts=texts,
                metadatas=metadatas,
            )
            for chunk_id in vector_ids:
                chunk = self.repository.get_document_chunk(session, chunk_id=chunk_id)
                if chunk is not None:
                    self._sync_chunk_fts(session, chunk=chunk)
        return len(chunks)

    def ingest_document(
        self,
        session,
        *,
        user_id: str,
        source_type: str,
        text: str | None,
        content_base64: str | None,
        filename: str | None,
        metadata: dict[str, Any],
    ) -> IngestedDocument:
        extracted = self.extractor.extract(text=text, content_base64=content_base64, filename=filename)
        content_hash = hashlib.sha256(extracted.text.encode("utf-8")).hexdigest()
        self.repository.ensure_user(session, user_id)
        document = self.repository.create_document(
            session,
            user_id=user_id,
            source_type=source_type,
            filename=extracted.filename,
            content_hash=content_hash,
            raw_text=extracted.text,
            metadata_json=metadata,
        )
        deactivated_document_ids = self.repository.deactivate_documents(
            session,
            user_id=user_id,
            source_type=source_type,
            metadata=metadata,
            superseded_by=document.id,
            exclude_document_id=document.id,
        )
        if deactivated_document_ids:
            old_chunks = self.repository.list_chunks_for_documents(
                session,
                document_ids=deactivated_document_ids,
            )
            if old_chunks:
                self._mark_chunks_inactive(session, chunks=old_chunks)
        chunk_count = self._create_document_chunks(
            session,
            document_id=document.id,
            user_id=user_id,
            source_type=source_type,
            text=extracted.text,
            filename=extracted.filename,
            metadata=metadata,
        )
        return IngestedDocument(
            document_id=document.id,
            chunk_count=chunk_count,
            content_hash=content_hash,
            raw_text=extracted.text,
        )

    def persist_resume_side_effects(self, session, *, user_id: str, document_id: str, text: str) -> None:
        projects = extract_projects_from_resume(text)
        for project in projects:
            self.repository.create_project(
                session,
                user_id=user_id,
                name=str(project["name"]),
                tech_stack=list(project["tech_stack"]),
                role=project["role"],
                metrics=dict(project["metrics"]),
                raw_source_id=document_id,
            )

    def replace_resume_representation(
        self,
        session,
        *,
        user_id: str,
        text: str,
        filename: str = "resume.tex",
    ) -> IngestedDocument:
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.repository.ensure_user(session, user_id)
        existing_documents = self.repository.list_documents(
            session,
            user_id=user_id,
            source_type="resume",
            active_only=False,
            limit=None,
        )
        existing_ids = [document.id for document in existing_documents]
        if existing_ids:
            old_chunks = self.repository.list_chunks_for_documents(session, document_ids=existing_ids)
            if old_chunks:
                self._delete_chunks(session, chunks=old_chunks)
            self.repository.delete_projects_for_source_documents(session, document_ids=existing_ids)
            self.repository.delete_document_chunks(session, document_ids=existing_ids)
            self.repository.delete_documents(session, document_ids=existing_ids)

        document = self.repository.create_document(
            session,
            user_id=user_id,
            source_type="resume",
            filename=filename,
            content_hash=content_hash,
            raw_text=text,
            metadata_json={"canonical_path": "resume/resume.tex"},
        )
        chunk_count = self._create_document_chunks(
            session,
            document_id=document.id,
            user_id=user_id,
            source_type="resume",
            text=text,
            filename=filename,
            metadata={"canonical_path": "resume/resume.tex"},
        )
        self.persist_resume_side_effects(session, user_id=user_id, document_id=document.id, text=text)
        return IngestedDocument(
            document_id=document.id,
            chunk_count=chunk_count,
            content_hash=content_hash,
            raw_text=text,
        )

    def persist_jd_side_effects(
        self,
        session,
        *,
        user_id: str,
        document_id: str,
        text: str,
        company: str | None,
        role: str | None,
        url: str | None,
        job_description: str | None,
        job_requirements: str | None,
    ):
        requirements = extract_jd_requirements(text)
        jd = self.repository.create_target_jd(
            session,
            user_id=user_id,
            document_id=document_id,
            company=company,
            role=role,
            url=url,
            job_description=job_description,
            job_requirements=job_requirements,
            raw_text=text,
            structured_requirements=requirements,
        )
        self.repository.upsert_user_profile(
            session,
            user_id=user_id,
            target_roles=[role] if role else None,
            target_companies=[company] if company else None,
        )
        return jd


class QuestionIngestionService:
    def __init__(
        self,
        *,
        settings: AppSettings,
        repository: InterviewRepository,
        vector_store: ChromaVectorStore,
        provider: OpenAICompatibleProvider,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.vector_store = vector_store
        self.provider = provider
        self.extractor = TextExtractor()

    def ingest_questions(
        self,
        session,
        *,
        user_id: str,
        text: str | None,
        content_base64: str | None,
        filename: str | None,
        metadata: dict[str, Any],
        source_company: str | None,
        source_role: str | None,
    ) -> QuestionIngestionResult:
        extracted = self.extractor.extract(text=text, content_base64=content_base64, filename=filename)
        content_hash = hashlib.sha256(extracted.text.encode("utf-8")).hexdigest()
        self.repository.ensure_user(session, user_id)
        document = self.repository.create_document(
            session,
            user_id=user_id,
            source_type="question",
            filename=extracted.filename,
            content_hash=content_hash,
            raw_text=extracted.text,
            metadata_json=metadata,
        )
        candidates, fallback_used = self._extract_structured_questions(
            extracted.text,
            fallback_company=source_company,
            fallback_role=source_role,
        )
        source_scope = self._resolve_source_scope(
            metadata=metadata,
            source_company=source_company,
            source_role=source_role,
            candidates=candidates,
        )
        document_metadata = {**metadata}
        if source_scope:
            document_metadata["source_scope"] = source_scope
            self.repository.update_document_metadata(
                session,
                document_id=document.id,
                metadata_json=document_metadata,
            )

        inactive_count = 0
        if source_scope:
            deactivated_document_ids = self.repository.deactivate_documents(
                session,
                user_id=user_id,
                source_type="question",
                metadata=document_metadata,
                superseded_by=document.id,
                exclude_document_id=document.id,
            )
            if deactivated_document_ids:
                old_chunks = self.repository.list_chunks_for_documents(
                    session,
                    document_ids=deactivated_document_ids,
                )
                if old_chunks:
                    self._mark_chunks_inactive(session, chunks=old_chunks)

        base_chunks = split_text(
            extracted.text,
            chunk_size=self.settings.text_chunk_size,
            chunk_overlap=self.settings.text_chunk_overlap,
        )
        base_vector_ids: list[str] = []
        base_texts: list[str] = []
        base_metas: list[dict[str, Any]] = []
        for index, chunk_text in enumerate(base_chunks):
            chunk = self.repository.create_document_chunk(
                session,
                document_id=document.id,
                user_id=user_id,
                source_type="question",
                chunk_index=index,
                text=chunk_text,
                metadata_json={
                    "chunk_kind": "document",
                    "source_scope": source_scope,
                    **metadata,
                },
                vector_collection="interview_chunks",
                vector_id=None,
            )
            chunk.vector_id = chunk.id
            base_vector_ids.append(chunk.id)
            base_texts.append(chunk_text)
            base_metas.append(
                {
                    "user_id": user_id,
                    "source_type": "question",
                    "document_id": document.id,
                    "chunk_id": chunk.id,
                    "question_id": "",
                    "dimension": "",
                    "topics_text": "",
                    "is_active": True,
                }
            )
            self._sync_chunk_fts(session, chunk=chunk)
        if base_texts:
            self.vector_store.upsert(
                collection_name="interview_chunks",
                ids=base_vector_ids,
                texts=base_texts,
                metadatas=base_metas,
            )

        existing_questions = (
            self.repository.list_questions_for_scope(
                session,
                user_id=user_id,
                source_scope=source_scope,
                active_only=True,
            )
            if source_scope
            else []
        )
        existing_by_fingerprint = {
            item.question_fingerprint: item
            for item in existing_questions
            if item.question_fingerprint
        }
        pending_existing = {
            item.id: item
            for item in existing_questions
        }

        seen_normalized: set[str] = set()
        processed: list[dict[str, Any]] = []
        skipped_count = 0
        vector_ids: list[str] = []
        texts: list[str] = []
        metadatas: list[dict[str, Any]] = []
        chunk_offset = len(base_chunks)

        for index, candidate in enumerate(candidates):
            normalized = normalize_text(candidate.question)
            if not normalized or normalized in seen_normalized:
                skipped_count += 1
                continue
            seen_normalized.add(normalized)
            fingerprint = _question_fingerprint(normalized)
            existing = existing_by_fingerprint.get(fingerprint) if source_scope else None
            if existing is not None:
                pending_existing.pop(existing.id, None)
                old_chunk = None
                if existing.source_chunk_id:
                    old_chunk = self.repository.get_document_chunk(session, chunk_id=existing.source_chunk_id)
                existing_block = normalize_text(old_chunk.text if old_chunk is not None else existing.text)
                if existing_block == normalize_text(candidate.block_text):
                    skipped_count += 1
                    continue

            mastery_level, gaps, next_probe = evaluate_answer(
                question=candidate.question,
                answer=candidate.answer,
                topics=candidate.topics,
                dimension=candidate.dimension,
            )
            question_chunk = self.repository.create_document_chunk(
                session,
                document_id=document.id,
                user_id=user_id,
                source_type="question",
                chunk_index=chunk_offset + index,
                text=candidate.block_text,
                metadata_json={
                    "chunk_kind": "question_block",
                    "source_company": candidate.source_company,
                    "source_role": candidate.source_role,
                    "source_scope": source_scope,
                    "dimension": candidate.dimension,
                    "topics": candidate.topics,
                    "topics_text": ",".join(candidate.topics),
                    "question_id": "",
                },
                vector_collection="question_bank",
                vector_id=None,
            )
            question = self.repository.create_question(
                session,
                user_id=user_id,
                document_id=document.id,
                source_chunk_id=question_chunk.id,
                text=candidate.question,
                source_company=candidate.source_company,
                source_role=candidate.source_role,
                dimension=candidate.dimension,
                topics=candidate.topics,
                reference_answer=candidate.reference_answer,
                normalized_text=normalized,
                question_fingerprint=fingerprint,
                source_scope=source_scope,
            )
            question_chunk.vector_id = question.id
            question_chunk.metadata_json = {
                **question_chunk.metadata_json,
                "question_id": question.id,
            }
            record = self.repository.create_answer_record(
                session,
                question_id=question.id,
                user_id=user_id,
                user_answer=candidate.answer,
                mastery_level=mastery_level,
                gaps=gaps,
                next_probe=next_probe,
            )
            self.repository.update_question_mastery(
                session,
                question_id=question.id,
                mastery_level=mastery_level,
            )
            if existing is not None:
                self._mark_question_inactive(session, question=existing, superseded_by=question.id)
                inactive_count += 1

            self._sync_chunk_fts(session, chunk=question_chunk)
            self.repository.update_retrieval_fts(
                session,
                item_id=question.id,
                item_type="question",
                searchable_text=build_question_searchable_text(question),
                is_active=True,
                user_id=user_id,
                source_scope=source_scope,
                source_type="question",
                dimension=candidate.dimension,
            )
            vector_ids.append(question.id)
            texts.append(self._question_bank_text(question))
            metadatas.append(
                {
                    "user_id": user_id,
                    "source_type": "question",
                    "document_id": document.id,
                    "chunk_id": question_chunk.id,
                    "question_id": question.id,
                    "dimension": candidate.dimension,
                    "topics_text": ",".join(candidate.topics),
                    "is_active": True,
                }
            )
            processed.append(
                {
                    "question_id": question.id,
                    "question": candidate.question,
                    "user_answer": candidate.answer,
                    "reference_answer": candidate.reference_answer,
                    "dimension": candidate.dimension,
                    "topics": candidate.topics,
                    "mastery_level": mastery_level,
                    "gaps": gaps,
                    "next_probe": next_probe,
                    "record_id": record.id,
                }
            )

        for stale in pending_existing.values():
            self._mark_question_inactive(session, question=stale, superseded_by=None)
            inactive_count += 1

        if texts:
            self.vector_store.upsert(
                collection_name="question_bank",
                ids=vector_ids,
                texts=texts,
                metadatas=metadatas,
            )

        return QuestionIngestionResult(
            ingested_document=IngestedDocument(
                document_id=document.id,
                chunk_count=len(base_chunks) + len(processed),
                content_hash=content_hash,
                raw_text=extracted.text,
            ),
            records=processed,
            processed_count=len(candidates),
            skipped_count=skipped_count,
            inactive_count=inactive_count,
            fallback_used=fallback_used,
        )

    def _question_bank_text(self, question) -> str:
        return f"{question.text}\n参考答案：{question.reference_answer}"

    def _sync_chunk_fts(self, session, *, chunk) -> None:
        metadata = chunk.metadata_json or {}
        self.repository.update_retrieval_fts(
            session,
            item_id=chunk.id,
            item_type="chunk",
            searchable_text=build_chunk_searchable_text(chunk),
            is_active=True,
            user_id=chunk.user_id,
            source_scope=str(metadata.get("source_scope") or "") or None,
            source_type=chunk.source_type,
            dimension=str(metadata.get("dimension") or "") or None,
        )

    def _mark_chunks_inactive(self, session, *, chunks: list[Any]) -> None:
        grouped: dict[str, list[Any]] = {}
        for chunk in chunks:
            grouped.setdefault(chunk.vector_collection, []).append(chunk)
            self.repository.delete_retrieval_fts(session, item_id=chunk.id)

        for collection_name, items in grouped.items():
            self.vector_store.upsert(
                collection_name=collection_name,
                ids=[chunk.vector_id or chunk.id for chunk in items],
                texts=[chunk.text for chunk in items],
                metadatas=[
                    {
                        "user_id": chunk.user_id,
                        "source_type": chunk.source_type,
                        "document_id": chunk.document_id,
                        "chunk_id": chunk.id,
                        "question_id": str(chunk.metadata_json.get("question_id", "")),
                        "dimension": str(chunk.metadata_json.get("dimension", "")),
                        "topics_text": str(chunk.metadata_json.get("topics_text", "")),
                        "is_active": False,
                    }
                    for chunk in items
                ],
            )

    def _mark_question_inactive(self, session, *, question, superseded_by: str | None) -> None:
        self.repository.deactivate_question(
            session,
            question_id=question.id,
            superseded_by=superseded_by,
        )
        self.repository.delete_retrieval_fts(session, item_id=question.id)
        self.vector_store.upsert(
            collection_name="question_bank",
            ids=[question.id],
            texts=[self._question_bank_text(question)],
            metadatas=[
                {
                    "user_id": question.user_id,
                    "source_type": "question",
                    "document_id": question.document_id or "",
                    "chunk_id": question.source_chunk_id or "",
                    "question_id": question.id,
                    "dimension": question.dimension,
                    "topics_text": ",".join(question.topics),
                    "is_active": False,
                }
            ],
        )

    def _extract_structured_questions(
        self,
        raw_text: str,
        *,
        fallback_company: str | None,
        fallback_role: str | None,
    ) -> tuple[list[QuestionCandidate], bool]:
        if self.provider.has_real_chat():
            try:
                response = self.provider.chat(
                    system_prompt=(
                        "你是面试题库结构化助手。"
                        "把用户提供的中文面经/题库文本提取成 JSON。"
                        "输出格式必须是一个 JSON 对象，包含 questions 数组。"
                    ),
                    user_prompt=(
                        "请提取所有题目，字段只保留：question, answer, source_company, source_role, "
                        "dimension, topics, reference_answer。\n"
                        f"默认 source_company={fallback_company or ''}\n"
                        f"默认 source_role={fallback_role or ''}\n"
                        "如果原文没有答案，answer 置为空字符串。"
                        "topics 必须是字符串数组。\n"
                        f"原文如下：\n{raw_text}"
                    ),
                )
                payload = self._extract_json_payload(response)
                llm_candidates = self._build_candidates_from_payload(
                    payload.get("questions", []),
                    fallback_company=fallback_company,
                    fallback_role=fallback_role,
                )
                if llm_candidates:
                    return llm_candidates, False
            except Exception:
                pass
        return self._build_candidates_from_parser(
            raw_text,
            fallback_company=fallback_company,
            fallback_role=fallback_role,
        ), True

    def _build_candidates_from_payload(
        self,
        items: list[dict[str, Any]],
        *,
        fallback_company: str | None,
        fallback_role: str | None,
    ) -> list[QuestionCandidate]:
        candidates: list[QuestionCandidate] = []
        for item in items:
            question = str(item.get("question", "")).strip()
            if not question:
                continue
            answer = str(item.get("answer", "")).strip()
            topics = self._coerce_topics(item.get("topics"), question)
            dimension = self._coerce_dimension(item.get("dimension"), question, topics)
            reference_answer = self._coerce_reference_answer(
                item.get("reference_answer"),
                question,
                topics,
                dimension,
            )
            candidates.append(
                QuestionCandidate(
                    question=question,
                    answer=answer,
                    source_company=str(item.get("source_company") or fallback_company or "").strip() or None,
                    source_role=str(item.get("source_role") or fallback_role or "").strip() or None,
                    dimension=dimension,
                    topics=topics,
                    reference_answer=reference_answer,
                    block_text=self._build_block_text(question, answer),
                )
            )
        return candidates

    def _build_candidates_from_parser(
        self,
        raw_text: str,
        *,
        fallback_company: str | None,
        fallback_role: str | None,
    ) -> list[QuestionCandidate]:
        parsed_questions = parse_question_batch(
            raw_text,
            fallback_company=fallback_company,
            fallback_role=fallback_role,
        )
        candidates: list[QuestionCandidate] = []
        for item in parsed_questions:
            topics = infer_topics(item.question)
            dimension = infer_dimension(item.question, topics)
            candidates.append(
                QuestionCandidate(
                    question=item.question,
                    answer=item.answer,
                    source_company=item.source_company,
                    source_role=item.source_role,
                    dimension=dimension,
                    topics=topics,
                    reference_answer=build_reference_answer(item.question, topics, dimension),
                    block_text=item.block_text,
                )
            )
        return candidates

    def _resolve_source_scope(
        self,
        *,
        metadata: dict[str, Any],
        source_company: str | None,
        source_role: str | None,
        candidates: list[QuestionCandidate],
    ) -> str | None:
        source_key = str(metadata.get("source_key", "")).strip()
        if source_key:
            return source_key
        company = source_company
        role = source_role
        if candidates:
            company = candidates[0].source_company or company
            role = candidates[0].source_role or role
        if not company and not role:
            return None
        return f"{company or ''}::{role or ''}"

    def _extract_json_payload(self, content: str) -> dict[str, Any]:
        normalized = content.strip()
        if normalized.startswith("```"):
            normalized = normalized.strip("`")
            if "\n" in normalized:
                normalized = normalized.split("\n", 1)[1]
        try:
            payload = json.loads(normalized)
        except json.JSONDecodeError:
            start = normalized.find("{")
            end = normalized.rfind("}")
            if start < 0 or end < 0 or end <= start:
                raise
            payload = json.loads(normalized[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("Expected JSON object payload.")
        return payload

    def _coerce_topics(self, raw_topics: Any, question: str) -> list[str]:
        if isinstance(raw_topics, list):
            topics = [str(item).strip() for item in raw_topics if str(item).strip()]
            if topics:
                return topics
        return infer_topics(question)

    def _coerce_dimension(self, raw_dimension: Any, question: str, topics: list[str]) -> str:
        dimension = str(raw_dimension or "").strip()
        return dimension or infer_dimension(question, topics)

    def _coerce_reference_answer(
        self,
        raw_reference: Any,
        question: str,
        topics: list[str],
        dimension: str,
    ) -> str:
        reference = str(raw_reference or "").strip()
        return reference or build_reference_answer(question, topics, dimension)

    def _build_block_text(self, question: str, answer: str) -> str:
        if not answer:
            return question
        return f"{question}\n我的答案：{answer}"
