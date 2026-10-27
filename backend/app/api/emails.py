from typing import Annotated, Literal

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import current_user, require_role
from app.core.config import get_settings
from app.db.session import get_db
from app.models.email import EmailCampaign, EmailDelivery, EmailTemplate
from app.models.user import Role, User
from app.services.campaign_processor import MAX_ATTEMPTS, SEND_BATCH_SIZE, process_campaign
from app.services.certificates import active_template, selected_template, snapshot_template, placeholder_values, render_pdf
from app.services.template_names import validate_name
from app.models.dataset import Dataset
from app.services.db_participants import get_person
from app.services.email_campaigns import campaign_data, classify, recipients, utcnow
from app.services.email_delivery import render, provider

router = APIRouter(prefix="/api/email", tags=["email"])
Admin = Annotated[User, Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN))]
Database = Annotated[Session, Depends(get_db)]


class TemplateInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1)


class PreviewInput(TemplateInput):
    participant_id: int | None = None
    attach_certificate: bool = False
    certificate_template_id: int | None = None


class Selection(BaseModel):
    selection: Literal["all", "selected", "filtered"] = "all"
    participant_ids: list[int] | None = None
    college: str | None = None
    attendance: Literal["REGISTERED", "PRESENT", "ABSENT"] | None = None
    resend: bool = False
    send_to: Literal["all", "unsent"] = "unsent"
    name: str = "Tech Roulette certificates"
    attach_certificate: bool = True
    dataset_id: int | None = None


class CampaignInput(Selection):
    name: str = Field(min_length=1, max_length=160)
    email_template_id: int | None = None
    certificate_template_id: int | None = None
    sender_name: str = Field(min_length=1, max_length=160)
    reply_to: str | None = None
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1)
    send_mode: Literal["now"] = "now"
    confirmed: bool = False
    expected_recipients: int | None = Field(default=None, ge=1, le=5000)


class TestInput(BaseModel):
    to: str
    sender_name: str
    reply_to: str | None = None
    subject: str
    body: str
    participant_id: int | None = None
    attach_certificate: bool = True
    certificate_template_id: int | None = None


class TemplatePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    subject: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, min_length=1)


class ManualEmail(BaseModel):
    to: str
    participant_name: str = Field(min_length=1, max_length=160)
    college_name: str = Field(min_length=1, max_length=160)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1)
    attach_certificate: bool = True


@router.get("/manual/status")
def manual_status(db: Database, _: Annotated[User, Depends(current_user)]):
    from app.models.certificate import CertificateTemplate
    settings = get_settings()
    ready = db.scalar(select(CertificateTemplate.id).where(CertificateTemplate.is_active.is_(True))) is not None
    return {"template_ready": ready, "email_mode": settings.email_mode,
            "brevo_configured": settings.email_mode == "production" and bool(settings.brevo_api_key and settings.email_from)}


@router.post("/manual/send")
def manual_send(payload: ManualEmail, db: Database, _: Admin):
    settings = get_settings()
    if settings.email_mode != "production":
        raise HTTPException(503, "Email sending is in development mode. Set EMAIL_MODE=production to send through Brevo.")
    if not settings.brevo_api_key:
        raise HTTPException(503, "Brevo API key missing. Set BREVO_API_KEY.")
    if not settings.email_from:
        raise HTTPException(503, "Sender email not configured. Set EMAIL_FROM.")
    to = valid_email(payload.to)
    name, college = payload.participant_name.strip(), payload.college_name.strip()
    template = active_template(db) if payload.attach_certificate else None
    values = placeholder_values(template, name, college)
    try:
        subject = render(payload.subject, values)
        body = render(payload.body, values)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    attachment = None
    if template is not None:
        try:
            attachment = render_pdf(template, name, college)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(500, "PDF attachment generation failed") from None
    from app.services.email_delivery import filename
    try:
        message_id = provider().send(to=to, recipient_name=values["participant_name"],
                                     sender_name=settings.email_from_name, reply_to=None,
                                     subject=subject, body=body, attachment=attachment,
                                     attachment_name=filename(values["participant_name"]) if attachment else None)
    except Exception as exc:
        raise HTTPException(502, f"Brevo rejected the email: {str(exc)[:250]}") from None
    return {"recipient": to, "message_id": message_id, "status": "sent"}


def valid_email(address: str | None):
    if not address:
        return None
    try:
        return validate_email(address, check_deliverability=False).normalized
    except EmailNotValidError:
        raise HTTPException(422, "Invalid email address") from None


