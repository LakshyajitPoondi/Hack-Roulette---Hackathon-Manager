"""Synchronous campaign work for explicit admin requests."""
import logging
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from app.models.certificate import CertificateTemplate
from app.models.email import EmailCampaign, EmailDelivery
from app.models.participant import Participant
from app.services.certificates import render_pdf
from app.services.email_campaigns import refresh_status, sent_keys, utcnow
from app.services.email_delivery import filename, provider, render

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
SEND_BATCH_SIZE = 10


def process_campaign(db: Session, campaign_id: int, limit: int) -> int:
    """Lock one delivery through its provider call, so overlapping invocations skip it."""
    processed = 0
    for _ in range(limit):
        delivery = db.scalar(
            select(EmailDelivery)
            .join(EmailCampaign)
            .options(selectinload(EmailDelivery.campaign))
            .where(EmailDelivery.campaign_id == campaign_id,
                   EmailDelivery.status == "PENDING",
                   EmailCampaign.status == "PROCESSING")
            .order_by(EmailDelivery.id)
            .with_for_update(of=EmailDelivery, skip_locked=True)
            .limit(1)
        )
        if delivery is None:
            db.rollback()
            break
        try:
            campaign = delivery.campaign
            if db.bind.dialect.name == "postgresql":
                scope = "certificate" if campaign.attach_certificate else f"plain:{campaign.name}"
                db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                           {"key": f"{scope}:{delivery.participant_key}"})
            if not campaign.allow_resend and delivery.participant_key in sent_keys(
                    db, name=campaign.name, attach_certificate=campaign.attach_certificate,
                    exclude_delivery_id=delivery.id):
                delivery.status = "SKIPPED"
                delivery.failure_reason = "Already sent for this certificate or campaign"
                db.commit()
                processed += 1
                continue
            delivery.attempt_count += 1
            person = db.get(Participant, delivery.participant_id)
            team = person.team_name if person is not None else None
            if person is not None:
                delivery.participant_name = person.name
                delivery.college = person.college
                delivery.email = person.email
            pdf = None
            if campaign.attach_certificate:
                template = db.get(CertificateTemplate, campaign.certificate_template_id)
                if not template:
                    raise FileNotFoundError("Certificate template is missing")
                pdf = render_pdf(template, delivery.participant_name, delivery.college, team,
                                 include_college=campaign.certificate_include_college,
                                 include_team=campaign.certificate_include_team)
            values = {"participant_name": delivery.participant_name, "college_name": delivery.college or ""}
            message_id = provider().send(
                to=delivery.email, recipient_name=delivery.participant_name,
                sender_name=campaign.sender_name, reply_to=campaign.reply_to,
                subject=render(campaign.subject, values), body=render(campaign.body, values),
                attachment=pdf,
                attachment_name=filename(delivery.participant_name) if campaign.attach_certificate else None,
                idempotency_key=str(uuid.uuid5(uuid.NAMESPACE_URL, f"hackroulette-c{campaign.id}-d{delivery.id}-a{delivery.attempt_count}")),
            )
            delivery.status = "SENT"
            delivery.provider_message_id = message_id
            delivery.sent_at = utcnow()
            delivery.failed_at = None
            delivery.failure_reason = None
        except Exception as exc:
            logger.warning("Email delivery %s failed: %s", delivery.id, exc)
            delivery.status = "FAILED"
            delivery.failed_at = utcnow()
            delivery.failure_reason = str(exc)[:1000]
        db.commit()
        processed += 1
    campaign = db.get(EmailCampaign, campaign_id)
    if campaign and campaign.status == "PROCESSING":
        refresh_status(db, campaign)
    return processed
