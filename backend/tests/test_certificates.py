import io
import re
from typing import get_args

from PIL import Image
from pypdf import PdfReader
from reportlab.pdfbase.ttfonts import TTFont
from app.models import Role
from app.schemas.certificate import FontFamily
from app.services import certificate_fonts


def png():
    output = io.BytesIO(); Image.new("RGB", (1000, 700), "white").save(output, format="PNG"); return output.getvalue()


def pdf_fonts(content: bytes) -> dict[str, bool]:
    """Fonts the page's text uses: name (without subset prefix) -> whether its font file is embedded."""
    page = PdfReader(io.BytesIO(content)).pages[0]
    fonts = page["/Resources"]["/Font"]
    # ReportLab's page setup selects Helvetica without drawing; only count fonts active when text is shown.
    used, current = set(), None
    for match in re.finditer(rb"/(\S+)\s+[\d.]+\s+Tf|[)>\]]\s*T[jJ]", page.get_contents().get_data()):
        if match.group(1):
            current = "/" + match.group(1).decode()
        else:
            used.add(current)
    result = {}
    for font in (fonts[key].get_object() for key in fonts if key in used):
        descriptor = font.get("/FontDescriptor")
        embedded = descriptor is not None and any(key in descriptor.get_object() for key in ("/FontFile", "/FontFile2", "/FontFile3"))
        result[str(font["/BaseFont"]).lstrip("/").split("+")[-1]] = embedded
    return result


def expected_font(family: str, style: str) -> str:
    entry = certificate_fonts.FAMILIES[family]
    face = entry.faces[style]
    return face if entry.builtin else TTFont("check", str(certificate_fonts.FONT_DIR / face)).face.name.decode()


def upload_active_template(client):
    template_id = client.post("/api/certificates/templates", data={"name": "Fonts"},
                              files={"file": ("art.png", png(), "image/png")}).json()["id"]
    assert client.post(f"/api/certificates/templates/{template_id}/activate").status_code == 200
    return template_id


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


def test_font_catalog_files_and_public_font_endpoint(client, make_user, login):
    assert get_args(FontFamily) == tuple(certificate_fonts.FAMILIES)
    for entry in certificate_fonts.FAMILIES.values():
        if not entry.builtin:
            assert all((certificate_fonts.FONT_DIR / face).is_file() for face in entry.faces.values())
    assert certificate_fonts.FAMILIES["liberation-serif"].faces.keys() == {"regular", "bold", "italic", "bold_italic"}
    assert list(certificate_fonts.FAMILIES["great-vibes"].faces) == ["regular"]
    assert client.get("/api/certificates/fonts").status_code == 401
    admin = make_user(Role.ADMIN, "fonts@example.com"); login(admin.email)
    catalog = {item["key"]: item for item in client.get("/api/certificates/fonts").json()}
    # Times previews with its metric-compatible bundled files; Helvetica previews with Arial.
    assert catalog["times"]["preview_files"]["bold"] == "/api/certificates/fonts/liberation-serif/bold"
    assert catalog["helvetica"]["preview_files"] == {} and catalog["cinzel"]["styles"] == ["regular", "bold"]
    client.cookies.clear()
    response = client.get("/api/certificates/fonts/montserrat/bold_italic")
    assert response.status_code == 200 and response.headers["content-type"] == "font/ttf"
    assert response.content == (certificate_fonts.FONT_DIR / "Montserrat-BoldItalic.ttf").read_bytes()
    for family, style in (("helvetica", "regular"), ("great-vibes", "bold"), ("unknown", "regular"), ("..", "regular")):
        assert client.get(f"/api/certificates/fonts/{family}/{style}").status_code == 404


def test_existing_templates_keep_helvetica(client, make_user, login):
    admin = make_user(Role.ADMIN, "default-font@example.com"); login(admin.email)
    template_id = upload_active_template(client)
    saved = next(item for item in client.get("/api/certificates/templates").json() if item["id"] == template_id)
    assert {key: saved[key] for key in saved if key.endswith(("_font_family", "_bold", "_italic"))} == {
        "name_font_family": "helvetica", "name_bold": True, "name_italic": False,
        "college_font_family": "helvetica", "college_bold": False, "college_italic": False,
        "team_font_family": "helvetica", "team_bold": False, "team_italic": False}
    pdf = client.post("/api/certificates/manual", json={"participant_name": "Alex", "college_name": "Example College"})
    assert pdf_fonts(pdf.content) == {"Helvetica-Bold": False, "Helvetica": False}


