from datetime import datetime, timedelta, timezone
import json
import re
from types import SimpleNamespace
from typing import Annotated, Literal
import unicodedata
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.auth.dependencies import require_role
from app.db.session import get_db
from app.models.certificate_export import CertificateExport, CertificateExportRecipient
from app.models.dataset import Dataset, DatasetParticipant
from app.models.participant import Participant
from app.models.user import Role, User
from app.services import certificates

router = APIRouter(prefix="/api/certificates/exports", tags=["certificate exports"])
Admin = Annotated[User, Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN))]
Database = Annotated[Session, Depends(get_db)]
MAX_RECIPIENTS = 5000
MAX_PDF_BYTES = 3 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
EXPORT_HOURS = 2


class ExportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    selection: Literal["selected", "all"]
    dataset_id: int | None = Field(default=None, ge=1)
    participant_ids: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list, max_length=MAX_RECIPIENTS)
    template_id: int | None = Field(default=None, ge=1)
    expected_count: int | None = Field(default=None, ge=1, le=MAX_RECIPIENTS)

    @model_validator(mode="after")
    def selection_matches_ids(self):
        if self.selection == "selected" and not self.participant_ids:
            raise ValueError("Select at least one participant")
        if self.selection == "all" and self.participant_ids:
            raise ValueError("All selection must not include participant IDs")
        if len(set(self.participant_ids)) != len(self.participant_ids):
            raise ValueError("Participant IDs must be distinct")
        return self


def filename(name: str, participant_id: int):
    # Keep readable Unicode; strip path/control characters and add the immutable ID for uniqueness.
    safe = "".join(c for c in unicodedata.normalize("NFC", name) if not unicodedata.category(c).startswith("C"))
    safe = re.sub(r'[^\w -]', "_", safe, flags=re.UNICODE)
    safe = re.sub(r"[\s_]+", "_", safe).strip(" ._-")[:100] or "Participant"
    return f"{safe}_{participant_id}.pdf"


def manifest(db, item):
    recipients = db.scalars(select(CertificateExportRecipient).where(CertificateExportRecipient.export_id == item.id)
                           .order_by(CertificateExportRecipient.participant_id)).all()
    return {"id": item.id, "template_id": item.template_id, "template_name": item.template_snapshot["name"],
            "expires_at": item.expires_at.replace(tzinfo=timezone.utc) if item.expires_at.tzinfo is None else item.expires_at,
            "total": len(recipients), "max_pdf_bytes": MAX_PDF_BYTES,
            "recipients": [{"id": r.participant_id, "name": r.name, "filename": r.filename} for r in recipients]}


def owned_export(db, id, actor):
    item = db.scalar(select(CertificateExport).where(CertificateExport.id == str(id),
        CertificateExport.created_by == actor.id, CertificateExport.expires_at > datetime.now(timezone.utc)))
    if item is None:
        raise HTTPException(404, "Certificate export not found or expired. Start a new generation run.")
    return item


