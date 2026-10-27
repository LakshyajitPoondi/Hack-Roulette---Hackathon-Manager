import csv
import io

import pytest
from sqlalchemy import func, select

from app.models import Participant, Role
from app.models.dataset import Dataset, DatasetParticipant
from app.services import datasets


@pytest.fixture
def admin(client, make_user, login):
    user = make_user(Role.ADMIN, "datasets@example.com")
    login(user.email)
    return user


def upload(client, data, name="October participants"):
    response = client.post("/api/datasets", data={"name": name}, files={"file": ("people.csv", data, "text/csv")})
    assert response.status_code == 201, response.text
    return response.json()


def review_and_import(client, id, approved=()):
    checked = client.post(f"/api/datasets/{id}/preview", json={"approved_rows": list(approved)})
    assert checked.status_code == 200, checked.text
    response = client.post(f"/api/datasets/{id}/import", json={"digest": checked.json()["digest"], "approved_rows": list(approved)})
    assert response.status_code == 200, response.text
    return response.json()


def test_lossless_draft_validation_and_export(client, admin):
    original = (b'name,email,department,notes\r\n'
                b' Rahul ,rahul @gmail.com,CSE,"=2+3"\r\n'
                b'Jane,jane@example.com,cse,"quoted, value"\r\n'
                b'Jane,jane@example.com,cse,"quoted, value"\r\n'
                b',,,\r\n')
    item = upload(client, original)
    id = item["id"]
    assert item["rows"][0]["cells"] == [" Rahul ", "rahul @gmail.com", "CSE", "=2+3"]
    assert any(i["problem"] == "Invalid email format" and i["suggestion"] == "rahul@gmail.com" for i in item["issues"])
    assert any("department" in i["problem"] for i in item["issues"])
    assert any(g["safe"] and g["row_ids"] == [2, 3] for g in item["duplicate_groups"])
    assert client.get(f"/api/datasets/{id}/export?original=true").content == original
    exported = list(csv.reader(io.StringIO(client.get(f"/api/datasets/{id}/export").content.decode("utf-8-sig"))))
    assert exported[1][3] == "'=2+3"
    assert exported[2][3] == "quoted, value"
    plan = client.post(f"/api/datasets/{id}/preview", json={}).json()
    assert (plan["total"], plan["invalid"], plan["duplicates"], plan["ready"]) == (4, 2, 1, 1)
    rows = item["rows"][:2]
    rows[0]["cells"][0:2] = ["Rahul", "rahul@gmail.com"]
    saved = client.patch(f"/api/datasets/{id}/draft", json={"revision": 1, "rows": rows})
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    assert client.patch(f"/api/datasets/{id}/draft", json={"revision": 1, "rows": rows}).status_code == 409
    assert client.get(f"/api/datasets/{id}/export?original=true").content == original
    assert client.get(f"/api/datasets/{id}").json()["rows"] == rows
    updated = client.post(f"/api/datasets/{id}/preview", json={}).json()
    assert (updated["modified"], updated["removed"], updated["ready"]) == (1, 2, 2)
    assert client.post(f"/api/datasets/{id}/import", json={"digest": plan["digest"]}).status_code == 409
    assert client.get("/api/participants/all").json() == []


def test_persistent_datasets_reuse_ids_and_shared_email(client, db, admin):
    one = upload(client, b"name,email,college\nJohn,shared@example.com,First\nJonathan,shared@example.com,Second\nJohn,shared@example.com,Other\n")
    id = one["id"]
    plan = client.post(f"/api/datasets/{id}/preview", json={}).json()
    assert [r["status"] for r in plan["rows"]] == ["READY", "REVIEW", "DUPLICATE"]
    # An approval list cannot be added to an older review digest without reviewing it.
    assert client.post(f"/api/datasets/{id}/import", json={"digest": plan["digest"], "approved_rows": [2]}).status_code == 409
    assert review_and_import(client, id, [2])["linked"] == 2
    people = client.get("/api/participants/all").json()
    assert len(people) == 2 and people[0]["id"] != people[1]["id"]
    two = upload(client, b"name,email,college\nJohn,shared@example.com,Changed\nNew Person,new@example.com,Third\n", "Another campaign")
    assert review_and_import(client, two["id"], [1])["linked"] == 2
    assert len(client.get("/api/participants/all").json()) == 3
    again = review_and_import(client, two["id"], [1])
    assert again["linked"] == 0
    john = db.scalar(select(Participant).where(Participant.name == "John"))
    assert john.college == "First"  # Uploading another collection cannot overwrite an existing recipient.
    assert db.scalar(select(func.count()).select_from(DatasetParticipant)) == 4
    assert len(client.get("/api/participants/all", params={"dataset_id": id}).json()) == 2
    assert client.get("/api/participants", params={"dataset_id": two["id"]}).json()["total"] == 2
    assert client.patch(f"/api/datasets/{id}", json={"name": "Renamed"}).status_code == 200
    assert client.get("/api/datasets").json()[-1]["name"] == "Renamed"
    assert all(d["participant_count"] == 2 for d in client.get("/api/datasets").json())
    assert client.post(f"/api/datasets/{id}/archive").status_code == 200
    assert client.post(f"/api/datasets/{id}/preview", json={}).status_code == 409
    assert client.patch(f"/api/datasets/{id}/draft", json={"revision": 1, "rows": one["rows"]}).status_code == 409
    assert db.scalar(select(func.count()).select_from(Participant)) == 3
    assert client.post(f"/api/datasets/{id}/archive?archived=false").status_code == 200


