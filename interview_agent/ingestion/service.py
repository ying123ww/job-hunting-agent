from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from interview_agent.app.config import AppSettings
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
from interview_agent.storage.repositories import InterviewRepository
from interview_agent.storage.vector_store import ChromaVectorStore


@dataclass(slots=True)
class IngestedDocument:
    document_id: str
    chunk_count: int
    content_hash: str
    raw_text: str


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
                self.vector_store.upsert(
                    collection_name="interview_chunks",
                    ids=[chunk.vector_id or chunk.id for chunk in old_chunks],
                    texts=[chunk.text for chunk in old_chunks],
                    metadatas=[
                        {
                            "user_id": user_id,
                            "source_type": chunk.source_type,
                            "document_id": chunk.document_id,
                            "chunk_id": chunk.id,
                            "question_id": "",
                            "dimension": str(chunk.metadata_json.get("dimension", "")),
                            "topics_text": str(chunk.metadata_json.get("topics_text", "")),
                            "is_active": False,
                        }
                        for chunk in old_chunks
                    ],
                )
        chunks = split_text(
            extracted.text,
            chunk_size=self.settings.text_chunk_size,
            chunk_overlap=self.settings.text_chunk_overlap,
        )
        vector_ids: list[str] = []
        texts: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for index, chunk_text in enumerate(chunks):
            metadata_json = {
                **metadata,
                "filename": extracted.filename,
                "chunk_kind": "document",
            }
            chunk = self.repository.create_document_chunk(
                session,
                document_id=document.id,
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
                    "document_id": document.id,
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
        return IngestedDocument(
            document_id=document.id,
            chunk_count=len(chunks),
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

    def persist_jd_side_effects(
        self,
        session,
        *,
        user_id: str,
        document_id: str,
        text: str,
        company: str | None,
        role: str | None,
    ):
        requirements = extract_jd_requirements(text)
        jd = self.repository.create_target_jd(
            session,
            user_id=user_id,
            document_id=document_id,
            company=company,
            role=role,
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
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.vector_store = vector_store
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
    ) -> tuple[IngestedDocument, list[dict[str, Any]], int]:
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
                metadata_json={"chunk_kind": "document", **metadata},
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
        if base_texts:
            self.vector_store.upsert(
                collection_name="interview_chunks",
                ids=base_vector_ids,
                texts=base_texts,
                metadatas=base_metas,
            )

        parsed_questions = parse_question_batch(
            extracted.text,
            fallback_company=source_company,
            fallback_role=source_role,
        )
        seen: set[str] = set()
        processed: list[dict[str, Any]] = []
        vector_ids: list[str] = []
        texts: list[str] = []
        metadatas: list[dict[str, Any]] = []
        chunk_offset = len(base_chunks)

        for index, item in enumerate(parsed_questions):
            normalized = normalize_text(item.question)
            if normalized in seen:
                continue
            seen.add(normalized)
            topics = infer_topics(item.question)
            dimension = infer_dimension(item.question, topics)
            reference_answer = build_reference_answer(item.question, topics, dimension)
            mastery_level, gaps, next_probe = evaluate_answer(
                question=item.question,
                answer=item.answer,
                topics=topics,
                dimension=dimension,
            )
            question_chunk = self.repository.create_document_chunk(
                session,
                document_id=document.id,
                user_id=user_id,
                source_type="question",
                chunk_index=chunk_offset + index,
                text=item.block_text,
                metadata_json={
                    "chunk_kind": "question_block",
                    "source_company": item.source_company,
                    "source_role": item.source_role,
                    "dimension": dimension,
                    "topics": topics,
                },
                vector_collection="question_bank",
                vector_id=None,
            )
            question = self.repository.create_question(
                session,
                user_id=user_id,
                document_id=document.id,
                source_chunk_id=question_chunk.id,
                text=item.question,
                source_company=item.source_company,
                source_role=item.source_role,
                dimension=dimension,
                topics=topics,
                reference_answer=reference_answer,
            )
            question_chunk.vector_id = question.id
            record = self.repository.create_answer_record(
                session,
                question_id=question.id,
                user_id=user_id,
                user_answer=item.answer,
                mastery_level=mastery_level,
                gaps=gaps,
                next_probe=next_probe,
            )
            self.repository.update_question_mastery(
                session,
                question_id=question.id,
                mastery_level=mastery_level,
            )
            vector_ids.append(question.id)
            texts.append(f"{item.question}\n参考答案：{reference_answer}")
            metadatas.append(
                {
                    "user_id": user_id,
                    "source_type": "question",
                    "document_id": document.id,
                    "chunk_id": question_chunk.id,
                    "question_id": question.id,
                    "dimension": dimension,
                    "topics_text": ",".join(topics),
                    "is_active": True,
                }
            )
            processed.append(
                {
                    "question_id": question.id,
                    "question": item.question,
                    "dimension": dimension,
                    "topics": topics,
                    "mastery_level": mastery_level,
                    "gaps": gaps,
                    "next_probe": next_probe,
                    "record_id": record.id,
                }
            )
        if texts:
            self.vector_store.upsert(
                collection_name="question_bank",
                ids=vector_ids,
                texts=texts,
                metadatas=metadatas,
            )

        return (
            IngestedDocument(
                document_id=document.id,
                chunk_count=len(base_chunks) + len(processed),
                content_hash=content_hash,
                raw_text=extracted.text,
            ),
            processed,
            len(parsed_questions),
        )
