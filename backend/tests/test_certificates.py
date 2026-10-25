import io
from PIL import Image
from pypdf import PdfReader
from app.models import Role


def png():
    output = io.BytesIO(); Image.new("RGB", (1000, 700), "white").save(output, format="PNG"); return output.getvalue()


def test_template_two_fields_and_on_demand_pdf(client, make_user, login, fake_sheet):
    fake_sheet.people = [fake_sheet.make(2, "Alex Johnson", "alex@example.com", "Example College")]
    admin = make_user(Role.ADMIN, "admin@example.com"); login(admin.email)
    uploaded = client.post("/api/certificates/templates", data={"name": "Participation"}, files={"file": ("art.png", png(), "image/png")})
    assert uploaded.status_code == 201
    template_id = uploaded.json()["id"]
    updated = client.patch(f"/api/certificates/templates/{template_id}", json={"name_x": 48, "college_x": 52, "college_y": 64, "college_font_size": 20})
    assert updated.status_code == 200 and updated.json()["college_x"] == 52
    assert client.post(f"/api/certificates/templates/{template_id}/activate").status_code == 200
    preview = client.get(f"/api/certificates/templates/{template_id}/preview")
    assert preview.status_code == 200 and len(PdfReader(io.BytesIO(preview.content)).pages) == 1
    pdf = client.get("/api/certificates/participants/2/download")
    assert pdf.status_code == 200 and len(PdfReader(io.BytesIO(pdf.content)).pages) == 1
    pdf_text = PdfReader(io.BytesIO(pdf.content)).pages[0].extract_text()
    assert "Alex Johnson" in pdf_text and "Example College" in pdf_text
    row = client.get("/api/certificates/participants/2").json()
    assert row["status"] == "READY" and "certificate_id" not in row


def test_include_settings_and_missing_participant_details(client, make_user, login):
    admin = make_user(Role.ADMIN, "include@example.com"); login(admin.email)
    uploaded = client.post("/api/certificates/templates", data={"name": "Participation"}, files={"file": ("art.png", png(), "image/png")})
    template_id = uploaded.json()["id"]
    assert (uploaded.json()["include_college"], uploaded.json()["include_team"]) == (True, False)
    assert client.post(f"/api/certificates/templates/{template_id}/activate").status_code == 200
    full = client.post("/api/participants", json={"name": "Alex Johnson", "email": "alex@example.com",
                                                  "team_name": "Team Nova", "college": "Example College"}).json()
    bare = client.post("/api/participants", json={"name": "Riya Sen", "email": "riya@example.com"}).json()

    def text(participant_id):
        response = client.get(f"/api/certificates/participants/{participant_id}/download")
        assert response.status_code == 200
        return PdfReader(io.BytesIO(response.content)).pages[0].extract_text()

    for include_college, include_team in ((True, False), (True, True), (False, True), (False, False)):
        updated = client.patch(f"/api/certificates/templates/{template_id}",
                               json={"include_college": include_college, "include_team": include_team, "team_y": 82})
        assert updated.status_code == 200 and updated.json()["team_y"] == 82
        content = text(full["id"])
        assert "Alex Johnson" in content
        assert ("Example College" in content) == include_college
        assert ("Team Nova" in content) == include_team
        assert text(bare["id"]).strip() == "Riya Sen"
    manual = client.post("/api/certificates/manual", json={"participant_name": "Solo Person"})
    assert manual.status_code == 200
    assert PdfReader(io.BytesIO(manual.content)).pages[0].extract_text().strip() == "Solo Person"
