"""Certificate font families. The editor preview and the PDF read the same TTF files."""
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = Path(__file__).resolve().parents[1] / "fonts"
STYLES = ("regular", "bold", "italic", "bold_italic")
HELVETICA_PREVIEW = "Arial, 'Liberation Sans', Helvetica, sans-serif"
_lock = Lock()


@dataclass(frozen=True)
class FontFamily:
    label: str
    category: str
    # style -> built-in PDF font name, or a TTF file in FONT_DIR
    faces: dict[str, str]
    builtin: bool = False
    # Family whose TTF files the browser previews a built-in font with
    preview_family: str | None = None


def _files(prefix: str, *styles: str) -> dict[str, str]:
    suffix = {"regular": "Regular", "bold": "Bold", "italic": "Italic", "bold_italic": "BoldItalic"}
    return {style: f"{prefix}-{suffix[style]}.ttf" for style in styles}


FAMILIES: dict[str, FontFamily] = {
    "helvetica": FontFamily("Helvetica", "Sans-serif", {"regular": "Helvetica", "bold": "Helvetica-Bold",
        "italic": "Helvetica-Oblique", "bold_italic": "Helvetica-BoldOblique"}, builtin=True),
    "montserrat": FontFamily("Montserrat", "Sans-serif", _files("Montserrat", *STYLES)),
    "times": FontFamily("Times", "Serif", {"regular": "Times-Roman", "bold": "Times-Bold",
        "italic": "Times-Italic", "bold_italic": "Times-BoldItalic"}, builtin=True, preview_family="liberation-serif"),
    "liberation-serif": FontFamily("Liberation Serif", "Serif", _files("LiberationSerif", *STYLES)),
    "playfair-display": FontFamily("Playfair Display", "Serif", _files("PlayfairDisplay", *STYLES)),
    "eb-garamond": FontFamily("EB Garamond", "Serif", _files("EBGaramond", *STYLES)),
    "cinzel": FontFamily("Cinzel", "Serif", _files("Cinzel", "regular", "bold")),
    "great-vibes": FontFamily("Great Vibes", "Script", _files("GreatVibes", "regular")),
    "pinyon-script": FontFamily("Pinyon Script", "Script", _files("PinyonScript", "regular")),
}


def style_name(bold: bool, italic: bool) -> str:
    return "bold_italic" if bold and italic else "bold" if bold else "italic" if italic else "regular"


def supports(family: str, bold: bool, italic: bool) -> bool:
    return family in FAMILIES and style_name(bold, italic) in FAMILIES[family].faces


def pdf_font(family: str, bold: bool, italic: bool) -> str:
    """Return a ReportLab font name, registering (and so embedding) TTF faces on first use."""
    entry = FAMILIES.get(family) or FAMILIES["helvetica"]
    style = style_name(bold, italic)
    if style not in entry.faces:
        # Saved settings are validated; this only guards rows edited outside the app.
        style = next(s for s in (style_name(bold, False), style_name(False, italic), "regular") if s in entry.faces)
    face = entry.faces[style]
    if entry.builtin:
        return face
    name = f"cert-{family}-{style}"
    with _lock:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / face)))
    return name


def font_file(family: str, style: str) -> Path | None:
    entry = FAMILIES.get(family)
    if entry is None or entry.builtin or style not in entry.faces:
        return None
    return FONT_DIR / entry.faces[style]


def catalog() -> list[dict]:
    """Families for the editor, with the URLs the browser loads each preview face from."""
    items = []
    for key, entry in FAMILIES.items():
        source = entry.preview_family or (None if entry.builtin else key)
        items.append({"key": key, "label": entry.label, "category": entry.category, "styles": list(entry.faces),
                      "preview_files": {style: f"/api/certificates/fonts/{source}/{style}" for style in entry.faces} if source else {},
                      "preview_fallback": HELVETICA_PREVIEW if key == "helvetica"
                      else {"Sans-serif": "sans-serif", "Serif": "serif", "Script": "cursive"}[entry.category]})
    return items
