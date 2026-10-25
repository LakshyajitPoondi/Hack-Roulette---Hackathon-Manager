from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import current_user, require_role
from app.db.session import get_db
from app.models.participant import Participant
from app.models.user import Role, User
from app.services import csv_participants
from app.services.db_participants import get_person, list_people

router = APIRouter(prefix="/api/participants", tags=["participants"])
Database = Annotated[Session, Depends(get_db)]
Reader = Annotated[User, Depends(current_user)]
Manager = Annotated[User, Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN))]


class ParticipantEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    team_name: str | None = Field(default=None, max_length=160)
    college: str | None = Field(default=None, max_length=160)

    @field_validator("name", "team_name", "college", mode="before")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("team_name", "college", mode="after")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("email", mode="after")
    @classmethod
    def clean_email(cls, value: EmailStr) -> str:
        return str(value).casefold()


@router.get("")
def participants(db: Database, _: Reader, search: str = Query(default="", max_length=160),
                 sort_by: Literal["name", "email", "team_name", "college", "created_at"] = "name",
                 sort_dir: Literal["asc", "desc"] = "asc", page: int = Query(default=1, ge=1),
                 page_size: int = Query(default=50, ge=1, le=500)):
    return list_people(db, search, sort_by, sort_dir, page, page_size)


@router.post("", status_code=201)
def create_participant(payload: ParticipantEdit, db: Database, _: Manager):
    if db.scalar(select(Participant.id).where(Participant.email == payload.email)) is not None:
        raise HTTPException(409, "A participant with this email already exists.")
    person = Participant(**payload.model_dump())
    db.add(person)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A participant with this email already exists.") from None
    db.refresh(person)
    return person


@router.get("/all")
def all_participants(db: Database, _: Manager):
    return list(db.scalars(select(Participant).order_by(Participant.name, Participant.id)))


@router.post("/import/preview")
async def preview_import(db: Database, _: Manager, file: UploadFile = File(...)):
    data = await file.read(csv_participants.MAX_CSV_BYTES + 1)
    return csv_participants.preview(db, data)


@router.post("/import")
async def import_participants(db: Database, _: Manager, digest: str = Form(...), file: UploadFile = File(...)):
    data = await file.read(csv_participants.MAX_CSV_BYTES + 1)
    return csv_participants.import_rows(db, data, digest)


@router.delete("/clear", status_code=204)
def clear_participants(db: Database, _: Manager):
    db.execute(delete(Participant))
    db.commit()


@router.get("/{participant_id}")
def participant(participant_id: int, db: Database, _: Reader):
    return get_person(db, participant_id)


@router.patch("/{participant_id}")
def update_participant(participant_id: int, payload: ParticipantEdit, db: Database, _: Manager):
    person = get_person(db, participant_id)
    duplicate = db.scalar(select(Participant.id).where(Participant.email == payload.email, Participant.id != participant_id))
    if duplicate is not None:
        raise HTTPException(409, "Another participant already uses this email.")
    for field, value in payload.model_dump().items():
        setattr(person, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Another participant already uses this email.") from None
    db.refresh(person)
    return person


@router.delete("/{participant_id}", status_code=204)
def delete_participant(participant_id: int, db: Database, _: Manager):
    person = get_person(db, participant_id)
    db.delete(person)
    db.commit()
