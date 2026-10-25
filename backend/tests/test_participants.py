from types import SimpleNamespace

from fastapi import HTTPException
from app.models import Role
from app.services.google_sheets import GoogleSheetsParticipants
from app.services.google_sheets import _a1_range


def test_google_sheet_header_mapping(monkeypatch):
    source = GoogleSheetsParticipants()
    values = [["Timestamp", "Full Name", "Email Address", "College Name", "Certificate Eligible"],
              ["2026-09-23T10:00:00+05:30", "Alex Johnson", "ALEX@example.com", "Example College", "TRUE"]]
    monkeypatch.setattr(source, "_request", lambda method, range_name, **kwargs: {"values": values})
    person = source.list()[0]
    assert person.id == 2
    assert person.email == "alex@example.com"
    assert person.college == "Example College"
    assert person.certificate_eligible is True


def test_google_sheet_reports_missing_credentials(monkeypatch):
    from app.services import google_sheets

    monkeypatch.setattr(google_sheets, "get_settings", lambda: SimpleNamespace(
        google_sheets_spreadsheet_id="validSheetId", google_sheets_range="Responses!A:Z",
        google_service_account_json=None, google_sheets_api_key=None,
    ))
    source = GoogleSheetsParticipants()
    try:
        source.list()
    except HTTPException as exc:
        assert exc.status_code == 503
        assert "credentials are missing" in exc.detail
    else:
        assert False, "Expected a configuration error"


def test_form_response_tab_is_quoted_in_a1_ranges():
    assert _a1_range("Form Responses 1!A:Z") == "'Form Responses 1'!A:Z"
    assert _a1_range("Form Responses 1!J2") == "'Form Responses 1'!J2"
    assert _a1_range("'Form Responses 1'!A:Z") == "'Form Responses 1'!A:Z"


def test_csv_participants_are_stored_and_filtered(client, make_user, login, fake_sheet):
    fake_sheet.people = [fake_sheet.make(2, "Alex Johnson", "alex@example.com"), fake_sheet.make(3, "Beth", "beth@example.com", "Other College")]
    make_user(Role.SUPER_ADMIN, "super@example.com"); login("super@example.com")
    page = client.get("/api/participants", params={"search": "alex"})
    assert page.status_code == 200
    assert page.json()["source"] == "csv"
    assert page.json()["total"] == 1
    assert page.json()["items"][0]["id"] == 2
    assert client.get("/api/participants/3").json()["college"] == "Other College"
    assert len(client.get("/api/participants/all").json()) == 2
    metrics = client.get("/api/admin/dashboard").json()["metrics"]
    assert metrics["registrations"] == 2


def test_csv_workflow_does_not_call_google_sheets(client, make_user, login, monkeypatch):
    from app.services.google_sheets import GoogleSheetsParticipants

    monkeypatch.setattr(GoogleSheetsParticipants, "list", lambda self: (_ for _ in ()).throw(AssertionError("Sheets should not be used")))
    make_user(Role.ADMIN, "csv-only@example.com"); login("csv-only@example.com")
    assert client.get("/api/participants").json()["source"] == "csv"
    assert client.get("/api/admin/dashboard").status_code == 200
    csv_data = b"name,email,team_name,college\nAlex,alex@example.com,Nova,Example College\n"
    preview = client.post("/api/participants/import/preview", files={"file": ("people.csv", csv_data)})
    assert preview.status_code == 200
    result = client.post("/api/participants/import", data={"digest": preview.json()["digest"]}, files={"file": ("people.csv", csv_data)})
    assert result.json()["imported"] == 1
    assert client.get("/api/participants/all").json()[0]["name"] == "Alex"


def test_csv_import_preview_validation_and_rbac(client, make_user, login, fake_sheet):
    fake_sheet.people = [fake_sheet.make(2, "Alex Johnson", "alex@example.com")]
    make_user(Role.STAFF, "staff@example.com"); make_user(Role.ADMIN, "admin@example.com")
    data = ("\ufeffParticipant Name,Email Address,Team,College Name\r\n"
            'Meera Shah,MEERA@example.com,"Nova, Team",XYZ University\r\n'
            'Meera Again,meera@example.com,Nova,XYZ University\r\n'
            'Alex Johnson,ALEX@example.com,Nova,ABC College\r\n'
            'Bad,,Team,College\r\n'
            'Missing team,bad@example.com,,College\r\n'
            'Invalid,not-an-email,Team,College\r\n'
            '\r\n').encode('utf-8')
    login("staff@example.com")
    assert client.post("/api/participants/import/preview", files={"file": ("people.csv", data)}).status_code == 403
    login("admin@example.com")
    response = client.post("/api/participants/import/preview", files={"file": ("people.csv", data)})
    assert response.status_code == 200, response.text
    preview = response.json()
    assert (preview["valid"], preview["duplicates"], preview["invalid"]) == (1, 2, 3)
    assert preview["rows"][0]["team_name"] == "Nova, Team"
    assert client.get("/api/participants").json()["total"] == 1
    changed = client.post("/api/participants/import", data={"digest": preview["digest"]}, files={"file": ("people.csv", b"name,email,team_name,college\n")})
    assert changed.status_code == 409
    imported = client.post("/api/participants/import", data={"digest": preview["digest"]}, files={"file": ("people.csv", data)})
    assert imported.json() == {"imported": 1, "duplicates": 2, "invalid": 3}
    assert client.get("/api/participants").json()["total"] == 2
    assert client.get("/api/participants", params={"search": "meera"}).json()["items"][0]["email"] == "meera@example.com"
    repeated = client.post("/api/participants/import", data={"digest": preview["digest"]}, files={"file": ("people.csv", data)})
    assert repeated.json()["imported"] == 0
    assert client.delete("/api/participants/2").status_code == 204
    assert client.delete("/api/participants/clear").status_code == 204
    assert client.get("/api/participants").json()["total"] == 0


