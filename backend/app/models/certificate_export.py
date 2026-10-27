from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CertificateExport(Base):
    """Temporary, private inputs for a bulk download; never an email campaign."""
    __tablename__ = "certificate_exports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    template_id: Mapped[int] = mapped_column(Integer, nullable=False)
    template_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    file_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)


class CertificateExportRecipient(Base):
    __tablename__ = "certificate_export_recipients"
    export_id: Mapped[str] = mapped_column(ForeignKey("certificate_exports.id", ondelete="CASCADE"), primary_key=True)
    participant_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    college: Mapped[str | None] = mapped_column(String(160))
    team_name: Mapped[str | None] = mapped_column(String(160))
    filename: Mapped[str] = mapped_column(String(220), nullable=False)
