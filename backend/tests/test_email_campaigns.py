from types import SimpleNamespace
import base64
import io
import pytest
from PIL import Image

from app.models import CertificateTemplate, Role
from app.services.email_delivery import BrevoProvider, render


def png():
    output = io.BytesIO(); Image.new("RGB", (1000, 700), "white").save(output, format="PNG"); return output.getvalue()


def test_render_and_brevo(monkeypatch):
    from app.services import email_delivery
    assert render("Hello {{participant_name}} from {{college_name}}", {"participant_name": "Alex", "college_name": "EEC"}) == "Hello Alex from EEC"
    assert render("Hi [name] / {{participant_name}} from [college] / {{college_name}}", {"participant_name": "Alex", "college_name": "EEC"}) == "Hi Alex / Alex from EEC / EEC"
    with pytest.raises(ValueError, match="Unsupported placeholder"):
        render("Hi {{phone_number}}", {"participant_name": "Alex", "college_name": "EEC"})
    captured = {}
    class Response:
        is_error = False
        def json(self): return {"messageId": "provider-123"}
    monkeypatch.setattr(email_delivery, "get_settings", lambda: SimpleNamespace(brevo_api_key="key", email_from="certs@example.com", email_from_name="Tech Roulette", email_reply_to=None))
    monkeypatch.setattr(email_delivery.httpx, "post", lambda url, **kwargs: (captured.update({"url": url, **kwargs}) or Response()))
    assert BrevoProvider().send(to="test@example.com", recipient_name="Alex", sender_name="Tech Roulette", reply_to=None, subject="Certificate", body="Attached", attachment=b"%PDF-test", attachment_name="certificate.pdf", idempotency_key="delivery-1") == "provider-123"
    assert captured["url"] == "https://api.brevo.com/v3/smtp/email"
    assert captured["headers"]["api-key"] == "key"
    assert captured["json"]["to"] == [{"email": "test@example.com", "name": "Alex"}]
    assert captured["json"]["sender"] == {"name": "Tech Roulette", "email": "certs@example.com"}
    assert base64.b64decode(captured["json"]["attachment"][0]["content"]) == b"%PDF-test"


def test_send_now_generates_pdf_and_prevents_duplicate(client, db, make_user, login, fake_sheet):
    admin = make_user(Role.ADMIN, "admin@example.com"); login(admin.email)
    fake_sheet.people = [fake_sheet.make(2, "Alex Johnson", "alex@example.com", "Example College")]
    template = CertificateTemplate(name="PDF", file_data=png(), file_type="png", is_active=True, created_by=admin.id)
    db.add(template); db.commit()
    payload = {"name": "Certificates", "sender_name": "Tech Roulette", "subject": "Hi {{participant_name}}",
               "body": "For {{college_name}}", "selection": "all", "send_mode": "now", "confirmed": True}
    response = client.post("/api/email/campaigns", json=payload)
    assert response.status_code == 201, response.text
    detail = client.get(f"/api/email/campaigns/{response.json()['id']}").json()
    assert detail["status"] == "COMPLETED" and detail["deliveries"][0]["status"] == "SENT"
    assert client.post("/api/email/recipients/summary", json={"selection": "all"}).json()["recipients_ready"] == 0
    assert client.post("/api/email/recipients/summary", json={"selection": "all", "send_to": "all", "resend": True}).json()["recipients_ready"] == 1


def test_manual_email_without_attachment_needs_no_certificate_template(client, make_user, login, fake_sheet, monkeypatch):
    from app.services import campaign_processor

    admin = make_user(Role.ADMIN, "plain@example.com"); login(admin.email)
    fake_sheet.people = [fake_sheet.make(2, "Alex Johnson", "alex@example.com", "Example College")]
    sent = []

    class Provider:
        def send(self, **kwargs):
            sent.append(kwargs)
            return "provider-123"

    monkeypatch.setattr(campaign_processor, "provider", lambda: Provider())
    response = client.post("/api/email/campaigns", json={
        "name": "Plain email", "sender_name": "Tech Roulette", "subject": "Hi {{participant_name}}",
        "body": "From {{college_name}}", "selection": "all", "confirmed": True,
        "attach_certificate": False,
    })
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "COMPLETED"
    assert sent[0]["attachment"] is None
    assert sent[0]["subject"] == "Hi Alex Johnson"


