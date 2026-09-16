"""Pydantic request models for the REST API."""

from __future__ import annotations

import re
from typing import Dict, List, Literal

from pydantic import BaseModel, Field, field_validator


ATTR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:\-]*$")


class CompareOptionsIn(BaseModel):
    ns_mode: Literal["uri", "prefix", "local"] = "uri"
    normalize_ws: bool = True
    ignore_attrs: List[str] = Field(default_factory=list)
    ignore_xpaths: List[str] = Field(default_factory=list)


class CompareRequest(BaseModel):
    session_id: str
    options: CompareOptionsIn = Field(default_factory=CompareOptionsIn)


class MarkingOptionsIn(BaseModel):
    mode: Literal["none", "attribute", "comment"] = "none"
    attribute_name: str = "data-merge-source"

    @field_validator("attribute_name")
    @classmethod
    def _validate_attribute_name(cls, value):
        if not ATTR_NAME_RE.match(value):
            raise ValueError("attribute_name must be a valid XML attribute name")
        return value


class MergeRequest(BaseModel):
    session_id: str
    selections: Dict[str, str] = Field(default_factory=dict)
    marking: MarkingOptionsIn = Field(default_factory=MarkingOptionsIn)
    preview: bool = False
