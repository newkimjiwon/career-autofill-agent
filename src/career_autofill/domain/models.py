from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fact(Model):
    value: str
    source: str = Field(min_length=1)
    status: Literal["source", "user", "unverified"] = "source"


class Experience(Model):
    title: str
    kind: Literal["project", "career", "activity"] = "project"
    summary: str
    skills: list[str] = Field(default_factory=list)
    source: str
    start: str | None = None
    end: str | None = None


class CareerProfile(Model):
    basic: dict[str, Fact] = Field(default_factory=dict)
    education: list[dict[str, Fact]] = Field(default_factory=list)
    military: dict[str, Fact] = Field(default_factory=dict)
    certifications: list[dict[str, Fact]] = Field(default_factory=list)
    languages: list[dict[str, Fact]] = Field(default_factory=list)
    experiences: list[Experience] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)

    def facts(self) -> dict[str, Fact]:
        result = {f"basic.{key}": value for key, value in self.basic.items()}
        result.update({f"military.{key}": value for key, value in self.military.items()})
        for section in ("education", "certifications", "languages"):
            for index, record in enumerate(getattr(self, section)):
                result.update({f"{section}.{index}.{key}": value for key, value in record.items()})
        return result


class Cell(Model):
    text: str
    rowspan: int = Field(default=1, ge=1)
    colspan: int = Field(default=1, ge=1)


class SourceSnapshot(Model):
    url: str
    title: str
    text: str
    collected_at: datetime
    tables: list[list[list[Cell]]] = Field(default_factory=list)
    links: list[dict[str, str]] = Field(default_factory=list)


class JobRole(Model):
    id: str
    company: str
    title: str
    responsibilities: str
    qualifications: str = ""
    preferred: str = ""
    general_qualifications: str = ""
    location: str = ""
    source_url: str
    deadline: datetime | None = None
    collected_at: datetime
    career_type: str = "신입"


class MatchEvidence(Model):
    topic: str
    profile_source: str
    profile_excerpt: str
    job_excerpt: str


class JobMatch(Model):
    job: JobRole
    score: int
    evidence: list[MatchEvidence]
    gaps: list[str]
    checks: list[str]


class FormField(Model):
    id: str
    frame: int = Field(default=0, ge=0)
    index: int = Field(ge=0)
    label: str
    section: str = ""
    kind: str
    name: str = ""
    value: str = ""
    required: bool = False
    disabled: bool = False
    readonly: bool = False
    maxlength: int = -1
    format_hint: Literal["", "YYYY.MM", "YYYY.MM.DD"] = ""
    options: list[dict[str, str]] = Field(default_factory=list)


class FillAction(Model):
    field: FormField
    profile_path: str
    value: str
    source: str


class FillPlan(Model):
    id: str
    url: str
    fingerprint: str
    profile_fingerprint: str
    created_at: datetime
    actions: list[FillAction]
    skipped: list[dict[str, str]]
    observed_fields: list[FormField] = Field(default_factory=list)
    state: Literal["preview", "applied", "failed"] = "preview"


class FormInspection(Model):
    status: Literal["ready", "login_required", "user_action_required"]
    url: str
    fields: list[FormField] = Field(default_factory=list)
    message: str | None = None
