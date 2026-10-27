from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def now():
    return datetime.now(timezone.utc)


class EmailTemplate(Base):
    __tablename__ = "email_templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class EmailCampaign(Base):
    __tablename__ = "email_campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email_template_id: Mapped[int | None] = mapped_column(ForeignKey("email_templates.id", ondelete="SET NULL"))
    certificate_template_id: Mapped[int | None] = mapped_column(ForeignKey("certificate_templates.id", ondelete="SET NULL"))
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"))
    certificate_snapshot: Mapped[dict | None] = mapped_column(JSON)
    certificate_file_data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    sender_name: Mapped[str] = mapped_column(String(160), nullable=False)
    reply_to: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attach_certificate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_resend: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Snapshot of the template's include settings, so every batch of one campaign matches.
    certificate_include_college: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    certificate_include_team: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creator = relationship("User")
    email_template = relationship("EmailTemplate")
    deliveries = relationship("EmailDelivery", back_populates="campaign", cascade="all, delete-orphan")


class EmailDelivery(Base):
    __tablename__ = "email_deliveries"
    __table_args__ = (UniqueConstraint("campaign_id", "participant_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("email_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    participant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    participant_key: Mapped[str] = mapped_column(String(320), nullable=False)
    participant_name: Mapped[str] = mapped_column(String(160), nullable=False)
    college: Mapped[str | None] = mapped_column(String(160))
    team_name: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    campaign = relationship("EmailCampaign", back_populates="deliveries")
