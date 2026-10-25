from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FontFamily = Literal["helvetica", "montserrat", "times", "liberation-serif", "playfair-display",
                     "eb-garamond", "cinzel", "great-vibes", "pinyon-script"]


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    name_x: float | None = Field(default=None, ge=0, le=100)
    name_y: float | None = Field(default=None, ge=0, le=100)
    name_font_size: int | None = Field(default=None, ge=8, le=200)
    name_alignment: Literal["left", "center", "right"] | None = None
    name_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    college_x: float | None = Field(default=None, ge=0, le=100)
    college_y: float | None = Field(default=None, ge=0, le=100)
    college_font_size: int | None = Field(default=None, ge=8, le=200)
    college_alignment: Literal["left", "center", "right"] | None = None
    college_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    team_x: float | None = Field(default=None, ge=0, le=100)
    team_y: float | None = Field(default=None, ge=0, le=100)
    team_font_size: int | None = Field(default=None, ge=8, le=200)
    team_alignment: Literal["left", "center", "right"] | None = None
    team_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    include_college: bool | None = None
    include_team: bool | None = None
    name_font_family: FontFamily | None = None
    name_bold: bool | None = None
    name_italic: bool | None = None
    college_font_family: FontFamily | None = None
    college_bold: bool | None = None
    college_italic: bool | None = None
    team_font_family: FontFamily | None = None
    team_bold: bool | None = None
    team_italic: bool | None = None
    name_uppercase: bool | None = None
    college_uppercase: bool | None = None
    team_uppercase: bool | None = None


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    file_type: str
    is_active: bool
    name_x: float
    name_y: float
    name_font_size: int
    name_alignment: str
    name_color: str
    college_x: float
    college_y: float
    college_font_size: int
    college_alignment: str
    college_color: str
    team_x: float
    team_y: float
    team_font_size: int
    team_alignment: str
    team_color: str
    include_college: bool
    include_team: bool
    name_font_family: str
    name_bold: bool
    name_italic: bool
    college_font_family: str
    college_bold: bool
    college_italic: bool
    team_font_family: str
    team_bold: bool
    team_italic: bool
    name_uppercase: bool
    college_uppercase: bool
    team_uppercase: bool
    created_by: int
    created_at: datetime
    updated_at: datetime


class CertificateRead(BaseModel):
    participant_id: int
    participant_name: str
    college_name: str | None
    team_name: str | None
    eligible: bool
    status: Literal["READY", "NO_TEMPLATE"]
    template_name: str | None
