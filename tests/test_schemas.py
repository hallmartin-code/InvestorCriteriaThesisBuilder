"""The API compiles each schema into a grammar and rejects it when that grows too large.

Measured limits (probed against claude-opus-5 on 2026-09-16):
- arrays of objects are the expensive construct: 6 were accepted, 10 were not
- at most 16 parameters may use a union or nullable type
Plain strings, integers, enums and arrays of strings are cheap.

These tests are the guard rail: they fail offline, before a deploy turns into a 400.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from icb.criteria.models import DRAFT_SCHEMA
from icb.screen.prompts import EXTRACTION_SCHEMA

MAX_OBJECT_ARRAYS = 6
MAX_UNIONS = 16
SCHEMAS = {"criteria_draft": DRAFT_SCHEMA, "screening": EXTRACTION_SCHEMA}


def walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def object_arrays(schema: dict[str, Any]) -> int:
    return sum(1 for node in walk(schema)
               if node.get("type") == "array" and isinstance(node.get("items"), dict)
               and node["items"].get("type") == "object")


def unions(schema: dict[str, Any]) -> int:
    return sum(1 for node in walk(schema) if isinstance(node.get("type"), list) or "anyOf" in node)


@pytest.mark.parametrize("name", list(SCHEMAS))
def test_schema_stays_inside_the_grammar_budget(name):
    schema = SCHEMAS[name]
    assert object_arrays(schema) <= MAX_OBJECT_ARRAYS, (
        f"{name} has {object_arrays(schema)} arrays of objects; the API rejected 10 as too large. "
        "Merge lists or encode one as strings.")
    assert unions(schema) == 0, f"{name} uses nullable or union types; use '' or 0 and convert in the model."
    assert json.dumps(schema)  # serializable as sent


@pytest.mark.parametrize("name", list(SCHEMAS))
def test_every_property_is_required_and_closed(name):
    """Structured outputs need every object closed, with all of its properties required."""
    for node in walk(SCHEMAS[name]):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
            assert set(node.get("required", [])) == set(node.get("properties", {}))
