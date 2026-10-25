"""Preview and import a small, explicit CSV participant list."""
import csv
import hashlib
import io
import re

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.participant import Participant

MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
FIELDS = {
    "name": {"name", "participant name", "full name"},
    "email": {"email", "email address", "participant email"},
    "team_name": {"team", "team name"},
    "college": {"college", "college name", "institution"},
}
REQUIRED = ("name", "email")


def _header(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ").replace("-", " ").strip().casefold())


def _text(value: str) -> str:
    return " ".join(value.split())


def preview(db: Session, data: bytes) -> dict:
    if not data or len(data) > MAX_CSV_BYTES:
        raise HTTPException(422, "CSV must be nonempty and at most 5 MB")
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "CSV must be UTF-8 encoded") from None
    try:
        reader = csv.reader(io.StringIO(content, newline=""), strict=True)
        headers = next(reader)
        columns = {}
        for field, aliases in FIELDS.items():
            matches = [i for i, value in enumerate(headers) if _header(value) in aliases]
            if len(matches) > 1 or (field in REQUIRED and not matches):
                raise HTTPException(422, f"CSV needs exactly one {field.replace('_', ' ')} column"
                                    if field in REQUIRED else f"CSV has more than one {field.replace('_', ' ')} column")
            if matches:
                columns[field] = matches[0]
        existing = set(db.scalars(select(Participant.email)))
        seen = set()
        rows = []
        for raw in reader:
            if not any(cell.strip() for cell in raw):
                continue
            if len(rows) >= MAX_ROWS:
                raise HTTPException(422, "CSV may contain at most 5000 participant rows")
            # Team name and college are optional: a missing column or blank cell becomes "".
            values = {field: _text(raw[columns[field]]) if field in columns and columns[field] < len(raw) else ""
                      for field in FIELDS}
            reasons = []
            if len(raw) != len(headers):
                reasons.append("Wrong number of columns")
            for field in FIELDS:
                if not values[field]:
                    if field in REQUIRED:
                        reasons.append(f"Missing {field.replace('_', ' ')}")
                elif len(values[field]) > (320 if field == "email" else 160):
                    reasons.append(f"{field.replace('_', ' ').capitalize()} is too long")
            if values["email"] and len(values["email"]) <= 320:
                try:
                    values["email"] = validate_email(values["email"], check_deliverability=False).normalized.casefold()
                except EmailNotValidError:
                    reasons.append("Invalid email")
            duplicate = False
            if not reasons:
                duplicate = values["email"] in seen or values["email"] in existing
                seen.add(values["email"])
            rows.append({"line": reader.line_num, **values, "status": "INVALID" if reasons else "DUPLICATE" if duplicate else "VALID",
                         "reason": "; ".join(reasons) if reasons else "Duplicate email" if duplicate else ""})
    except csv.Error as exc:
        raise HTTPException(422, f"Malformed CSV: {exc}") from None
    except StopIteration:
        raise HTTPException(422, "CSV is empty") from None
    if not rows:
        raise HTTPException(422, "CSV contains no participant rows")
    return {"digest": hashlib.sha256(data).hexdigest(), "rows": rows,
            "valid": sum(row["status"] == "VALID" for row in rows),
            "duplicates": sum(row["status"] == "DUPLICATE" for row in rows),
            "invalid": sum(row["status"] == "INVALID" for row in rows)}


def import_rows(db: Session, data: bytes, expected_digest: str) -> dict:
    if hashlib.sha256(data).hexdigest() != expected_digest:
        raise HTTPException(409, "CSV changed after preview. Preview it again.")
    result = preview(db, data)
    valid = [row for row in result["rows"] if row["status"] == "VALID"]
    if valid:
        values = [{key: row[key] or None for key in FIELDS} for row in valid]
        if db.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        statement = insert(Participant).values(values).on_conflict_do_nothing(index_elements=[Participant.email]).returning(Participant.id)
        imported = len(db.scalars(statement).all())
        db.commit()
    else:
        imported = 0
    return {"imported": imported, "duplicates": result["duplicates"] + len(valid) - imported,
            "invalid": result["invalid"]}
