"""Bounded resume defaults; rendering remains outside the profile bank."""
from typing import Literal
from pydantic import Field
from .schema import BankModel


class LayoutDefaults(BankModel):
    font_family: Literal['auto', 'serif', 'sans', 'mono', 'latex'] = 'auto'
    font_size: float = Field(default=11, ge=8, le=16, allow_inf_nan=False)
    margin: float = Field(default=18, ge=10, le=35, allow_inf_nan=False)
    line_spacing: float = Field(default=1.25, ge=1, le=1.8, allow_inf_nan=False)
    page_size: Literal['A4', 'letter'] = 'A4'
    date_format: Literal['Jul 2023', 'July 2023', '07/2023', '2023'] = 'Jul 2023'
    present_label: Literal['Present', 'Current', 'Now'] = 'Present'
    heading_style: Literal['rule', 'small-caps', 'bold'] = 'rule'
    accent_color: Literal['black', 'navy', 'teal', 'maroon'] = 'black'
    bullet_char: Literal['•', '–', '▪'] = '•'
    header_align: Literal['center', 'left'] = 'center'
    contact_separator: Literal['·', '|', 'newline', 'new line'] = '·'  # 'new line' is the legacy spelling
    section_spacing: Literal['compact', 'normal', 'airy'] = 'normal'
    skills_layout: Literal['inline', 'grouped', 'columns'] = 'grouped'


class SectionDefault(BankModel):
    kind: Literal['experience', 'education', 'projects', 'skills', 'custom', 'certification', 'award', 'volunteering']
    title: str | None = Field(default=None, max_length=240)
    hidden: bool = False


class BuildDefaults(BankModel):
    points_per_item: int = Field(default=4, ge=1, le=30)
    include_profile_summary: bool = True


class ResumeDefaults(BankModel):
    template: Literal['classic', 'modern'] = 'classic'
    layout: LayoutDefaults = Field(default_factory=LayoutDefaults)
    sections: list[SectionDefault] = Field(default_factory=list, max_length=30)
    header_fields: list[Literal['email', 'phone', 'location', 'links']] = Field(default_factory=list, max_length=4)
    build: BuildDefaults = Field(default_factory=BuildDefaults)
