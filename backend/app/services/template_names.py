from fastapi import HTTPException
from sqlalchemy import func, select, text


def validate_name(db, model, name, exclude_id=None):
    clean = name.strip()
    if not clean or len(clean) > 160:
        raise HTTPException(422, "Template name must contain 1–160 characters")
    # Serialize conflicting API writes without renaming any pre-existing duplicate names in production.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                   {"key": f"template-name:{model.__tablename__}:{clean.lower()}"})
    query = select(model.id).where(func.lower(func.trim(model.name)) == clean.lower())
    if exclude_id is not None:
        query = query.where(model.id != exclude_id)
    if db.scalar(query.limit(1)) is not None:
        raise HTTPException(409, "A template with this name already exists")
    return clean
