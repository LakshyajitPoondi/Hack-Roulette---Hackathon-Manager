import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_role
from app.db.session import get_db
from app.models.dataset import Dataset, DatasetParticipant
from app.models.user import Role, User
from app.services import datasets as service
from app.services.csv_participants import MAX_CSV_BYTES, MAX_ROWS

class LimitedDatasetRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def limited(request: Request):
            # Bound JSON/multipart memory before FastAPI parses it, including chunked requests.
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 2 * MAX_CSV_BYTES + 1024 * 1024:
                    return JSONResponse({"detail": "Dataset request is too large"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
            return await handler(request)
        return limited


router = APIRouter(prefix="/api/datasets", tags=["datasets"], route_class=LimitedDatasetRoute)
Database = Annotated[Session, Depends(get_db)]
Admin = Annotated[User, Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN))]


class Rename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("A name is required")
        return value.strip()


class Row(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(ge=1, le=MAX_ROWS)
    cells: list[str] = Field(max_length=service.MAX_COLUMNS)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    rows: list[Row] = Field(max_length=MAX_ROWS)


class ImportReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    digest: str | None = Field(default=None, max_length=64)
    approved_rows: list[int] = Field(default_factory=list, max_length=MAX_ROWS)


def get_dataset(db, id, *, lock=False):
    item = db.scalar(select(Dataset).where(Dataset.id == id).with_for_update()) if lock else db.get(Dataset, id)
    if item is None:
        raise HTTPException(404, "Dataset not found")
    return item


def summary(db, item):
    count = db.scalar(select(func.count()).select_from(DatasetParticipant).where(DatasetParticipant.dataset_id == item.id))
    return {"id": item.id, "name": item.name, "original_filename": item.original_filename,
            "created_at": item.created_at, "participant_count": count, "row_count": len(item.rows),
            "archived": item.archived, "revision": item.revision, "is_legacy": item.is_legacy}


def detail(db, item):
    return {**summary(db, item), "headers": item.headers, "rows": item.rows, "original_rows": item.original_rows,
            **service.analyze(item.headers, item.rows)}


@router.get("")
def list_datasets(db: Database, _: Admin):
    # Large draft/original bytes are excluded from the dataset picker query.
    counts = (select(DatasetParticipant.dataset_id, func.count().label("count"))
              .group_by(DatasetParticipant.dataset_id).subquery())
    items = db.execute(select(Dataset.id, Dataset.name, Dataset.original_filename, Dataset.created_at,
                              Dataset.archived, Dataset.revision, Dataset.is_legacy, counts.c.count)
                       .outerjoin(counts, Dataset.id == counts.c.dataset_id).order_by(Dataset.id.desc()))
    return [{**dict(row._mapping), "participant_count": row._mapping["count"] or 0} for row in items]


@router.post("", status_code=201)
async def upload_dataset(db: Database, actor: Admin, name: str = Form(..., min_length=1, max_length=160),
                         file: UploadFile = File(...)):
    clean = name.strip()
    if not clean:
        raise HTTPException(422, "A dataset name is required")
    data = await file.read(MAX_CSV_BYTES + 1)
    headers, rows = service.parse(data)
    service.columns(headers)
    item = Dataset(name=clean, original_filename=(file.filename or "upload.csv")[:255], original_data=data,
                   headers=headers, original_rows=rows, rows=rows, created_by=actor.id)
    db.add(item); db.commit(); db.refresh(item)
    return detail(db, item)


@router.get("/{id}")
def read_dataset(id: int, db: Database, _: Admin):
    return detail(db, get_dataset(db, id))


@router.patch("/{id}")
def rename_dataset(id: int, payload: Rename, db: Database, _: Admin):
    item = get_dataset(db, id, lock=True)
    item.name = payload.name
    db.commit()
    return summary(db, item)


@router.post("/{id}/archive")
def archive_dataset(id: int, db: Database, _: Admin, archived: bool = True):
    item = get_dataset(db, id, lock=True)
    item.archived = archived
    db.commit()
    return summary(db, item)


@router.patch("/{id}/draft")
def save_draft(id: int, payload: Draft, db: Database, _: Admin):
    item = get_dataset(db, id, lock=True)
    if item.archived:
        raise HTTPException(409, "Restore this dataset before editing")
    if payload.revision != item.revision:
        raise HTTPException(409, "Another editor saved this dataset. Reload it before saving.")
    rows = [row.model_dump() for row in payload.rows]
    allowed_ids = {r["id"] for r in item.original_rows}
    if len({r["id"] for r in rows}) != len(rows) or any(r["id"] not in allowed_ids for r in rows):
        raise HTTPException(422, "Row IDs must be distinct original row IDs")
    if any(len(r["cells"]) != len(item.headers) or any(len(c) > service.MAX_CELL or "\x00" in c for c in r["cells"]) for r in rows):
        raise HTTPException(422, "Invalid row width or cell value")
    if len(json.dumps(rows, ensure_ascii=False).encode()) > 2 * MAX_CSV_BYTES:
        raise HTTPException(422, "Edited dataset is too large")
    item.rows = rows
    item.revision += 1
    db.commit()
    return detail(db, item)


@router.post("/{id}/preview")
def preview_import(id: int, payload: ImportReview, db: Database, _: Admin):
    item = get_dataset(db, id)
    if item.archived:
        raise HTTPException(409, "Restore this dataset before importing")
    return service.import_preview(db, item, set(payload.approved_rows))


@router.post("/{id}/import")
def import_dataset(id: int, payload: ImportReview, db: Database, _: Admin):
    item = get_dataset(db, id, lock=True)
    if item.archived:
        raise HTTPException(409, "Restore this dataset before importing")
    return service.import_dataset(db, item, payload.digest, set(payload.approved_rows))


@router.get("/{id}/export")
def export_dataset(id: int, db: Database, _: Admin, original: bool = False):
    item = get_dataset(db, id)
    # The original is immutable evidence, downloaded as text to discourage spreadsheet execution.
    data = bytes(item.original_data) if original else service.export(item.headers, item.rows)
    return Response(data, media_type="text/plain" if original else "text/csv",
                    headers={"Content-Disposition": f'attachment; filename="dataset-{id}{"-original.txt" if original else ".csv"}"',
                             "X-Content-Type-Options": "nosniff"})
