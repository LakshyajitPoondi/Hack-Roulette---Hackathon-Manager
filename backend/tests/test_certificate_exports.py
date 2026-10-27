from datetime import datetime, timedelta, timezone
import io
from uuid import uuid4

from PIL import Image
from pypdf import PdfReader
import pytest
from sqlalchemy import func, select

from app.models import CertificateTemplate, EmailCampaign, EmailDelivery, Participant, Role
from app.models.certificate_export import CertificateExport, CertificateExportRecipient
from app.models.dataset import Dataset, DatasetParticipant
from app.api import certificate_exports


def png(color="white"):
    stream = io.BytesIO(); Image.new("RGB", (700, 500), color).save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def setup(db, make_user, login, monkeypatch):
    actor = make_user(Role.ADMIN, "exports@example.com"); login(actor.email)
    template = CertificateTemplate(name="Participation", file_data=png(), file_type="png", is_active=True,
        include_team=True, name_font_family="liberation-serif", created_by=actor.id)
    people = [Participant(id=11, name="José Živković", email="shared@example.com", college="College One", team_name="Team One"),
              Participant(id=12, name="Same Name", email="shared@example.com", college="College Two", team_name="Team Two"),
              Participant(id=13, name="Same Name", email="other@example.com")]
    dataset = Dataset(name="First", original_filename="first.csv", original_data=b"name,email", headers=["name", "email"],
                      original_rows=[], rows=[])
    db.add_all([template, dataset, *people]); db.flush()
    db.add_all([DatasetParticipant(dataset_id=dataset.id, participant_id=p.id) for p in people[:2]])
    db.commit()
    from app.services import campaign_processor, email_delivery
    def forbidden():
        raise AssertionError("Bulk certificate downloads must never use an email provider")
    monkeypatch.setattr(campaign_processor, "provider", forbidden)
    monkeypatch.setattr(email_delivery, "provider", forbidden)
    return actor, template, people, dataset


def create(client, **overrides):
    return client.post("/api/certificates/exports", json={"request_id": str(uuid4()), "selection": "all", **overrides})


def pdf(client, run, id):
    return client.get(f"/api/certificates/exports/{run}/participants/{id}")


def test_selection_scope_filenames_and_no_email_side_effects(client, db, setup):
    actor, template, people, dataset = setup
    scoped = create(client, dataset_id=dataset.id, expected_count=2)
    assert scoped.status_code == 201, scoped.text
    assert scoped.headers["cache-control"] == "private, no-store"
    assert [p["id"] for p in scoped.json()["recipients"]] == [11, 12]
    all_people = create(client)
    assert all_people.status_code == 201 and all_people.json()["total"] == 3
    selected = create(client, selection="selected", participant_ids=[12, 13], template_id=template.id)
    assert selected.status_code == 201
    assert [p["filename"] for p in selected.json()["recipients"]] == ["Same_Name_12.pdf", "Same_Name_13.pdf"]
    assert pdf(client, scoped.json()["id"], 13).status_code == 404
    first = pdf(client, scoped.json()["id"], 11)
    assert first.status_code == 200 and first.headers["cache-control"] == "private, no-store"
    content = PdfReader(io.BytesIO(first.content)).pages[0].extract_text()
    assert "José Živković" in content and "College One" in content and "Team One" in content
    second = pdf(client, scoped.json()["id"], 12)
    content = PdfReader(io.BytesIO(second.content)).pages[0].extract_text()
    assert "Same Name" in content and "College Two" in content and "Team Two" in content
    assert db.scalar(select(func.count()).select_from(EmailCampaign)) == 0
    assert db.scalar(select(func.count()).select_from(EmailDelivery)) == 0
    assert len(db.scalars(select(Participant)).all()) == 3
    assert people[0].name == "José Živković" and people[0].email == "shared@example.com"


def test_template_and_participant_snapshots_are_stable(client, db, setup):
    actor, template, people, dataset = setup
    run = create(client).json()
    other = CertificateTemplate(name="Other", file_data=png("red"), file_type="png", created_by=actor.id)
    db.add(other); db.commit()
    assert client.post(f"/api/certificates/templates/{other.id}/activate").status_code == 200
    assert client.patch(f"/api/certificates/templates/{template.id}", json={"name": "Changed", "name_uppercase": True, "include_college": False, "include_team": False}).status_code == 200
    assert client.post(f"/api/certificates/templates/{template.id}/replace", files={"file": ("new.png", png("blue"), "image/png")}).status_code == 200
    people[0].name = "Changed Participant"; people[0].college = "Changed College"; db.commit()
    exported = db.get(CertificateExport, run["id"])
    assert exported.template_snapshot["name"] == "Participation" and exported.file_data == png()
    content = PdfReader(io.BytesIO(pdf(client, run["id"], 11).content)).pages[0].extract_text()
    assert "José Živković" in content and "College One" in content and "Team One" in content
    assert "Changed Participant" not in content