def test_send_now_processes_all_recipients_and_retries_failures(client, db, make_user, login, fake_sheet, monkeypatch):
    from app.services import campaign_processor
    admin = make_user(Role.ADMIN, "admin-batch@example.com"); login(admin.email)
    fake_sheet.people = [fake_sheet.make(i, f"Participant {i}", f"p{i}@example.com") for i in range(2, 28)]
    db.add(CertificateTemplate(name="PDF", file_data=png(), file_type="png", is_active=True, created_by=admin.id)); db.commit()
    attempts = []
    class Provider:
        def send(self, **kwargs):
            assert kwargs["attachment"].startswith(b"%PDF")
            attempts.append(kwargs["to"])
            if kwargs["to"] == "p27@example.com" and attempts.count(kwargs["to"]) == 1:
                raise RuntimeError("Temporary failure")
            return "provider-123"
    monkeypatch.setattr(campaign_processor, "provider", lambda: Provider())
    payload = {"name": "Certificates", "sender_name": "Tech Roulette", "subject": "Hi {{participant_name}}",
               "body": "For {{college_name}}", "selection": "all", "send_mode": "now", "confirmed": True}
    response = client.post("/api/email/campaigns", json=payload)
    assert response.status_code == 201, response.text
    campaign_id = response.json()["id"]
    assert response.json()["status"] == "PROCESSING"
    while client.get(f"/api/email/campaigns/{campaign_id}").json()["status"] == "PROCESSING":
        continued = client.post(f"/api/email/campaigns/{campaign_id}/continue")
        assert continued.status_code == 200, continued.text
        assert continued.json()["processed"] > 0
    detail = client.get(f"/api/email/campaigns/{campaign_id}").json()
    assert detail["status"] == "PARTIALLY_FAILED"
    assert detail["sent_count"] == 25 and detail["failed_count"] == 1
    retry = client.post(f"/api/email/campaigns/{campaign_id}/retry")
    assert retry.status_code == 200, retry.text
    assert retry.json()["retried"] == 1
    detail = client.get(f"/api/email/campaigns/{campaign_id}").json()
    assert detail["status"] == "COMPLETED" and detail["sent_count"] == 26
    assert attempts.count("p2@example.com") == 1
    assert attempts.count("p27@example.com") == 2
    assert client.post(f"/api/email/campaigns/{campaign_id}/continue").status_code == 409
    assert client.post("/api/email/campaigns", json={**payload, "send_mode": "schedule"}).status_code == 422


def test_scoped_unsent_and_explicit_resend(client, make_user, login, fake_sheet, monkeypatch):
    from app.services import campaign_processor
    admin = make_user(Role.ADMIN, "scoped@example.com"); login(admin.email)
    fake_sheet.people = [fake_sheet.make(2, "Alex", "alex@example.com")]
    sent = []
    class Provider:
        def send(self, **kwargs):
            sent.append(kwargs["subject"])
            return f"message-{len(sent)}"
    monkeypatch.setattr(campaign_processor, "provider", lambda: Provider())
    payload = {"name": "First notice", "sender_name": "Tech Roulette", "subject": "First",
               "body": "Hello", "attach_certificate": False, "confirmed": True}
    first = client.post("/api/email/campaigns", json=payload)
    assert first.status_code == 201
    detail = client.get(f"/api/email/campaigns/{first.json()['id']}").json()
    assert detail["deliveries"][0]["provider_message_id"] == "message-1"
    assert detail["deliveries"][0]["sent_at"] is not None
    assert client.post("/api/email/campaigns", json=payload).status_code == 422
    assert client.post("/api/email/campaigns", json={**payload, "name": "Second notice"}).status_code == 201
    assert sent == ["First", "First"]
    assert client.post("/api/email/campaigns", json={**payload, "send_to": "unsent", "resend": True}).status_code == 422
    resent = client.post("/api/email/campaigns", json={**payload, "send_to": "all", "resend": True})
    assert resent.status_code == 201
    assert sent == ["First", "First", "First"]


