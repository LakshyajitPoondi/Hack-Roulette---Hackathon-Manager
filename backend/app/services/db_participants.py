from math import ceil

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.participant import Participant
from app.models.dataset import DatasetParticipant


def list_people(db: Session, search: str = "", sort_by: str = "name", sort_dir: str = "asc", page: int = 1, page_size: int = 50, dataset_id: int | None = None):
    statement = select(Participant)
    if dataset_id is not None:
        statement = statement.join(DatasetParticipant).where(DatasetParticipant.dataset_id == dataset_id)
    if search.strip():
        pattern = f"%{search.strip()}%"
        statement = statement.where(or_(Participant.name.ilike(pattern), Participant.email.ilike(pattern),
                                        Participant.team_name.ilike(pattern), Participant.college.ilike(pattern)))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    column = {"name": Participant.name, "email": Participant.email, "team_name": Participant.team_name,
              "college": Participant.college, "created_at": Participant.created_at}[sort_by]
    direction = column.desc() if sort_dir == "desc" else column.asc()
    items = list(db.scalars(statement.order_by(direction, Participant.id).offset((page - 1) * page_size).limit(page_size)))
    return {"source": "csv", "items": items, "page": page, "page_size": page_size, "total": total, "total_pages": ceil(total / page_size)}


def get_person(db: Session, participant_id: int) -> Participant:
    person = db.get(Participant, participant_id)
    if person is None:
        raise HTTPException(404, "Participant not found")
    return person