def test_independent_field_fonts_persist_and_reach_every_path(client, db, make_user, login, monkeypatch):
    from app.services import campaign_processor
    admin = make_user(Role.ADMIN, "field-fonts@example.com"); login(admin.email)
    template_id = upload_active_template(client)
    settings = {"include_team": True, "name_font_family": "liberation-serif", "name_bold": True, "name_italic": False,
                "college_font_family": "eb-garamond", "college_bold": False, "college_italic": True,
                "team_font_family": "montserrat", "team_bold": True, "team_italic": True, "name_font_size": 35}
    assert client.patch(f"/api/certificates/templates/{template_id}", json=settings).status_code == 200
    saved = next(item for item in client.get("/api/certificates/templates").json() if item["id"] == template_id)
    assert {key: saved[key] for key in settings} == settings
    expected = {"LiberationSerif-Bold": True, "EBGaramond-Italic": True, "Montserrat-BoldItalic": True}
    person = client.post("/api/participants", json={"name": "Alex Johnson", "email": "alex@example.com",
                                                    "team_name": "Team Nova", "college": "Example College"}).json()
    assert pdf_fonts(client.get(f"/api/certificates/participants/{person['id']}/download").content) == expected
    assert pdf_fonts(client.get(f"/api/certificates/templates/{template_id}/preview").content) == expected
    assert pdf_fonts(client.post("/api/certificates/manual", json={"participant_name": "A", "college_name": "B", "team_name": "C"}).content) == expected
    sent = []
    class Provider:
        def send(self, **kwargs):
            sent.append(kwargs)
            return "provider-123"
    monkeypatch.setattr(campaign_processor, "provider", lambda: Provider())
    campaign = client.post("/api/email/campaigns", json={"name": "Fonts", "sender_name": "Tech Roulette", "subject": "Hi",
        "body": "Attached", "selection": "selected", "participant_ids": [person["id"]], "confirmed": True})
    assert campaign.status_code == 201, campaign.text
    assert pdf_fonts(sent[0]["attachment"]) == expected


def test_every_supported_style_renders_with_its_own_font_file(client, make_user, login):
    admin = make_user(Role.ADMIN, "all-fonts@example.com"); login(admin.email)
    template_id = upload_active_template(client)
    for family, entry in certificate_fonts.FAMILIES.items():
        for style in entry.faces:
            bold, italic = style in {"bold", "bold_italic"}, style in {"italic", "bold_italic"}
            assert client.patch(f"/api/certificates/templates/{template_id}", json={
                "name_font_family": family, "name_bold": bold, "name_italic": italic}).status_code == 200
            fonts = pdf_fonts(client.post("/api/certificates/manual", json={"participant_name": "Sample"}).content)
            assert fonts == {expected_font(family, style): not entry.builtin}, (family, style)


