"""Lossless CSV drafts and explicit, transactional participant collection imports."""
import csv
import hashlib
import io
import json
import re

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dataset import Dataset, DatasetParticipant
from app.models.participant import Participant, identity_part
from app.services.csv_participants import FIELDS, MAX_CSV_BYTES, MAX_ROWS, _header, _text

MAX_COLUMNS = 100
MAX_CELL = 10000


def department_key(value):
    words = [w for w in re.findall(r"[^\W\d_]+", value.casefold()) if w not in {"and", "of", "the", "department", "dept"}]
    if len(words) > 1 and all(len(w) >= 3 for w in words):
        return "".join(w[0] for w in words)
    return re.sub(r"[^\w]", "", value).casefold()


def parse(data: bytes):
    if not data or len(data) > MAX_CSV_BYTES:
        raise HTTPException(422, "CSV must be nonempty and at most 5 MB")
    try:
        content = data.decode("utf-8-sig")
        if "\x00" in content:
            raise ValueError("NUL characters are not allowed")
        reader = csv.reader(io.StringIO(content, newline=""), strict=True)
        headers = next(reader)
        if not headers or len(headers) > MAX_COLUMNS or any(not h.strip() for h in headers):
            raise ValueError("Use 1–100 nonempty column headings")
        if len(set(map(_header, headers))) != len(headers):
            raise ValueError("Column headings must be distinct")
        rows = []
        for cells in reader:
            if len(rows) >= MAX_ROWS:
                raise ValueError("CSV may contain at most 5000 rows, including empty rows")
            if len(cells) > len(headers):
                raise ValueError(f"Row ending at line {reader.line_num} has extra columns; fix the CSV before uploading")
            # A short/empty record stays visible and editable instead of disappearing.
            cells += [""] * (len(headers) - len(cells))
            if any(len(c) > MAX_CELL for c in cells):
                raise ValueError("CSV cells may contain at most 10000 characters")
            rows.append({"id": len(rows) + 1, "cells": cells})
        if not rows:
            raise ValueError("CSV contains no data rows")
        if any(len(h) > 160 for h in headers):
            raise ValueError("Column headings may contain at most 160 characters")
        return headers, rows
    except (UnicodeDecodeError, csv.Error, StopIteration, ValueError) as exc:
        raise HTTPException(422, f"Invalid UTF-8 CSV: {str(exc)[:180]}") from None


def columns(headers):
    result = {}
    for field, aliases in FIELDS.items():
        matches = [i for i, h in enumerate(headers) if _header(h) in aliases]
        if len(matches) > 1 or (field in {"name", "email"} and not matches):
            raise HTTPException(422, f"CSV needs exactly one {field} column")
        if matches:
            result[field] = matches[0]
    return result


def analyze(headers, rows):
    mapped = columns(headers)
    issues, groups = [], []
    exact, identities, emails, departments = {}, {}, {}, {}
    department_columns = [i for i, h in enumerate(headers) if _header(h) in {"department", "dept", "department name"}]
    by_id = {r["id"]: r for r in rows}

    def issue(row, column, severity, problem, suggestion=None):
        issues.append({"row_id": row["id"], "column": column, "severity": severity,
                       "problem": problem, "value": row["cells"][column] if column is not None else "",
                       "suggestion": suggestion})

    for row in rows:
        cells = row["cells"]
        exact.setdefault(tuple(cells), []).append(row["id"])
        if not any(c.strip() for c in cells):
            issue(row, None, "error", "Empty row")
        for i, cell in enumerate(cells):
            if cell != cell.strip():
                issue(row, i, "warning", "Leading or trailing whitespace", cell.strip())
            if any(ord(c) < 32 and c not in "\r\n\t" for c in cell):
                issue(row, i, "error", "Unexpected control character")
            if "\n" in cell or "\t" in cell or "  " in cell:
                issue(row, i, "warning", "Suspicious spacing or multiline value")
        name, email = (cells[mapped[f]].strip() for f in ("name", "email"))
        for field in FIELDS:
            value = cells[mapped[field]] if field in mapped else ""
            if field in {"name", "email"} and not value.strip():
                issue(row, mapped[field], "error", f"Missing required {field}")
            if len(_text(value)) > (320 if field == "email" else 160):
                issue(row, mapped[field], "error", f"{field} is too long")
        if email:
            try:
                validate_email(email, check_deliverability=False)
            except EmailNotValidError:
                compact = re.sub(r"\s", "", email)
                suggestion = None
                if compact != email:
                    try:
                        validate_email(compact, check_deliverability=False)
                        suggestion = compact
                    except EmailNotValidError:
                        pass
                issue(row, mapped["email"], "error", "Invalid email format", suggestion)
        if name and email:
            identities.setdefault((identity_part(_text(name)), identity_part(email)), []).append(row["id"])
            emails.setdefault(identity_part(email), []).append(row["id"])
        for i in department_columns:
            key = department_key(cells[i])
            if key:
                departments.setdefault((i, key), {}).setdefault(cells[i], []).append(row["id"])
    for reason, index in (("Exact duplicate row (all columns match)", exact),
                          ("Same normalized participant name and email", identities),
                          ("Shared email: may be distinct participants; review before import", emails)):
        for ids in index.values():
            if len(ids) > 1:
                groups.append({"reason": reason, "row_ids": ids, "safe": index is exact})
    for (i, _), variants in departments.items():
        if len(variants) > 1:
            for ids in variants.values():
                for row_id in ids:
                    row = by_id[row_id]
                    issue(row, i, "warning", "Inconsistent department naming (case, spacing or abbreviation); choose a value manually")
    return {"issues": issues, "duplicate_groups": groups}


