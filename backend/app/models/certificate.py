from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CertificateTemplate(Base):
    __tablename__ = "certificate_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    name_x: Mapped[float] = mapped_column(nullable=False, default=50.0)
    name_y: Mapped[float] = mapped_column(nullable=False, default=50.0)
    name_font_size: Mapped[int] = mapped_column(Integer, nullable=False, default=36)
    name_alignment: Mapped[str] = mapped_column(String(10), nullable=False, default="center")
    name_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#171717")
    college_x: Mapped[float] = mapped_column(nullable=False, default=50.0)
    college_y: Mapped[float] = mapped_column(nullable=False, default=62.0)
    college_font_size: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    college_alignment: Mapped[str] = mapped_column(String(10), nullable=False, default="center")
    college_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#171717")
    team_x: Mapped[float] = mapped_column(nullable=False, default=50.0)
    team_y: Mapped[float] = mapped_column(nullable=False, default=74.0)
    team_font_size: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    team_alignment: Mapped[str] = mapped_column(String(10), nullable=False, default="center")
    team_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#171717")
    # Defaults keep the original look: Helvetica Bold name, Helvetica college and team.
    name_font_family: Mapped[str] = mapped_column(String(40), nullable=False, default="helvetica")
    name_bold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    name_italic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    college_font_family: Mapped[str] = mapped_column(String(40), nullable=False, default="helvetica")
    college_bold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    college_italic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    team_font_family: Mapped[str] = mapped_column(String(40), nullable=False, default="helvetica")
    team_bold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    team_italic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Uppercasing happens at render time; stored participant data is never changed.
    name_uppercase: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    college_uppercase: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    team_uppercase: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    include_college: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    include_team: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
