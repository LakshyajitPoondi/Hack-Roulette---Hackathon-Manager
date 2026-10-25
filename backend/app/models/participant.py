from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def identity_part(value: str) -> str:
    """Duplicate-identity normalisation. Matches lower(trim(...)) in the database index."""
    return value.strip().lower()


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # Several participants may share an email; the same name and email together may not repeat.
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    team_name: Mapped[str | None] = mapped_column(String(160))
    college: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (Index("ux_participants_name_email", func.lower(func.trim(email)), func.lower(func.trim(name)), unique=True),)

    @property
    def participant_key(self) -> str:
        """Campaign delivery identity. Older deliveries used the bare email address instead."""
        return f"participant:{self.id}"

    @property
    def identity(self) -> tuple[str, str]:
        return identity_part(self.email), identity_part(self.name)