@router.post("", status_code=201)
def create_export(payload: ExportInput, response: Response, db: Database, actor: Admin):
    response.headers["Cache-Control"] = "private, no-store"
    now = datetime.now(timezone.utc)
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"certificate-export:{actor.id}"})
    # Retry of the same creation request reuses its snapshot, rather than creating another job.
    existing = db.get(CertificateExport, str(payload.request_id))
    if existing is not None:
        return manifest(db, owned_export(db, payload.request_id, actor))
    # Opportunistic expiry cleanup, with a bounded number of snapshots per creation request.
    expired = list(db.scalars(select(CertificateExport.id).where(CertificateExport.expires_at <= now).limit(50)))
    if expired:
        db.execute(delete(CertificateExportRecipient).where(CertificateExportRecipient.export_id.in_(expired)))
        db.execute(delete(CertificateExport).where(CertificateExport.id.in_(expired)))
    active = db.scalar(select(func.count()).select_from(CertificateExport).where(CertificateExport.created_by == actor.id,
                       CertificateExport.expires_at > now))
    if active >= 3:
        raise HTTPException(409, "Three exports are already open. Finish or cancel one, or wait for it to expire.")
    query = select(Participant).order_by(Participant.id)
    if payload.dataset_id is not None:
        dataset = db.get(Dataset, payload.dataset_id)
        if dataset is None:
            raise HTTPException(404, "Dataset not found")
        query = query.join(DatasetParticipant).where(DatasetParticipant.dataset_id == payload.dataset_id)
    if payload.selection == "selected":
        query = query.where(Participant.id.in_(payload.participant_ids))
    people = list(db.scalars(query.limit(MAX_RECIPIENTS + 1)))
    if payload.selection == "selected" and len(people) != len(payload.participant_ids):
        raise HTTPException(422, "A selected participant is missing or outside the chosen dataset. Reload the selection.")
    if not people or len(people) > MAX_RECIPIENTS:
        raise HTTPException(422, f"Choose between 1 and {MAX_RECIPIENTS} participants per ZIP")
    if payload.expected_count is not None and len(people) != payload.expected_count:
        raise HTTPException(409, "Participant count changed. Reload and review the selection before generating.")
    recipient_data = [{"id": p.id, "name": p.name, "filename": filename(p.name, p.id)} for p in people]
    if len(json.dumps(recipient_data, ensure_ascii=False).encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise HTTPException(422, "This selection's names exceed the export response limit. Choose fewer participants.")
    template = certificates.selected_template(db, payload.template_id)
    if not template.file_data:
        raise HTTPException(409, "The selected certificate artwork is unavailable")
    item = CertificateExport(id=str(payload.request_id), created_by=actor.id, expires_at=now + timedelta(hours=EXPORT_HOURS),
        template_id=template.id, template_snapshot=certificates.snapshot_template(template), file_data=bytes(template.file_data))
    db.add(item); db.flush()
    db.add_all([CertificateExportRecipient(export_id=item.id, participant_id=p.id, name=p.name,
        college=p.college, team_name=p.team_name, filename=filename(p.name, p.id)) for p in people])
    db.commit()
    return manifest(db, item)


@router.get("/{export_id}/participants/{participant_id}")
def export_pdf(export_id: UUID, participant_id: int, db: Database, actor: Admin):
    item = owned_export(db, export_id, actor)
    person = db.get(CertificateExportRecipient, (item.id, participant_id))
    if person is None:
        raise HTTPException(404, "Participant is not in this export")
    template = SimpleNamespace(**item.template_snapshot, file_data=item.file_data)
    try:
        pdf = certificates.render_pdf(template, person.name, person.college, person.team_name)
    except Exception:
        # Keep participant data, internal filesystem paths and provider configuration out of errors/logs.
        raise HTTPException(422, "Certificate rendering failed for this participant. Check the template and font settings.") from None
    if len(pdf) > MAX_PDF_BYTES:
        raise HTTPException(413, "This PDF exceeds the 3 MB export limit. Use a smaller certificate background.")
    return Response(pdf, media_type="application/pdf", headers={"Cache-Control": "private, no-store",
        "Content-Disposition": 'attachment; filename="certificate.pdf"', "X-Content-Type-Options": "nosniff"})


@router.delete("/{export_id}", status_code=204)
def delete_export(export_id: UUID, db: Database, actor: Admin):
    # Idempotent cleanup, including expired runs. An unknown/other admin's UUID reveals nothing.
    query = select(CertificateExport.id).where(CertificateExport.id == str(export_id), CertificateExport.created_by == actor.id)
    if db.scalar(query) is not None:
        db.execute(delete(CertificateExportRecipient).where(CertificateExportRecipient.export_id == str(export_id)))
        db.execute(delete(CertificateExport).where(CertificateExport.id == str(export_id)))
        db.commit()
