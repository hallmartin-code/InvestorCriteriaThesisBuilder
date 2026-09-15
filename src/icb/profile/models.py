"""Investor profile document (CLAUDE.md §6; shape in §15, Screens item 2).

The web form and the CLI both produce this document. Values may be partial while a field is
not yet provided, so every part of a value is optional here. `validate.normalize` decides each
field's status from its value; a client can never mark an incomplete field as provided.
Length and size limits exist because the app is open to anyone.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator, model_validator

Status = Literal["provided", "no_preference", "not_provided"]
SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])?$"

Short = Annotated[str, Field(max_length=200)]
Text = Annotated[str, Field(max_length=5000)]
Usd = Annotated[int, Field(ge=0, le=10**13)]
Stage = Literal["Pre-Seed", "Seed", "Series A", "Series B", "Series C+", "Growth"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoneyRange(_Strict):
    min_usd: Usd | None = None
    max_usd: Usd | None = None


class YearRange(_Strict):
    min: Annotated[float, Field(ge=0, le=100)] | None = None
    max: Annotated[float, Field(ge=0, le=100)] | None = None


class ReturnObjective(_Strict):
    text: Text = ""
    target_multiple: Annotated[float, Field(ge=0, le=100_000)] | None = None
    target_irr_pct: Annotated[float, Field(ge=-100, le=100_000)] | None = None


class PriorInvestment(_Strict):
    company: Short = ""
    year: Annotated[int, Field(ge=1900, le=2100)] | None = None
    stage: Short | None = None
    sector: Short = ""
    check_usd: Usd | None = None
    outcome: Literal["active", "exited", "written_off", "unknown"] | None = None
    multiple: Annotated[float, Field(ge=0, le=100_000)] | None = None
    lesson: Text | None = None


class SectorScope(_Strict):
    sector: Short = ""
    subsectors: Annotated[list[Short], Field(max_length=50)] = []


class Traction(_Strict):
    metric: Short | None = None
    threshold: Short = ""


class ThesisNotes(_Strict):
    text: Annotated[str, Field(max_length=50_000)] = ""
    files: Annotated[list[Short], Field(max_length=20)] = []


# Every §6 field, in form order, with the shape its value may take.
VALUE_TYPES: dict[str, Any] = {
    "investor_type": Literal["angel", "family_office", "fund", "corporate"] | None,
    "capital_available_usd": Usd | None,
    "check_size": MoneyRange | None,
    "follow_on_reserve_policy": Text | None,
    "return_objective": ReturnObjective | None,
    "liquidity_objective": Text | None,
    "time_horizon_years": YearRange | None,
    "prior_investments": Annotated[list[PriorInvestment], Field(max_length=100)] | None,
    "stages": Annotated[list[Stage], Field(max_length=6)] | None,
    "sectors": Annotated[list[SectorScope], Field(max_length=50)] | None,
    "geographies": Annotated[list[Short], Field(max_length=100)] | None,
    "ownership_target_pct": Annotated[float, Field(ge=-1_000, le=1_000)] | None,
    "round_size": MoneyRange | None,
    "instruments_accepted": Annotated[list[Short], Field(max_length=20)] | None,
    "minimum_traction": Traction | None,
    "instant_no_filters": Annotated[list[Text], Field(max_length=50)] | None,
    "thesis_notes": ThesisNotes | None,
}
FIELD_KEYS: tuple[str, ...] = tuple(VALUE_TYPES)

# Tier 2 hard-criteria parameters and thesis notes may be deliberately not applied; Tier 1 may not.
NO_PREFERENCE_ALLOWED = frozenset({
    "follow_on_reserve_policy", "stages", "sectors", "geographies", "ownership_target_pct", "round_size",
    "instruments_accepted", "minimum_traction", "instant_no_filters", "thesis_notes",
})

_ADAPTERS = {key: TypeAdapter(value_type) for key, value_type in VALUE_TYPES.items()}


class FieldEntry(_Strict):
    status: Status = "not_provided"
    value: Any = None
    source: Short = "intake"
    affirmed_none: bool | None = None


class ProfileDocument(_Strict):
    schema_version: Literal[1] = 1
    slug: Annotated[str, Field(pattern=SLUG_PATTERN)]
    display_name: Annotated[str, Field(min_length=1, max_length=120)]
    updated_at: datetime | None = None
    fields: dict[str, FieldEntry] = {}

    @field_validator("display_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter the investor's name.")
        return value

    @model_validator(mode="after")
    def _check_fields(self) -> ProfileDocument:
        unknown = sorted(set(self.fields) - set(FIELD_KEYS))
        if unknown:
            raise ValueError(f"Unknown profile fields: {', '.join(unknown)}.")
        for key, entry in self.fields.items():
            if entry.status == "no_preference" and key not in NO_PREFERENCE_ALLOWED:
                raise ValueError(f"{key} must be answered; it cannot be marked No preference.")
            try:
                validated = _ADAPTERS[key].validate_python(entry.value)
            except ValidationError as exc:
                first = exc.errors()[0]
                where = ".".join(str(part) for part in (key, *first.get("loc", ())))
                raise ValueError(f"{where}: {first.get('msg', 'invalid value')}") from None
            entry.value = _ADAPTERS[key].dump_python(validated, mode="json")
        return self