def test_invalid_ids_boundaries_limits_and_filename_safety(client, db, setup, monkeypatch):
    _, template, _, dataset = setup
    assert create(client, selection="selected", participant_ids=[]).status_code == 422
    assert create(client, selection="selected", participant_ids=[11, 11]).status_code == 422
    assert create(client, selection="selected", participant_ids=[999]).status_code == 422
    assert create(client, selection="selected", dataset_id=dataset.id, participant_ids=[13]).status_code == 422
    assert create(client, dataset_id=999).status_code == 404
    assert create(client, template_id=999).status_code == 404
    assert create(client, participant_ids=[11]).status_code == 422
    assert create(client, expected_count=4).status_code == 409
    monkeypatch.setattr(certificate_exports, "MAX_RECIPIENTS", 2)
    assert create(client).status_code == 422
    for name in ("../../evil", "CON", "a\\b/c:<>|?*", "\x00\n", "José Živković"):
        value = certificate_exports.filename(name, 11)
        assert value.endswith("_11.pdf") and not any(c in value for c in '\\/:<>|?*\x00\n')
        assert not value.startswith(".")


def test_private_ownership_expiry_idempotency_and_cleanup(client, db, setup, make_user, login):
    actor, _, _, _ = setup
    request_id = str(uuid4())
    run = create(client, request_id=request_id).json()
    again = create(client, request_id=request_id)
    assert again.status_code == 201 and again.json() == run
    assert db.scalar(select(func.count()).select_from(CertificateExport)) == 1
    other = make_user(Role.ADMIN, "other-export@example.com"); login(other.email)
    assert pdf(client, run["id"], 11).status_code == 404
    assert create(client, request_id=request_id).status_code == 404
    assert client.delete(f"/api/certificates/exports/{run['id']}").status_code == 204
    assert db.get(CertificateExport, run["id"]) is not None
    login(actor.email)
    db.get(CertificateExport, run["id"]).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); db.commit()
    assert pdf(client, run["id"], 11).status_code == 404
    next_run = create(client).json()
    assert db.get(CertificateExport, run["id"]) is None
    assert not list(db.scalars(select(CertificateExportRecipient).where(CertificateExportRecipient.export_id == run["id"])))
    assert client.delete(f"/api/certificates/exports/{next_run['id']}").status_code == 204
    assert client.delete(f"/api/certificates/exports/{next_run['id']}").status_code == 204
    assert db.scalar(select(func.count()).select_from(CertificateExport)) == 0
    make_user(Role.STAFF, "export-staff@example.com"); login("export-staff@example.com")
    assert create(client).status_code == 403
    assert pdf(client, next_run["id"], 11).status_code == 403
    assert client.delete(f"/api/certificates/exports/{next_run['id']}").status_code == 403
    client.post("/api/auth/logout")
    assert create(client).status_code == 401


def test_per_pdf_errors_are_private_and_bounded(client, setup, monkeypatch):
    run = create(client).json()
    def broken(*args):
        raise RuntimeError("Sensitive internal details")
    monkeypatch.setattr(certificate_exports.certificates, "render_pdf", broken)
    response = pdf(client, run["id"], 11)
    assert response.status_code == 422 and "Sensitive" not in response.text
    monkeypatch.setattr(certificate_exports.certificates, "render_pdf", lambda *args: b"x" * (certificate_exports.MAX_PDF_BYTES + 1))
    assert pdf(client, run["id"], 11).status_code == 413


def test_active_export_limit_and_empty_scopes(client, db, setup):
    _, _, _, dataset = setup
    for _ in range(3):
        assert create(client).status_code == 201
    assert create(client).status_code == 409
    db.query(CertificateExportRecipient).delete(); db.query(CertificateExport).delete(); db.commit()
    db.query(DatasetParticipant).delete(); db.commit()
    assert create(client, dataset_id=dataset.id).status_code == 422


def test_inactive_template_selection_and_manifest_limit(client, db, setup, monkeypatch):
    actor, active, _, _ = setup
    other = CertificateTemplate(name="Alternate", file_data=png("blue"), file_type="png", created_by=actor.id,
        name_uppercase=True, name_font_family="liberation-serif")
    db.add(other); db.commit()
    default = create(client).json()
    assert default["template_id"] == active.id
    selected = create(client, template_id=other.id).json()
    assert selected["template_id"] == other.id and selected["template_name"] == "Alternate"
    content = PdfReader(io.BytesIO(pdf(client, selected["id"], 11).content)).pages[0].extract_text()
    assert "JOSÉ ŽIVKOVIĆ" in content
    monkeypatch.setattr(certificate_exports, "MAX_MANIFEST_BYTES", 10)
    assert create(client).status_code == 422
    assert db.scalar(select(func.count()).select_from(CertificateExport)) == 2
