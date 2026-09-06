"""Pydantic models for ReliefTrace's API - read-only insights plus the one
write path (POST /api/contribute)."""

from datetime import date
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, EmailStr, Field, field_validator

ResourceType = Literal["Food", "Water", "Shelter", "Medical", "Clothing"]
RESOURCE_TYPES = list(get_args(ResourceType))


class ZoneGap(BaseModel):
    zone_name: str
    resource_type: str
    quantity_needed: float
    quantity_fulfilled: float
    unmet_need: float
    urgency_level: str
    unit: str = ""


class ResponseTrendPoint(BaseModel):
    day: date
    requests_count: int
    quantity_requested: float
    deliveries_count: int
    quantity_delivered: float


class ResourceBreakdown(BaseModel):
    resource_type: str
    total_needed: float
    total_fulfilled: float
    unmet_need: float
    unit: str = ""


class RecentDelivery(BaseModel):
    delivery_id: str
    zone_name: str
    donor_org: str
    donor_email: str | None = None
    cause_note: str | None = None
    resource_type: str
    quantity_sent: float
    delivery_date: date
    solana_tx_sig: str | None = None


class BriefingPriority(BaseModel):
    rank: int
    zone: str
    urgency: str
    reason: str
    recommended_action: str
    key_resources: list[str] = []
    confidence: Literal["high", "medium", "low"] = "medium"


class AiBriefing(BaseModel):
    briefing: str  # the narrative paragraph (kept for backwards compatibility)
    priorities: list[BriefingPriority] = []
    generated_at: str


class AskInput(BaseModel):
    question: Annotated[str, Field(min_length=3, max_length=400)]

    @field_validator("question")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("must not be blank")
        return v


class AskResult(BaseModel):
    question: str
    answer: str
    tools_used: list[str] = []
    generated_at: str


class ContributionInput(BaseModel):
    # who is contributing - an org or a person's name, nothing else
    donor_org: Annotated[str, Field(min_length=1, max_length=80)]
    donor_email: EmailStr
    # optional free text for context, e.g. "assam flood relief drive" or
    # "delivered via local Rotary chapter". Never the org name.
    cause_note: Annotated[str, Field(max_length=140)] = ""
    resource_type: ResourceType
    quantity: Annotated[float, Field(gt=0, le=1_000_000)]
    zone_name: Annotated[str, Field(min_length=1, max_length=80)]
    # Honeypot: rendered off-screen and hidden from assistive tech, so a real
    # user never fills it. A non-empty value means an automated form filler -
    # the route rejects it. Default "" keeps it optional for humans.
    website: str = ""

    @field_validator("donor_org", "zone_name")
    @classmethod
    def _strip_and_check(cls, v: str) -> str:
        v = " ".join(v.split())  # collapse whitespace, trim
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("cause_note")
    @classmethod
    def _clean_note(cls, v: str) -> str:
        return " ".join(v.split())


class ContributionResult(BaseModel):
    delivery_id: str
    donor_org: str
    donor_email: str
    cause_note: str = ""
    resource_type: str
    quantity: float
    zone_name: str
    delivery_date: date
    solana_tx_sig: str
    explorer_url: str
    verified: bool = True
    receipt_email: bool = False  # a confirmation email was queued to the donor
