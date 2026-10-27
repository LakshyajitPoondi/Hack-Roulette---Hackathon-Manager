"""Preview and import a small, explicit CSV participant list."""
import csv
import hashlib
import io
import re

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.participant import Participant, identity_part

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
        # Everyone already holding each email: existing participants, then importable earlier rows of this file.
        by_email: dict[str, list[dict]] = {}
        for person in db.scalars(select(Participant).order_by(Participant.id)):
            by_email.setdefault(identity_part(person.email), []).append(
                {"source": "existing", "id": person.id, "line": None, "name": person.name, "email": person.email,
                 "team_name": person.team_name, "college": person.college})
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
            status, reason, matches = "INVALID", "; ".join(reasons), []
            if not reasons:
                email_key = identity_part(values["email"])
                earlier = list(by_email.get(email_key, []))
                exact = next((match for match in earlier if identity_part(match["name"]) == identity_part(values["name"])), None)
                if exact:
                    # Same name and email: never imported, whatever the team or college.
                    status, matches = "DUPLICATE", [exact]
                    reason = (f"Same name and email as existing participant #{exact['id']}" if exact["source"] == "existing"
                              else f"Same name and email as line {exact['line']}")
                elif earlier:
                    status, matches = "REVIEW", earlier
                    reason = "Email already used by " + ", ".join(
                        f"{match['name']} (participant #{match['id']})" if match["source"] == "existing"
                        else f"{match['name']} (line {match['line']})" for match in earlier)
                else:
                    status, reason = "VALID", ""
                if status != "DUPLICATE":
                    by_email.setdefault(email_key, []).append(
                        {"source": "csv", "id": None, "line": reader.line_num, **{key: values[key] or None for key in FIELDS}})
            rows.append({"line": reader.line_num, **values, "status": status, "reason": reason, "matches": matches})
    except csv.Error as exc:
        raise HTTPException(422, f"Malformed CSV: {exc}") from None
    except StopIteration:
        raise HTTPException(422, "CSV is empty") from None
    if not rows:
        raise HTTPException(422, "CSV contains no participant rows")
    return {"digest": hashlib.sha256(data).hexdigest(), "rows": rows,
            "valid": sum(row["status"] == "VALID" for row in rows),
            "review": sum(row["status"] == "REVIEW" for row in rows),
            "duplicates": sum(row["status"] == "DUPLICATE" for row in rows),
            "invalid": sum(row["status"] == "INVALID" for row in rows)}


def import_rows(db: Session, data: bytes, expected_digest: str, approved_lines: set[int] = frozenset(), *, commit=True) -> dict:
    """Import new rows, plus REVIEW rows whose line the admin approved. Exact duplicates are never imported."""
    if hashlib.sha256(data).hexdigest() != expected_digest:
        raise HTTPException(409, "CSV changed after preview. Preview it again.")
    # Re-check against the database now; a row only counts as reviewed if it is still REVIEW and was approved.
    result = preview(db, data)
    new = [row for row in result["rows"] if row["status"] == "VALID"]
    reviewed = [row for row in result["rows"] if row["status"] == "REVIEW" and row["line"] in approved_lines]
    inserted: set[tuple[str, str]] = set()
    if new or reviewed:
        values = [{key: row[key] or None for key in FIELDS} for row in new + reviewed]
        if db.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        # The name+email unique index skips any exact duplicate created concurrently.
        statement = insert(Participant).values(values).on_conflict_do_nothing().returning(Participant.email, Participant.name)
        inserted = {(identity_part(email), identity_part(name)) for email, name in db.execute(statement).all()}
        if commit:
            db.commit()
    was_inserted = lambda row: (identity_part(row["email"]), identity_part(row["name"])) in inserted
    imported_new = sum(map(was_inserted, new))
    imported_reviewed = sum(map(was_inserted, reviewed))
    return {"imported": imported_new + imported_reviewed, "imported_new": imported_new, "imported_reviewed": imported_reviewed,
            "review_skipped": result["review"] - imported_reviewed,
            "duplicates": result["duplicates"] + len(new) - imported_new, "invalid": result["invalid"]}
