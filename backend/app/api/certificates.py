from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session, defer

from app.auth.dependencies import require_role
from app.db.session import get_db
from app.models.certificate import CertificateTemplate
from app.models.user import Role, User
from app.schemas.certificate import CertificateRead, TemplateRead, TemplateUpdate
from app.services import certificate_fonts as fonts
from app.services import certificates as service
from app.services.db_participants import get_person
from app.models.participant import Participant

router = APIRouter(prefix="/api/certificates", tags=["certificates"])
Admin = Annotated[User, Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN))]
Database = Annotated[Session, Depends(get_db)]


@router.get("/fonts")
def font_catalog(_: Admin):
    return fonts.catalog()


# Public so the browser's font loader can fetch it without cookies; the files are open-licensed.
@router.get("/fonts/{family}/{style}")
def font_file(family: str, style: str):
    path = fonts.font_file(family, style)
    if path is None:
        raise HTTPException(404, "Font not found")
    return FileResponse(path, media_type="font/ttf", headers={"Cache-Control": "public, max-age=604800"})


@router.get("/templates", response_model=list[TemplateRead])
def templates(db: Database, _: Admin):
    return list(db.scalars(select(CertificateTemplate).options(defer(CertificateTemplate.file_data)).order_by(CertificateTemplate.id.desc())))


@router.post("/templates", response_model=TemplateRead, status_code=201)
async def upload_template(db: Database, actor: Admin, file: UploadFile = File(...), name: str = Form(...)):
    if not name.strip() or len(name.strip()) > 160:
        raise HTTPException(422, "Template name must contain 1–160 characters")
    data = await file.read(service.MAX_TEMPLATE_BYTES + 1)
    extension = service.validate_template(data)
    template = CertificateTemplate(name=name.strip(), file_data=data, file_type=extension, created_by=actor.id)
    db.add(template); db.commit(); db.refresh(template)
    return template


@router.patch("/templates/{template_id}", response_model=TemplateRead)
def update_template(template_id: int, payload: TemplateUpdate, db: Database, _: Admin):
    template = service.get_template(db, template_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, "Template settings cannot be empty")
        if key == "name" and not value.strip():
            raise HTTPException(422, "Template name is required")
        setattr(template, key, value.strip() if key == "name" else value)
    for field, label in (("name", "Participant name"), ("college", "College name"), ("team", "Team name")):
        family, bold, italic = (getattr(template, f"{field}_{key}") for key in ("font_family", "bold", "italic"))
        if not fonts.supports(family, bold, italic):
            db.rollback()
            raise HTTPException(422, f"{label}: {fonts.FAMILIES[family].label} has no {fonts.style_name(bold, italic).replace('_', ' ')} style")
    db.commit(); db.refresh(template)
    return template


@router.post("/templates/{template_id}/activate", response_model=TemplateRead)
def activate_template(template_id: int, db: Database, _: Admin):
    template = service.get_template(db, template_id)
    if not template.is_active:
        db.execute(update(CertificateTemplate).where(CertificateTemplate.is_active.is_(True)).values(is_active=False))
        template.is_active = True
        db.commit(); db.refresh(template)
    return template


@router.post("/templates/{template_id}/replace", response_model=TemplateRead)
async def replace_template(template_id: int, db: Database, _: Admin, file: UploadFile = File(...)):
    template = service.get_template(db, template_id)
    data = await file.read(service.MAX_TEMPLATE_BYTES + 1)
    template.file_type = service.validate_template(data)
    template.file_data = data
    db.commit(); db.refresh(template)
    return template


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: int, db: Database, _: Admin):
    template = service.get_template(db, template_id)
    if template.is_active:
        raise HTTPException(409, "Activate another template before deleting this one")
    db.delete(template); db.commit()


@router.get("/templates/{template_id}/preview")
def preview_template(template_id: int, db: Database, _: Admin):
    pdf = service.render_pdf(service.get_template(db, template_id), "ALEX JOHNSON", "EXAMPLE COLLEGE", "TEAM NOVA")
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="certificate-preview.pdf"'})


@router.get("/templates/{template_id}/file")
def template_file(template_id: int, db: Database, _: Admin):
    template = service.get_template(db, template_id)
    if template.file_data is None:
        raise HTTPException(503, "Template file is unavailable; upload or replace the template")
    return Response(bytes(template.file_data), media_type={"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg"}[template.file_type])


class ManualCertificate(BaseModel):
    participant_name: str = Field(min_length=1, max_length=160)
    college_name: str = Field(default="", max_length=160)
    team_name: str = Field(default="", max_length=160)


@router.post("/manual")
def manual_certificate(payload: ManualCertificate, db: Database, _: Admin, download: bool = False):
    pdf = service.render_pdf(service.active_template(db), payload.participant_name.strip(), payload.college_name.strip(),
                             payload.team_name.strip())
    disposition = "attachment" if download else "inline"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'{disposition}; filename="certificate.pdf"'})


def certificate_row(person, template: CertificateTemplate | None) -> dict:
    return {"participant_id": person.id, "participant_name": person.name, "college_name": person.college,
            "team_name": person.team_name, "eligible": True,
            "status": "READY" if template else "NO_TEMPLATE", "template_name": template.name if template else None}


@router.get("")
def list_certificates(db: Database, _: Admin, eligible: bool | None = None,
                      page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100)):
    people = list(db.scalars(select(Participant).order_by(Participant.name, Participant.id)))
    template = db.scalar(select(CertificateTemplate).where(CertificateTemplate.is_active.is_(True)))
    start = (page - 1) * page_size
    return {"items": [certificate_row(person, template) for person in people[start:start + page_size]],
            "total": len(people), "page": page, "page_size": page_size}


@router.get("/participants/{participant_id}", response_model=CertificateRead)
def participant_certificate(participant_id: int, db: Database, _: Admin):
    person = get_person(db, participant_id)
    template = db.scalar(select(CertificateTemplate).where(CertificateTemplate.is_active.is_(True)))
    return certificate_row(person, template)


@router.get("/participants/{participant_id}/download")
def download_certificate(participant_id: int, db: Database, _: Admin, download: bool = False):
    person = get_person(db, participant_id)
    data = service.render_pdf(service.active_template(db), person.name, person.college, person.team_name)
    disposition = "attachment" if download else "inline"
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disposition}; filename="certificate-{participant_id}.pdf"'})
