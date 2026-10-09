from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update

from app.models.generation_job import GenerationJobModel
from app.repository.base import BaseRepository


class GenerationJobRepository(BaseRepository):
    async def create(self, **fields: Any) -> GenerationJobModel:
        async with self.session_factory() as session:
            job = GenerationJobModel(**fields)
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job

    async def get(self, job_id: str) -> GenerationJobModel | None:
        async with self.session_factory() as session:
            return await session.get(GenerationJobModel, job_id)

    async def update(self, job_id: str, **fields: Any) -> GenerationJobModel | None:
        async with self.session_factory() as session:
            job = await session.get(GenerationJobModel, job_id)
            if job is None:
                return None
            for key, value in fields.items():
                setattr(job, key, value)
            await session.commit()
            await session.refresh(job)
            return job

    async def list(
        self, *, status: str | None, limit: int, offset: int
    ) -> tuple[list[GenerationJobModel], int]:
        async with self.session_factory() as session:
            stmt = select(GenerationJobModel)
            count_stmt = select(func.count()).select_from(GenerationJobModel)
            if status is not None:
                stmt = stmt.where(GenerationJobModel.status == status)
                count_stmt = count_stmt.where(GenerationJobModel.status == status)
            rows, total = await self._execute_paginated(
                session,
                stmt,
                count_stmt,
                sort_column=GenerationJobModel.created_at,
                sort_desc=True,
                limit=limit,
                offset=offset,
            )
            return list(rows), total or 0

    async def delete(self, job_id: str) -> bool:
        async with self.session_factory() as session:
            job = await session.get(GenerationJobModel, job_id)
            if job is None:
                return False
            await session.delete(job)
            await session.commit()
            return True

    async def list_expired(self, now: datetime) -> list[GenerationJobModel]:
        """Succeeded jobs whose artifacts are past their expiry (metadata rows are kept)."""
        async with self.session_factory() as session:
            rows = await session.execute(
                select(GenerationJobModel).where(
                    GenerationJobModel.status == "succeeded",
                    GenerationJobModel.expires_at.is_not(None),
                    GenerationJobModel.expires_at <= now,
                )
            )
            return [j for j in rows.scalars().all() if j.artifacts]

    async def fail_orphans(self, error: dict) -> int:
        """Jobs left queued/running by a previous process can never finish; mark them failed."""
        async with self.session_factory() as session:
            result = await session.execute(
                update(GenerationJobModel)
                .where(GenerationJobModel.status.in_(("queued", "running")))
                .values(status="failed", error=error, finished_at=datetime.now(UTC))
            )
            await session.commit()
            return result.rowcount or 0
