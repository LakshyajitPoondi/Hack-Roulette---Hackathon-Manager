import io

import pytest
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import func, select

from app.models import CertificateTemplate, EmailCampaign, EmailTemplate, Role
from app.services import campaign_processor


def png(color="white"):
    result = io.BytesIO()
    Image.new("RGB", (1000, 700), color).save(result, format="PNG")
    return result.getvalue()


@pytest.fixture
def admin(client, make_user, login):
    user = make_user(Role.ADMIN, "templates@example.com"); login(user.email)
    return user


def certificate(client, name, color="white"):
    response = client.post("/api/certificates/templates", data={"name": name}, files={"file": ("template.png", png(color), "image/png")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_email_rename_is_partial_persistent_and_validated(client, db, admin):
    original = {"name": "Welcome", "subject": "Hello {{participant_name}}", "body": "At {{college_name}}"}
    created = client.post("/api/email/templates", json=original)
    assert created.status_code == 201
    id = created.json()["id"]
    renamed = client.patch(f"/api/email/templates/{id}", json={"name": "  Greeting  "})
    assert renamed.status_code == 200
    assert renamed.json()["id"] == id and renamed.json()["name"] == "Greeting"
    assert (renamed.json()["subject"], renamed.json()["body"]) == (original["subject"], original["body"])
    assert client.get("/api/email/templates").json()[0]["name"] == "Greeting"
    assert db.scalar(select(func.count()).select_from(EmailTemplate)) == 1
    second = client.post("/api/email/templates", json={**original, "name": "Second"}).json()["id"]
    for invalid, status in (("greeting", 409), ("   ", 422)):
        assert client.patch(f"/api/email/templates/{second}", json={"name": invalid}).status_code == status
    assert client.post("/api/email/templates", json={**original, "name": "GREETING"}).status_code == 409
    assert client.patch(f"/api/email/templates/{id}", json={"name": None}).status_code == 422
    assert client.patch(f"/api/email/templates/{id}", json={}).status_code == 422
    assert client.patch(f"/api/email/templates/{id}", json={"subject": "Updated"}).status_code == 200
    assert client.post("/api/email/preview", json={"name": "Preview", "subject": original["subject"], "body": original["body"]}).json()["subject"] == "Hello Alex Johnson"


def test_certificate_rename_preserves_file_and_settings(client, db, admin, monkeypatch):
    id = certificate(client, "Participation")
    other = certificate(client, "Winner")
    assert client.patch(f"/api/certificates/templates/{id}", json={"name_x": 43, "include_team": True}).status_code == 200
    original_file = bytes(db.get(CertificateTemplate, id).file_data)
    from app.services import certificates
    monkeypatch.setattr(certificates, "render_pdf", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Rename must not generate PDFs")))
    renamed = client.patch(f"/api/certificates/templates/{id}", json={"name": "  Attendance  "})
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["id"], renamed.json()["name"], renamed.json()["name_x"], renamed.json()["include_team"]) == (id, "Attendance", 43, True)
    assert bytes(db.get(CertificateTemplate, id).file_data) == original_file
    assert db.scalar(select(func.count()).select_from(CertificateTemplate)) == 2
    assert next(t for t in client.get("/api/certificates/templates").json() if t["id"] == id)["name"] == "Attendance"
    assert client.patch(f"/api/certificates/templates/{other}", json={"name": "attendance"}).status_code == 409
    assert client.patch(f"/api/certificates/templates/{id}", json={"name": " "}).status_code == 422
    assert client.post(f"/api/certificates/templates/{id}/activate").status_code == 200
    assert client.post(f"/api/certificates/templates/{other}/activate").status_code == 200
    assert [t["id"] for t in client.get("/api/certificates/templates").json() if t["is_active"]] == [other]


def test_campaign_selected_certificate_snapshot_shared_email_and_dataset(client, db, admin, monkeypatch):
    active = certificate(client, "Active")
    selected = certificate(client, "Selected", "yellow")
    assert client.post(f"/api/certificates/templates/{active}/activate").status_code == 200
    assert client.patch(f"/api/certificates/templates/{selected}", json={"include_team": True, "name_uppercase": True}).status_code == 200
    data = b"name,email,team_name,college\nJohn,shared@example.com,Alpha,College One\nJonathan,shared@example.com,Beta,College Two\n"
    dataset = client.post("/api/datasets", data={"name": "Campaign dataset"}, files={"file": ("data.csv", data)}).json()["id"]
    plan = client.post(f"/api/datasets/{dataset}/preview", json={"approved_rows": [2]}).json()
    assert client.post(f"/api/datasets/{dataset}/import", json={"digest": plan["digest"], "approved_rows": [2]}).status_code == 200
    assert client.post("/api/participants", json={"name": "Outside dataset", "email": "outside@example.com"}).status_code == 201
    people = client.get("/api/participants/all", params={"dataset_id": dataset}).json()
    assert len(people) == 2
    from app.api import emails
    # Pause initial processing to exercise later configuration changes without sending anything.
    monkeypatch.setattr(emails, "process_campaign", lambda *a: 0)
    payload = {"name": "Certificates", "sender_name": "Tech Roulette", "subject": "Hi {{participant_name}}", "body": "At {{college_name}}",
               "selection": "all", "dataset_id": dataset, "certificate_template_id": selected, "attach_certificate": True, "confirmed": True}
    created = client.post("/api/email/campaigns", json=payload)
    assert created.status_code == 201, created.text
    id = created.json()["id"]
    campaign = db.get(EmailCampaign, id)
    assert campaign.certificate_template_id == selected and campaign.dataset_id == dataset
    assert campaign.certificate_file_data == png("yellow")
    assert client.patch(f"/api/certificates/templates/{selected}", json={"name": "Renamed", "name_uppercase": False, "include_team": False, "name_font_size": 80}).status_code == 200
    assert client.post(f"/api/certificates/templates/{selected}/replace", files={"file": ("other.png", png("blue"), "image/png")}).status_code == 200
    assert client.delete(f"/api/certificates/templates/{selected}").status_code == 409
    assert client.delete(f"/api/participants/{people[0]['id']}").status_code == 409
    assert client.delete("/api/participants/clear").status_code == 409
    captured = []
    class Provider:
        def send(self, **kwargs):
            captured.append(kwargs)
            return "mocked-message"
    monkeypatch.setattr(campaign_processor, "provider", lambda: Provider())
    monkeypatch.setattr(emails, "process_campaign", campaign_processor.process_campaign)
    assert client.post(f"/api/email/campaigns/{id}/continue").status_code == 200
    assert len(captured) == 2
    for message, name, college, team in zip(captured, ["JOHN", "JONATHAN"], ["College One", "College Two"], ["Alpha", "Beta"]):
        text = PdfReader(io.BytesIO(message["attachment"])).pages[0].extract_text()
        assert name in text and college in text and team in text
        assert message["to"] == "shared@example.com" and message["subject"] == f"Hi {name}"
    detail = client.get(f"/api/email/campaigns/{id}").json()
    assert detail["certificate_template_name"] == "Selected" and detail["recipient_count"] == 2
    assert {d["participant_id"] for d in detail["deliveries"]} == {p["id"] for p in people}
    assert client.post(f"/api/datasets/{dataset}/archive").status_code == 200
    assert client.get(f"/api/email/campaigns/{id}").json()["sent_count"] == 2


def test_certificate_default_selection_preview_and_plain_email(client, db, admin, monkeypatch):
    active = certificate(client, "Active")
    other = certificate(client, "Uppercase")
    client.post(f"/api/certificates/templates/{active}/activate")
    client.patch(f"/api/certificates/templates/{other}", json={"name_uppercase": True})
    person = client.post("/api/participants", json={"name": "Alice", "email": "alice@example.com"}).json()
    preview = {"name": "Preview", "participant_id": person["id"], "subject": "Hi {{participant_name}}", "body": "Message", "attach_certificate": True, "certificate_template_id": other}
    assert client.post("/api/email/preview", json=preview).json()["subject"] == "Hi ALICE"
    assert client.post("/api/email/preview", json={**preview, "certificate_template_id": 9999}).status_code == 404
    captured = []
    class Provider:
        def send(self, **kwargs):
            captured.append(kwargs); return "mocked"
    monkeypatch.setattr(campaign_processor, "provider", lambda: Provider())
    payload = {"name": "Default", "sender_name": "Tech Roulette", "subject": "Hi [name]", "body": "Body", "selection": "all", "confirmed": True}
    first = client.post("/api/email/campaigns", json=payload)
    assert first.status_code == 201
    assert db.get(EmailCampaign, first.json()["id"]).certificate_template_id == active
    plain = client.post("/api/email/campaigns", json={**payload, "name": "Plain", "attach_certificate": False, "certificate_template_id": 9999})
    assert plain.status_code == 201 and captured[-1]["attachment"] is None
    assert db.get(EmailCampaign, plain.json()["id"]).certificate_snapshot is None
    assert client.post("/api/email/campaigns", json={**payload, "resend": True, "send_to": "all", "certificate_template_id": 9999}).status_code == 404
