from sqlalchemy import JSON, Column, DateTime, String
from sqlalchemy.sql import func

from app.core.database import Base


class GenerationJobModel(Base):
    """One generation request and its outcome. JSON columns hold the structured
    parts (spec, provenance, summary, error, artifact list) — they're always read and
    written whole, never queried into, so a separate table per part would be overhead."""

    __tablename__ = "generation_job"

    id = Column(String(36), primary_key=True)
    status = Column(String(16), nullable=False, index=True)  # queued|running|succeeded|failed
    connector = Column(String, nullable=True)
    preset = Column(String, nullable=True)

    request = Column(JSON, nullable=False)
    resolved_spec = Column(JSON, nullable=False)
    provenance = Column(JSON, nullable=True)
    summary = Column(JSON, nullable=True)
    error = Column(JSON, nullable=True)
    artifacts = Column(JSON, nullable=False, default=list)  # [{id, filename, path, size, content_type}]

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
