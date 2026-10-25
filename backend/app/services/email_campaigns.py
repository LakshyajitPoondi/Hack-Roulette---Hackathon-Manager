from datetime import datetime, timezone
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.email import EmailCampaign, EmailDelivery
from app.models.participant import Participant, identity_part


def utcnow():
    return datetime.now(timezone.utc)


def sent_keys(db: Session, *, name: str, attach_certificate: bool, exclude_delivery_id: int | None = None) -> set[str]:
    query = (select(EmailDelivery.participant_key).join(EmailCampaign)
             .where(EmailDelivery.status == "SENT", EmailCampaign.attach_certificate == attach_certificate))
    if not attach_certificate:
        query = query.where(EmailCampaign.name == name.strip())
    if exclude_delivery_id is not None:
        query = query.where(EmailDelivery.id != exclude_delivery_id)
    return set(db.scalars(query))


ALREADY_SENT = "Already sent for this certificate or campaign"
AMBIGUOUS_HISTORY = ("An older send to this shared email cannot be matched to one participant; "
                     "not sent automatically to avoid a possible duplicate.")
PARTICIPANT_KEY = "participant:"


def send_history(db: Session, people: list[Participant], *, name: str, attach_certificate: bool,
                 exclude_delivery_id: int | None = None) -> tuple[set[int], set[int]]:
    """Return (IDs already sent, IDs whose older history is ambiguous) for these participants.

    New deliveries are keyed 'participant:<id>'. Older ones are keyed by email only; they count for the
    email's only holder, or for the holder whose name matches the name recorded on the delivery. If the
    email is now shared and no holder's name matches, every holder is reported as ambiguous.
    """
    query = (select(EmailDelivery.participant_key, EmailDelivery.participant_name).join(EmailCampaign)
             .where(EmailDelivery.status == "SENT", EmailCampaign.attach_certificate == attach_certificate))
    if not attach_certificate:
        query = query.where(EmailCampaign.name == name.strip())
    if exclude_delivery_id is not None:
        query = query.where(EmailDelivery.id != exclude_delivery_id)
    sent_ids, legacy = set(), {}
    for key, recorded_name in db.execute(query):
        if key.startswith(PARTICIPANT_KEY):
            sent_ids.add(int(key.removeprefix(PARTICIPANT_KEY)))
        else:
            legacy.setdefault(identity_part(key), set()).add(identity_part(recorded_name))
    sent, ambiguous = {person.id for person in people if person.id in sent_ids}, set()
    emails = {identity_part(person.email) for person in people if person.id not in sent} & legacy.keys()
    if emails:
        holders: dict[str, list[Participant]] = {}
        for holder in db.scalars(select(Participant).where(func.lower(func.trim(Participant.email)).in_(emails))):
            holders.setdefault(identity_part(holder.email), []).append(holder)
        for person in people:
            email = identity_part(person.email)
            if person.id in sent or email not in emails:
                continue
            sharing = holders.get(email) or [person]
            if len(sharing) == 1 or identity_part(person.name) in legacy[email]:
                sent.add(person.id)
            elif not any(identity_part(other.name) in legacy[email] for other in sharing):
                ambiguous.add(person.id)
    return sent, ambiguous


def recipients(db: Session, *, selection: str, participant_ids: list[int] | None,
               college: str | None, attendance: str | None, name: str = "Tech Roulette certificates",
               attach_certificate: bool = True, resend: bool = False,
               send_to: str = "unsent", **_) -> tuple[list[Participant], list[int]]:
    """Return (recipients, IDs left out because older shared-email history is ambiguous)."""
    people = list(db.scalars(select(Participant).order_by(Participant.id)))
    if selection == "selected":
        ids = set(participant_ids or []); people = [p for p in people if p.id in ids]
    elif selection == "filtered":
        if college: people = [p for p in people if p.college == college]
    ambiguous: set[int] = set()
    if send_to == "unsent" or not resend:
        sent, ambiguous = send_history(db, people, name=name, attach_certificate=attach_certificate)
        people = [p for p in people if p.id not in sent and p.id not in ambiguous]
    return people, sorted(ambiguous)


def classify(db: Session, people: list[Participant]):
    ready, invalid = [], []
    for person in people:
        try: validate_email(person.email, check_deliverability=False)
        except (EmailNotValidError, TypeError): invalid.append(person.id); continue
        ready.append(person)
    return {"total_selected": len(people), "invalid_emails": len(invalid),
            "recipients_ready": len(ready), "ready": ready, "invalid_ids": invalid}


def campaign_data(campaign: EmailCampaign):
    deliveries = campaign.deliveries
    return {"id": campaign.id, "name": campaign.name, "email_template_id": campaign.email_template_id,
            "email_template_name": campaign.email_template.name if campaign.email_template else None,
            "certificate_template_id": campaign.certificate_template_id, "sender_name": campaign.sender_name,
            "reply_to": campaign.reply_to, "subject": campaign.subject, "body": campaign.body,
            "attach_certificate": campaign.attach_certificate, "allow_resend": campaign.allow_resend,
            "status": campaign.status,
            "created_by": campaign.created_by,
            "created_by_name": campaign.creator.name, "created_at": campaign.created_at,
            "started_at": campaign.started_at, "completed_at": campaign.completed_at,
            "recipient_count": len(deliveries), "sent_count": sum(d.status == "SENT" for d in deliveries),
            "failed_count": sum(d.status == "FAILED" for d in deliveries),
            "skipped_count": sum(d.status == "SKIPPED" for d in deliveries)}


def refresh_status(db: Session, campaign: EmailCampaign):
    locked = db.scalar(select(EmailCampaign).where(EmailCampaign.id == campaign.id).with_for_update())
    statuses = list(db.scalars(select(EmailDelivery.status).where(EmailDelivery.campaign_id == campaign.id)))
    if not statuses or any(s == "PENDING" for s in statuses): return
    sent = statuses.count("SENT")
    locked.status = "COMPLETED" if all(s in {"SENT", "SKIPPED"} for s in statuses) else "PARTIALLY_FAILED" if sent else "FAILED"
    locked.completed_at = utcnow(); db.commit()