def test_same_origin_admin_post_is_allowed(client, make_user):
    make_user(Role.ADMIN, "same-origin@example.com")
    response = client.post("/api/auth/login", headers={"Origin": "http://testserver"},
                           json={"email": "same-origin@example.com", "password": "strong-test-password-123"})
    assert response.status_code == 200
    blocked = client.post("/api/auth/logout", headers={"Origin": "https://other.example"})
    assert blocked.status_code == 403


def test_csv_rejects_malformed_encoding_and_oversized_fields(client, make_user, login):
    make_user(Role.ADMIN, "csv-errors@example.com"); login("csv-errors@example.com")
    for data in (b"name,email,team_name,college\n\xff,bad@example.com,Team,College\n",
                 b'name,email,team_name,college\n"Unclosed,bad@example.com,Team,College\n'):
        assert client.post("/api/participants/import/preview", files={"file": ("bad.csv", data)}).status_code == 422
    long_name = "X" * 161
    result = client.post("/api/participants/import/preview", files={"file": ("long.csv", f"name,email,team_name,college\n{long_name},long@example.com,Team,College\n".encode())})
    assert result.status_code == 200
    assert result.json()["invalid"] == 1
    assert "too long" in result.json()["rows"][0]["reason"]


def test_admin_can_edit_csv_participant_and_duplicate_email_is_rejected(client, make_user, login, fake_sheet):
    fake_sheet.people = [fake_sheet.make(2, "Alex", "alex@example.com"), fake_sheet.make(3, "Meera", "meera@example.com")]
    make_user(Role.STAFF, "staff-edit@example.com")
    make_user(Role.ADMIN, "admin-edit@example.com")
    changes = {"name": "  Alex   Johnson ", "email": " NEW@Example.com ",
               "team_name": " Team  Nova ", "college": " XYZ   University "}
    login("staff-edit@example.com")
    assert client.patch("/api/participants/2", json=changes).status_code == 403
    login("admin-edit@example.com")
    response = client.patch("/api/participants/2", json=changes)
    assert response.status_code == 200, response.text
    assert {key: response.json()[key] for key in changes} == {
        "name": "Alex Johnson", "email": "new@example.com", "team_name": "Team Nova", "college": "XYZ University"}
    assert client.get("/api/participants/2").json()["college"] == "XYZ University"
    assert client.patch("/api/participants/2", json={**changes, "email": "meera@example.com"}).status_code == 409
    assert client.patch("/api/participants/2", json={**changes, "name": " "}).status_code == 422
    assert client.patch("/api/participants/2", json={**changes, "college": " "}).json()["college"] is None
    assert client.patch("/api/participants/2", json={**changes, "created_at": "2020-01-01"}).status_code == 422


def test_admin_can_add_participant_manually(client, make_user, login):
    make_user(Role.STAFF, "staff-add@example.com")
    make_user(Role.ADMIN, "admin-add@example.com")
    person = {"name": "  Riya   Sen ", "email": " Riya@Example.com ", "team_name": "  ", "college": None}
    login("staff-add@example.com")
    assert client.post("/api/participants", json=person).status_code == 403
    login("admin-add@example.com")
    created = client.post("/api/participants", json=person)
    assert created.status_code == 201, created.text
    assert {key: created.json()[key] for key in person} == {
        "name": "Riya Sen", "email": "riya@example.com", "team_name": None, "college": None}
    listed = client.get("/api/participants", params={"search": "riya@example.com"}).json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == created.json()["id"]
    full = client.post("/api/participants", json={"name": "Dev", "email": "dev@example.com", "team_name": " Team  Nova ", "college": "ABC College"})
    assert full.status_code == 201 and (full.json()["team_name"], full.json()["college"]) == ("Team Nova", "ABC College")
    duplicate = client.post("/api/participants", json={**person, "email": "RIYA@example.COM"})
    assert duplicate.status_code == 409 and "already exists" in duplicate.json()["detail"]
    for invalid in ({**person, "name": " "}, {**person, "email": "not-an-email"}, {**person, "email": ""},
                    {"email": "solo@example.com"}, {**person, "email": "new@example.com", "id": 99},
                    {**person, "email": "long@example.com", "college": "x" * 161}):
        assert client.post("/api/participants", json=invalid).status_code == 422
    edited = client.patch(f"/api/participants/{created.json()['id']}", json={**person, "team_name": "Orbit"})
    assert edited.status_code == 200 and edited.json()["team_name"] == "Orbit"
    # CSV import keeps requiring team and college.
    csv_data = b"name,email,team_name,college\nNo Team,noteam@example.com,,ABC College\n"
    preview = client.post("/api/participants/import/preview", files={"file": ("people.csv", csv_data)}).json()
    assert preview["rows"][0]["status"] == "INVALID" and "Missing team name" in preview["rows"][0]["reason"]