def test_uppercase_settings_apply_only_when_rendering(client, make_user, login, monkeypatch):
    from app.api import emails
    from app.services import campaign_processor
    admin = make_user(Role.ADMIN, "uppercase@example.com"); login(admin.email)
    template_id = upload_active_template(client)
    saved = next(item for item in client.get("/api/certificates/templates").json() if item["id"] == template_id)
    assert (saved["name_uppercase"], saved["college_uppercase"], saved["team_uppercase"]) == (False, False, False)
    person = client.post("/api/participants", json={"name": "Lakshyajit Poondi", "email": "Lakshya@Example.com",
                                                    "team_name": "Team Alpha", "college": "Easwari Engineering College"}).json()
    assert client.patch(f"/api/certificates/templates/{template_id}", json={"include_team": True}).status_code == 200
    originals = {"name": "Lakshyajit Poondi", "college": "Easwari Engineering College", "team": "Team Alpha"}

    def text(response):
        return PdfReader(io.BytesIO(response.content)).pages[0].extract_text()

    assert all(value in text(client.get(f"/api/certificates/participants/{person['id']}/download")) for value in originals.values())
    for field in originals:
        assert client.patch(f"/api/certificates/templates/{template_id}",
                            json={f"{other}_uppercase": other == field for other in originals}).status_code == 200
        content = text(client.get(f"/api/certificates/participants/{person['id']}/download"))
        for other, value in originals.items():
            assert (value.upper() if other == field else value) in content, (field, other)
            assert (value not in content) == (other == field), (field, other)
    assert client.patch(f"/api/certificates/templates/{template_id}",
                        json={"name_uppercase": True, "college_uppercase": True, "team_uppercase": True}).status_code == 200
    # Stored participant data is unchanged.
    stored = client.get(f"/api/participants/{person['id']}").json()
    assert (stored["name"], stored["college"], stored["team_name"]) == ("Lakshyajit Poondi", "Easwari Engineering College", "Team Alpha")
    assert "ALEX JOHNSON" in text(client.get(f"/api/certificates/templates/{template_id}/preview"))
    manual = text(client.post("/api/certificates/manual", json={"participant_name": "Solo Person", "college_name": "Some College"}))
    assert "SOLO PERSON" in manual and "SOME COLLEGE" in manual

    # Email placeholders follow the certificate's casing only for certificate emails; other text is untouched.
    email = {"name": "P", "subject": "Hi {{participant_name}}", "body": "From [college]. Reply to Lakshya@Example.com",
             "participant_id": person["id"]}
    assert client.post("/api/email/preview", json={**email, "attach_certificate": True}).json() == {
        "subject": "Hi LAKSHYAJIT POONDI", "body": "From EASWARI ENGINEERING COLLEGE. Reply to Lakshya@Example.com"}
    assert client.post("/api/email/preview", json=email).json() == {
        "subject": "Hi Lakshyajit Poondi", "body": "From Easwari Engineering College. Reply to Lakshya@Example.com"}
    sent = []
    class Provider:
        def send(self, **kwargs):
            sent.append(kwargs)
            return "provider-123"
    monkeypatch.setattr(emails, "provider", lambda: Provider())
    monkeypatch.setattr(campaign_processor, "provider", lambda: Provider())
    assert client.post("/api/email/test", json={"to": "tester@example.com", "sender_name": "Tech Roulette", "subject": email["subject"],
                                                "body": email["body"], "participant_id": person["id"], "attach_certificate": True}).status_code == 200
    assert client.post("/api/email/campaigns", json={"name": "Upper", "sender_name": "Tech Roulette", "subject": email["subject"],
        "body": email["body"], "selection": "selected", "participant_ids": [person["id"]], "confirmed": True}).status_code == 201
    for message in sent:
        assert message["subject"] == "Hi LAKSHYAJIT POONDI" and "LAKSHYAJIT POONDI" in PdfReader(io.BytesIO(message["attachment"])).pages[0].extract_text()
    assert sent[1]["to"] == "lakshya@example.com"


def test_unsupported_font_styles_are_rejected(client, make_user, login):
    admin = make_user(Role.ADMIN, "bad-fonts@example.com"); login(admin.email)
    template_id = upload_active_template(client)
    for changes in ({"team_font_family": "great-vibes", "team_bold": True},
                    {"college_font_family": "cinzel", "college_italic": True},
                    {"name_font_family": "pinyon-script"}):  # the name is bold by default
        response = client.patch(f"/api/certificates/templates/{template_id}", json=changes)
        assert response.status_code == 422 and "style" in response.json()["detail"], changes
    assert client.patch(f"/api/certificates/templates/{template_id}", json={"name_font_family": "comic-sans"}).status_code == 422
    saved = next(item for item in client.get("/api/certificates/templates").json() if item["id"] == template_id)
    assert (saved["name_font_family"], saved["team_font_family"], saved["college_italic"]) == ("helvetica", "helvetica", False)
    assert client.patch(f"/api/certificates/templates/{template_id}",
                        json={"name_font_family": "pinyon-script", "name_bold": False}).status_code == 200