def preview(subject: str, body: str):
    sample = {"participant_name": "Alex Johnson", "college_name": "Example College"}
    try:
        return {"subject": render(subject, sample), "body": render(body, sample)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/mode")
def mode(_: Admin):
    return {"mode": get_settings().email_mode, "sending_enabled": get_settings().email_mode == "production"}


@router.get("/templates")
def templates(db: Database, _: Admin):
    return list(db.scalars(select(EmailTemplate).order_by(EmailTemplate.id.desc())))


@router.post("/templates", status_code=201)
def create_template(payload: TemplateInput, db: Database, actor: Admin):
    preview(payload.subject, payload.body)
    values = payload.model_dump()
    values["name"] = validate_name(db, EmailTemplate, payload.name)
    item = EmailTemplate(**values, created_by=actor.id)
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.patch("/templates/{template_id}")
def update_template(template_id: int, payload: TemplatePatch, db: Database, _: Admin):
    item = db.get(EmailTemplate, template_id)
    if not item:
        raise HTTPException(404, "Template not found")
    values = payload.model_dump(exclude_unset=True)
    if not values or any(value is None for value in values.values()):
        raise HTTPException(422, "Provide nonempty template changes")
    if "name" in values and values["name"] != item.name:
        values["name"] = validate_name(db, EmailTemplate, payload.name, template_id)
    preview(values.get("subject", item.subject), values.get("body", item.body))
    for key, value in values.items():
        setattr(item, key, value)
    db.commit(); db.refresh(item)
    return item


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: int, db: Database, _: Admin):
    item = db.get(EmailTemplate, template_id)
    if not item:
        raise HTTPException(404, "Template not found")
    db.delete(item); db.commit()


@router.post("/preview")
def preview_email(payload: PreviewInput, db: Database, _: Admin):
    if payload.participant_id is not None:
        person = get_person(db, payload.participant_id)
        template = None
        if payload.attach_certificate:
            try:
                template = selected_template(db, payload.certificate_template_id)
            except HTTPException:
                if payload.certificate_template_id is not None:
                    raise
                template = None  # No active template yet: preview the values unchanged.
        values = placeholder_values(template, person.name, person.college)
        try:
            return {"subject": render(payload.subject, values), "body": render(payload.body, values)}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    return preview(payload.subject, payload.body)


@router.post("/test")
def test_email(payload: TestInput, db: Database, _: Admin):
    to = valid_email(payload.to)
    reply = valid_email(payload.reply_to)
    rendered = preview(payload.subject, payload.body)
    attachment = attachment_name = None
    if payload.participant_id:
        from app.services.email_delivery import filename
        person = get_person(db, payload.participant_id)
        template = selected_template(db, payload.certificate_template_id) if payload.attach_certificate else None
        if template is not None:
            attachment = render_pdf(template, person.name, person.college, person.team_name)
            attachment_name = filename(person.name)
        values = placeholder_values(template, person.name, person.college)
        rendered = {"subject": render(payload.subject, values), "body": render(payload.body, values)}
    try:
        message_id = provider().send(to=to, sender_name=payload.sender_name, reply_to=reply,
                                     recipient_name=person.name if payload.participant_id else None,
                                     subject=rendered["subject"], body=rendered["body"], attachment=attachment, attachment_name=attachment_name)
    except Exception as exc:
        raise HTTPException(502, str(exc)[:300]) from None
    return {"recipient": to, "message_id": message_id, "mode": get_settings().email_mode}


@router.post("/recipients/summary")
def recipient_summary(payload: Selection, db: Database, _: Admin):
    if payload.selection == "selected" and not payload.participant_ids:
        raise HTTPException(422, "Select at least one participant")
    people, ambiguous = recipients(db, **payload.model_dump())
    result = classify(db, people)
    # The same selection with history ignored: what an explicit "send again" would reach.
    everyone, _ = recipients(db, **{**payload.model_dump(), "resend": True, "send_to": "all"})
    kept = {person.id for person in people} | set(ambiguous)
    already_sent = [{"id": p.id, "name": p.name, "email": p.email} for p in everyone if p.id not in kept]
    return {**{key: value for key, value in result.items() if key != "ready"},
            "history_ambiguous": len(ambiguous), "history_ambiguous_ids": ambiguous,
            "already_sent": already_sent, "resend_ready": classify(db, everyone)["recipients_ready"]}


@router.get("/campaigns")
def campaigns(db: Database, _: Admin):
    items = db.scalars(select(EmailCampaign).options(selectinload(EmailCampaign.deliveries), selectinload(EmailCampaign.creator), selectinload(EmailCampaign.email_template)).order_by(EmailCampaign.id.desc())).all()
    return [campaign_data(item) for item in items]