def test_dataset_validation_limits_rbac_and_row_ids(client, admin, make_user, login):
    item = upload(client, b"name,email\nAlice,alice@example.com\n")
    id = item["id"]
    for rows in ([{"id": 2, "cells": ["Eve", "eve@example.com"]}],
                 [item["rows"][0], item["rows"][0]], [{"id": 1, "cells": ["Alice"]}],
                 [{"id": 1, "cells": ["x" * 10001, "alice@example.com"]}]):
        assert client.patch(f"/api/datasets/{id}/draft", json={"revision": 1, "rows": rows}).status_code == 422
    for data in (b"name,email\n\xff,a@example.com", b'name,email\n"unclosed,x@example.com',
                 b"name,email\nA,a@example.com,unexpected", b"name,email,email\nA,a@example.com,a@example.com",
                 b"name\nA", b"name,email\nA,\x00", b"name,email\n" + b"A,a@example.com\n" * 5001):
        response = client.post("/api/datasets", data={"name": "Bad"}, files={"file": ("bad.csv", data)})
        assert response.status_code == 422, response.text
    assert client.post("/api/datasets", data={"name": " "}, files={"file": ("a.csv", b"name,email\nA,a@example.com")}).status_code == 422
    assert client.patch(f"/api/datasets/{id}", json={"name": " "}).status_code == 422
    make_user(Role.STAFF, "dataset-staff@example.com"); login("dataset-staff@example.com")
    assert client.get("/api/datasets").status_code == 403
    assert client.get(f"/api/datasets/{id}/export?original=true").status_code == 403
    assert client.post(f"/api/datasets/{id}/import", json={"digest": "anything"}).status_code == 403
    assert client.patch(f"/api/datasets/{id}/draft", json={"revision": 1, "rows": []}).status_code == 403


def test_legacy_import_is_also_saved(client, db, admin):
    data = b"name,email\nLegacy,legacy@example.com\n"
    preview = client.post("/api/participants/import/preview", files={"file": ("legacy.csv", data)}).json()
    response = client.post("/api/participants/import", data={"digest": preview["digest"]}, files={"file": ("legacy.csv", data)})
    assert response.status_code == 200, response.text
    item = db.scalar(select(Dataset))
    assert item.original_data == data
    assert db.scalar(select(func.count()).select_from(DatasetParticipant)) == 1


def test_formula_export_and_size_limits():
    for value in ("=SUM(A1)", " +1", "-2", "@X", "\tformula", "\rtest", "\ntest"):
        output = datasets.export([value], [{"id": 1, "cells": [value]}]).decode("utf-8-sig")
        assert list(csv.reader(io.StringIO(output)))[0][0].startswith("'")
    with pytest.raises(Exception) as exc:
        datasets.parse(b"x" * (datasets.MAX_CSV_BYTES + 1))
    assert exc.value.status_code == 422


def test_abbreviation_warnings_do_not_guess_department_replacements():
    headers = ["name", "email", "department"]
    rows = [{"id": 1, "cells": ["One", "one@example.com", "CSE"]},
            {"id": 2, "cells": ["Two", "two@example.com", "Computer Science and Engineering"]},
            {"id": 3, "cells": ["Three", "three@example.com", "CSE-AI"]}]
    report = datasets.analyze(headers, rows)
    warnings = [i for i in report["issues"] if "department" in i["problem"]]
    assert {i["row_id"] for i in warnings} == {1, 2}
    assert all(i["suggestion"] is None for i in warnings)


def test_dataset_body_limits_apply_before_parsing(client, admin):
    response = client.post("/api/datasets", content=b"x" * (2 * datasets.MAX_CSV_BYTES + 1024 * 1024 + 1),
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert client.get("/api/datasets").json() == []