def test_brevo_failure_is_recorded_and_test_email_stays_separate(client, make_user, login, fake_sheet, monkeypatch):
    from app.services import campaign_processor
    admin = make_user(Role.ADMIN, "failure@example.com"); login(admin.email)
    fake_sheet.people = [fake_sheet.make(2, "Alex", "alex@example.com")]
    class FailingProvider:
        def send(self, **kwargs):
            raise RuntimeError("Brevo rate limit (429)")
    monkeypatch.setattr(campaign_processor, "provider", lambda: FailingProvider())
    response = client.post("/api/email/campaigns", json={"name": "Failed notice", "sender_name": "Tech Roulette",
        "subject": "Hello", "body": "Hello", "attach_certificate": False, "confirmed": True})
    assert response.status_code == 201
    detail = client.get(f"/api/email/campaigns/{response.json()['id']}").json()
    assert detail["status"] == "FAILED"
    delivery = detail["deliveries"][0]
    assert delivery["status"] == "FAILED" and delivery["attempt_count"] == 1
    assert delivery["sent_at"] is None and delivery["provider_message_id"] is None
    assert "rate limit" in delivery["failure_reason"]
    test = client.post("/api/email/test", json={"to": "admin-test@example.com", "sender_name": "Tech Roulette",
        "subject": "Test", "body": "Hello"})
    assert test.status_code == 200 and test.json()["recipient"] == "admin-test@example.com"


def test_each_csv_participant_gets_own_pdf_and_placeholders(client, db, make_user, login, monkeypatch):
    from app.services import campaign_processor
    from pypdf import PdfReader
    admin = make_user(Role.ADMIN, "mapping@example.com"); login(admin.email)
    csv_data = ("name,email,team_name,college\nAarav Kumar,aarav@example.com,Nova,ABC College\n"
                "Meera Shah,meera@example.com,Orbit,XYZ University\n").encode()
    preview = client.post("/api/participants/import/preview", files={"file": ("people.csv", csv_data)}).json()
    imported = client.post("/api/participants/import", data={"digest": preview["digest"]}, files={"file": ("people.csv", csv_data)})
    assert imported.json()["imported"] == 2
    ids = [person["id"] for person in client.get("/api/participants/all").json()]
    changed = client.patch(f"/api/participants/{ids[0]}", json={"name": "Aarav Kumar", "email": "aarav@example.com",
        "team_name": "Nova", "college": "Edited University"})
    assert changed.status_code == 200, changed.text
    db.add(CertificateTemplate(name="Certificate", file_data=png(), file_type="png", is_active=True, created_by=admin.id)); db.commit()
    sent = []
    class Provider:
        def send(self, **kwargs):
            sent.append(kwargs)
            return f"message-{len(sent)}"
    monkeypatch.setattr(campaign_processor, "provider", lambda: Provider())
    response = client.post("/api/email/campaigns", json={"name": "Certificate Email", "sender_name": "Tech Roulette",
        "subject": "Hello {{participant_name}}", "body": "College: {{college_name}}",
        "selection": "selected", "participant_ids": ids, "confirmed": True})
    assert response.status_code == 201, response.text
    assert len(sent) == 2
    for message, name, college, address, other in ((sent[0], "Aarav Kumar", "Edited University", "aarav@example.com", "Meera Shah"),
                                                   (sent[1], "Meera Shah", "XYZ University", "meera@example.com", "Aarav Kumar")):
        assert message["to"] == address
        assert message["subject"] == f"Hello {name}"
        assert message["body"] == f"College: {college}"
        pdf_text = PdfReader(io.BytesIO(message["attachment"])).pages[0].extract_text()
        assert name in pdf_text and college in pdf_text and other not in pdf_text
    detail = client.get(f"/api/email/campaigns/{response.json()['id']}").json()
    assert (detail["recipient_count"], detail["sent_count"], detail["failed_count"]) == (2, 2, 0)


def test_review_count_change_blocks_send(client, make_user, login, fake_sheet):
    admin = make_user(Role.ADMIN, "count@example.com"); login(admin.email)
    fake_sheet.people = [fake_sheet.make(2, "Alex", "alex@example.com")]
    response = client.post("/api/email/campaigns", json={"name": "Notice", "sender_name": "Tech Roulette",
        "subject": "Hello", "body": "Test", "attach_certificate": False,
        "selection": "selected", "participant_ids": [2], "expected_recipients": 2, "confirmed": True})
    assert response.status_code == 409
    assert client.get("/api/email/campaigns").json() == []