def import_preview(db: Session, dataset: Dataset, approved: set[int] = frozenset()):
    report = analyze(dataset.headers, dataset.rows)
    mapped = columns(dataset.headers)
    invalid = {i["row_id"] for i in report["issues"] if i["severity"] == "error"}
    people = list(db.scalars(select(Participant).order_by(Participant.id)))
    existing = {p.identity: p for p in people}
    email_owners = {}
    for p in people:
        email_owners.setdefault(identity_part(p.email), set()).add(identity_part(p.name))
    seen, plan = set(), []
    for row in dataset.rows:
        values = {f: _text(row["cells"][mapped[f]]) if f in mapped else "" for f in FIELDS}
        key = identity_part(values["email"]), identity_part(values["name"])
        status, reason, person = "READY", "", existing.get(key)
        if row["id"] in invalid:
            status, reason = "INVALID", "Correct the row errors before importing"
        elif key in seen:
            status, reason = "DUPLICATE", "Repeated name and email in this dataset; keep one row"
        else:
            values["email"] = validate_email(values["email"], check_deliverability=False).normalized.casefold()
            if person:
                reason = f"Reuse participant #{person.id}; existing participant details remain unchanged"
            if email_owners.get(key[0], set()) - {key[1]}:
                status = "READY" if row["id"] in approved else "REVIEW"
                reason += ("; " if reason else "") + "Shared email: confirm this is a separate participant"
            seen.add(key)
            email_owners.setdefault(key[0], set()).add(key[1])
        plan.append({"row_id": row["id"], "status": status, "reason": reason,
                     "participant_id": person.id if person else None, **values})
    original = {r["id"]: r["cells"] for r in dataset.original_rows}
    modified = sum(original.get(r["id"]) != r["cells"] for r in dataset.rows)
    digest = hashlib.sha256(json.dumps([dataset.id, dataset.revision, plan], sort_keys=True).encode()).hexdigest()
    return {"digest": digest, "rows": plan, "total": len(plan), "modified": modified,
            "removed": len(dataset.original_rows) - len(dataset.rows),
            "valid": sum(r["status"] != "INVALID" for r in plan),
            "invalid": sum(r["status"] == "INVALID" for r in plan),
            "duplicates": sum(r["status"] == "DUPLICATE" for r in plan),
            "review": sum(r["status"] == "REVIEW" for r in plan),
            "ready": sum(r["status"] == "READY" for r in plan)}


def import_dataset(db: Session, dataset: Dataset, digest: str, approved: set[int]):
    result = import_preview(db, dataset, approved)
    if digest != result["digest"]:
        raise HTTPException(409, "Dataset or participants changed. Review the import again.")
    ready = [r for r in result["rows"] if r["status"] == "READY"]
    if not ready:
        raise HTTPException(422, "No eligible rows to import")
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    values = [{f: row[f] or None for f in FIELDS} for row in ready if row["participant_id"] is None]
    if values:
        db.execute(insert(Participant).values(values).on_conflict_do_nothing())
    people = {p.identity: p.id for p in db.scalars(select(Participant))}
    ids = {people[(identity_part(r["email"]), identity_part(r["name"]))] for r in ready}
    old = set(db.scalars(select(DatasetParticipant.participant_id).where(DatasetParticipant.dataset_id == dataset.id)))
    # Imports only add membership; editing a draft never removes historical membership or changes a person's details.
    db.execute(insert(DatasetParticipant).values([{"dataset_id": dataset.id, "participant_id": id} for id in ids]).on_conflict_do_nothing())
    db.commit()
    return {"linked": len(ids - old), "reused": sum(r["participant_id"] is not None for r in ready), "eligible": len(ready)}


def export(headers, rows, *, protect_formulas=True):
    def safe(value):
        # CSV quoting alone does not prevent spreadsheet formula execution.
        return "'" + value if protect_formulas and (value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@"))) else value
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([safe(h) for h in headers])
    writer.writerows([safe(c) for c in row["cells"]] for row in rows)
    return output.getvalue().encode("utf-8-sig")