@router.get("/campaigns/{campaign_id}")
def campaign_detail(campaign_id: int, db: Database, _: Admin):
    item = db.scalar(select(EmailCampaign).options(selectinload(EmailCampaign.deliveries), selectinload(EmailCampaign.creator), selectinload(EmailCampaign.email_template)).where(EmailCampaign.id == campaign_id))
    if not item:
        raise HTTPException(404, "Campaign not found")
    return {**campaign_data(item), "deliveries": [{"id": d.id, "participant_id": d.participant_id, "participant_name": d.participant_name,
            "email": d.email, "status": d.status, "attempt_count": d.attempt_count, "provider_message_id": d.provider_message_id,
            "sent_at": d.sent_at, "failed_at": d.failed_at, "failure_reason": d.failure_reason} for d in item.deliveries]}


@router.post("/campaigns", status_code=201)
def create_campaign(payload: CampaignInput, db: Database, actor: Admin):
    if not payload.confirmed:
        raise HTTPException(422, "Confirm the recipient summary before sending")
    preview(payload.subject, payload.body)
    settings = get_settings()
    if settings.email_mode not in {"development", "production"}:
        raise HTTPException(503, "EMAIL_MODE must be development or production")
    if settings.email_mode == "production" and (not settings.brevo_api_key or not settings.email_from):
        raise HTTPException(503, "Brevo is not configured. Set BREVO_API_KEY and EMAIL_FROM.")
    reply = valid_email(payload.reply_to)
    if payload.email_template_id and not db.get(EmailTemplate, payload.email_template_id):
        raise HTTPException(404, "Email template not found")
    if payload.dataset_id is not None:
        dataset = db.get(Dataset, payload.dataset_id)
        if dataset is None or dataset.archived:
            raise HTTPException(409, "Select an available dataset")
    people, _ambiguous = recipients(db, **payload.model_dump(include={"selection", "participant_ids", "college", "attendance", "resend", "send_to", "name", "attach_certificate", "dataset_id"}))
    result = classify(db, people)
    if not result["ready"]:
        raise HTTPException(422, "No eligible recipients have a valid email address")
    if payload.expected_recipients is not None and len(result["ready"]) != payload.expected_recipients:
        raise HTTPException(409, "Recipient count changed since review. Review the send again.")
    template = selected_template(db, payload.certificate_template_id) if payload.attach_certificate else None
    item = EmailCampaign(name=payload.name.strip(), email_template_id=payload.email_template_id,
                         dataset_id=payload.dataset_id,
                         certificate_snapshot=snapshot_template(template) if template else None,
                         certificate_file_data=bytes(template.file_data) if template and template.file_data is not None else None,
                         certificate_template_id=template.id if template else None,
                         certificate_include_college=template.include_college if template else True,
                         certificate_include_team=template.include_team if template else False,
                         sender_name=payload.sender_name.strip(), reply_to=reply, subject=payload.subject,
                         body=payload.body, attach_certificate=payload.attach_certificate,
                         allow_resend=payload.resend and payload.send_to == "all",
                         status="PROCESSING", created_by=actor.id, started_at=utcnow())
    db.add(item); db.flush()
    for person in result["ready"]:
        db.add(EmailDelivery(campaign_id=item.id, participant_id=person.id, participant_key=person.participant_key,
                             participant_name=person.name, college=person.college, team_name=person.team_name, email=person.email, status="PENDING"))
    db.commit(); db.refresh(item)
    process_campaign(db, item.id, SEND_BATCH_SIZE)
    db.refresh(item)
    return {"id": item.id, "status": item.status, "recipients": len(result["ready"]), "skipped_invalid": result["invalid_emails"]}


@router.post("/campaigns/{campaign_id}/continue")
def continue_campaign(campaign_id: int, db: Database, _: Admin):
    item = db.get(EmailCampaign, campaign_id)
    if not item or item.status != "PROCESSING":
        raise HTTPException(409, "Campaign has no pending deliveries")
    processed = process_campaign(db, campaign_id, SEND_BATCH_SIZE)
    db.refresh(item)
    return {"status": item.status, "processed": processed}


@router.post("/campaigns/{campaign_id}/retry")
def retry(campaign_id: int, db: Database, _: Admin):
    item = db.scalar(select(EmailCampaign).options(selectinload(EmailCampaign.deliveries)).where(EmailCampaign.id == campaign_id))
    if not item or item.status not in {"FAILED", "PARTIALLY_FAILED"}:
        raise HTTPException(409, "Campaign has no completed failures")
    failed = [d for d in item.deliveries if d.status == "FAILED" and d.attempt_count < MAX_ATTEMPTS]
    if not failed:
        raise HTTPException(409, "No failed deliveries with attempts remaining")
    for delivery in failed:
        delivery.status = "PENDING"; delivery.failed_at = None
    item.status = "PROCESSING"; item.completed_at = None
    db.commit()
    process_campaign(db, item.id, SEND_BATCH_SIZE)
    db.refresh(item)
    return {"retried": len(failed), "status": item.status}