def test_edited_participants_render_individually_before_provider_send(client, make_user, login, fake_sheet, monkeypatch):
    from app.services import campaign_processor
    make_user(Role.ADMIN, "personalize@example.com"); login("personalize@example.com")
    fake_sheet.people = [fake_sheet.make(2, "Alex", "alex@example.com", "Old College"),
                         fake_sheet.make(3, "Meera", "meera@example.com", "Second College")]
    changed = client.patch("/api/participants/2", json={"name": "Alex New", "email": "alexnew@example.com",
        "team_name": "New Team", "college": "New University"})
    assert changed.status_code == 200, changed.text
    sent = []
    class Provider:
        def send(self, **kwargs):
            sent.append(kwargs)
            return "provider-123"
    monkeypatch.setattr(campaign_processor, "provider", lambda: Provider())
    response = client.post("/api/email/campaigns", json={"name": "Personalized", "sender_name": "Tech Roulette",
        "subject": "Hi [name] / {{participant_name}}", "body": "College [college] / {{college_name}}",
        "attach_certificate": False, "selection": "all", "confirmed": True})
    assert response.status_code == 201, response.text
    assert [(item["to"], item["subject"], item["body"]) for item in sent] == [
        ("alexnew@example.com", "Hi Alex New / Alex New", "College New University / New University"),
        ("meera@example.com", "Hi Meera / Meera", "College Second College / Second College")]
    assert all("[name]" not in item["subject"] for item in sent)
    preview = client.post("/api/email/preview", json={"name": "Preview", "subject": "Hi [name]",
        "body": "At {{college_name}}", "participant_id": 2})
    assert preview.json() == {"subject": "Hi Alex New", "body": "At New University"}


def test_pending_delivery_uses_latest_participant_details(client, make_user, login, fake_sheet, monkeypatch):
    from app.services import campaign_processor
    make_user(Role.ADMIN, "pending-edit@example.com"); login("pending-edit@example.com")
    fake_sheet.people = [fake_sheet.make(i, f"Person {i}", f"person{i}@example.com") for i in range(2, 13)]
    sent = []
    class Provider:
        def send(self, **kwargs):
            sent.append(kwargs)
            return "provider-123"
    monkeypatch.setattr(campaign_processor, "provider", lambda: Provider())
    response = client.post("/api/email/campaigns", json={"name": "Pending edit", "sender_name": "Tech Roulette",
        "subject": "Hi [name]", "body": "At [college]", "attach_certificate": False,
        "selection": "all", "confirmed": True})
    assert response.status_code == 201 and response.json()["status"] == "PROCESSING"
    changed = client.patch("/api/participants/12", json={"name": "Updated Person", "email": "updated@example.com",
        "team_name": "Updated Team", "college": "Updated College"})
    assert changed.status_code == 200
    continued = client.post(f"/api/email/campaigns/{response.json()['id']}/continue")
    assert continued.status_code == 200
    assert sent[-1]["to"] == "updated@example.com"
    assert sent[-1]["subject"] == "Hi Updated Person"
    assert sent[-1]["body"] == "At Updated College"


def test_campaign_keeps_certificate_settings_it_started_with(client, db, make_user, login, fake_sheet, monkeypatch):
    from app.services import campaign_processor
    from pypdf import PdfReader
    admin = make_user(Role.ADMIN, "snapshot@example.com"); login(admin.email)
    fake_sheet.people = [fake_sheet.make(i, f"Person {i}", f"person{i}@example.com") for i in range(2, 13)]
    template = CertificateTemplate(name="Certificate", file_data=png(), file_type="png", is_active=True,
                                   created_by=admin.id, include_team=True)
    db.add(template); db.commit()
    sent = []
    class Provider:
        def send(self, **kwargs):
            sent.append(kwargs)
            return "provider-123"
    monkeypatch.setattr(campaign_processor, "provider", lambda: Provider())
    response = client.post("/api/email/campaigns", json={"name": "Snapshot", "sender_name": "Tech Roulette",
        "subject": "Hi [name]", "body": "Certificate attached", "selection": "all", "confirmed": True})
    assert response.status_code == 201 and response.json()["status"] == "PROCESSING"
    # Editing the template between batches must not change the rest of this campaign.
    assert client.patch(f"/api/certificates/templates/{template.id}",
                        json={"include_college": False, "include_team": False}).status_code == 200
    assert client.post(f"/api/email/campaigns/{response.json()['id']}/continue").status_code == 200
    assert len(sent) == 11
    for message in sent:
        content = PdfReader(io.BytesIO(message["attachment"])).pages[0].extract_text()
        assert "Team Test" in content and "Example College" in content
