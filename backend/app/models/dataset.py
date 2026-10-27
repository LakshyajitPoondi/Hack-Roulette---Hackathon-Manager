from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    headers: Mapped[list] = mapped_column(JSON, nullable=False)
    original_rows: Mapped[list] = mapped_column(JSON, nullable=False)
    rows: Mapped[list] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_legacy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class DatasetParticipant(Base):
    __tablename__ = "dataset_participants"
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"), primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id", ondelete="CASCADE"), primary_key=True)
