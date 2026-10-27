import io
from types import SimpleNamespace

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.certificate import CertificateTemplate
from app.services.certificate_fonts import pdf_font

MAX_TEMPLATE_BYTES = 10 * 1024 * 1024


def validate_template(data: bytes) -> str:
    if not data or len(data) > MAX_TEMPLATE_BYTES:
        raise HTTPException(422, "Template must be between 1 byte and 10 MB")
    if data.startswith(b"%PDF-"):
        try:
            reader = PdfReader(io.BytesIO(data))
            if len(reader.pages) != 1 or reader.is_encrypted: raise ValueError()
            return "pdf"
        except Exception:
            raise HTTPException(422, "Upload a readable, single-page PDF") from None
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"PNG", "JPEG"}: raise ValueError()
            image.verify(); return "png" if image.format == "PNG" else "jpg"
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(422, "Upload a valid PNG, JPG, or single-page PDF") from None


def active_template(db: Session) -> CertificateTemplate:
    template = db.scalar(select(CertificateTemplate).where(CertificateTemplate.is_active.is_(True)))
    if not template: raise HTTPException(409, "No active certificate template. Activate one first.")
    return template


def get_template(db: Session, template_id: int) -> CertificateTemplate:
    template = db.get(CertificateTemplate, template_id)
    if not template: raise HTTPException(404, "Template not found")
    return template


def selected_template(db: Session, template_id: int | None):
    return get_template(db, template_id) if template_id is not None else active_template(db)


def snapshot_template(template):
    omitted = {"id", "file_data", "created_at", "updated_at", "created_by", "is_active"}
    return {c.name: getattr(template, c.name) for c in CertificateTemplate.__table__.columns if c.name not in omitted}


def campaign_template(db, campaign):
    if campaign.certificate_snapshot is not None:
        return SimpleNamespace(**campaign.certificate_snapshot, file_data=campaign.certificate_file_data)
    # Compatibility for unmigrated legacy campaigns. New campaigns always have an immutable snapshot.
    return get_template(db, campaign.certificate_template_id)


def cased(template: CertificateTemplate | None, field: str, text: str) -> str:
    """Apply the template's uppercase setting for one field (name, college or team)."""
    return text.upper() if template is not None and getattr(template, f"{field}_uppercase") else text


def placeholder_values(template: CertificateTemplate | None, name: str, college: str | None) -> dict[str, str]:
    """Email placeholder values for a certificate email, cased like the certificate. Pass None for plain emails."""
    return {"participant_name": cased(template, "name", name), "college_name": cased(template, "college", college or "")}


def render_pdf(template: CertificateTemplate, name: str, college: str | None, team: str | None = None, *,
               include_college: bool | None = None, include_team: bool | None = None) -> bytes:
    """Overlay the participant's details. Include flags default to the template's saved settings."""
    include_college = template.include_college if include_college is None else include_college
    include_team = template.include_team if include_team is None else include_team
    if template.file_data is None:
        raise HTTPException(503, "Template file is unavailable; upload or replace the template")
    data = bytes(template.file_data)
    output = io.BytesIO()
    if template.file_type == "pdf":
        original = PdfReader(io.BytesIO(data)); page = original.pages[0]
        width, height = float(page.mediabox.width), float(page.mediabox.height)
    else:
        with Image.open(io.BytesIO(data)) as image: width, height = map(float, image.size)
    overlay = io.BytesIO(); pdf = canvas.Canvas(overlay, pagesize=(width, height))
    if template.file_type != "pdf":
        from reportlab.lib.utils import ImageReader
        pdf.drawImage(ImageReader(io.BytesIO(data)), 0, 0, width=width, height=height)
    def line(text: str, field: str):
        value = lambda key: getattr(template, f"{field}_{key}")
        font = pdf_font(value("font_family"), value("bold"), value("italic"))
        return cased(template, field, text), value("x"), value("y"), value("font_size"), value("alignment"), value("color"), font

    lines = [line(name, "name")]
    # A missing value is skipped entirely, even when its line is included.
    if include_college and college and college.strip():
        lines.append(line(college, "college"))
    if include_team and team and team.strip():
        lines.append(line(team, "team"))
    for text, x_percent, y_percent, size, alignment, color, font in lines:
        pdf.setFillColor(HexColor(color)); pdf.setFont(font, size)
        draw = {"left": pdf.drawString, "center": pdf.drawCentredString, "right": pdf.drawRightString}[alignment]
        draw(width * x_percent / 100, height * (1 - y_percent / 100), text)
    pdf.save(); overlay.seek(0)
    if template.file_type == "pdf":
        writer = PdfWriter(); writer.add_page(page); writer.pages[0].merge_page(PdfReader(overlay).pages[0]); writer.write(output)
    else: output.write(overlay.getvalue())
    return output.getvalue()
