"""Filters over `events.tags` / `events.categories` must survive Postgres.

Both are plain `JSON` columns, and that has now produced the same class of
production-only 500 three separate times:

1. `.contains()` on JSON renders as a SQL `LIKE`, which Postgres rejects with
   `operator does not exist: json ~~ text`.
2. `jsonb_array_elements_text(tags)` has no `json` overload, so Postgres
   rejects it with `function jsonb_array_elements_text(json) does not exist`.

Neither fails the rest of the suite, because that runs on SQLite, which is
permissive about both. So assert on the SQL compiled for the Postgres dialect
— that catches the whole class here, in a hermetic test, instead of in
production or in the one CI job that has a real database.

The fix in both directions is the same: cast the column to JSONB first.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql
from sqlmodel import select

from app.api.discovery import _canonical_tag_filter, _category_filter
from app.models.event import Event

# Every JSON-column filter the discovery API can put in a WHERE clause.
FILTERS = [
    ("categories", _category_filter("Fitness")),
    ("tags", _canonical_tag_filter("chill")),
]


def _compile(condition) -> str:
    return str(select(Event.id).where(condition).compile(dialect=postgresql.dialect()))


@pytest.mark.parametrize(("label", "condition"), FILTERS)
def test_filter_does_not_compile_to_like(label: str, condition) -> None:
    sql = _compile(condition)
    assert "LIKE" not in sql.upper(), (
        f"the {label} filter compiled to a LIKE against a JSON column; Postgres "
        f"rejects that with 'operator does not exist: json ~~ text'.\n{sql}"
    )


@pytest.mark.parametrize(("label", "condition"), FILTERS)
def test_jsonb_functions_receive_a_jsonb_cast(label: str, condition) -> None:
    """No `jsonb_*(events.<col>)` — Postgres has no json overload for those."""
    sql = _compile(condition)
    for column in ("events.tags", "events.categories"):
        assert f"({column})" not in sql, (
            f"the {label} filter passes the raw JSON column {column} to a jsonb_* "
            f"function; Postgres rejects that with 'function ... does not exist'. "
            f"Cast it: func.<fn>(cast({column.replace('.', '_')}, JSONB)).\n{sql}"
        )


def test_category_filter_uses_jsonb_containment() -> None:
    sql = _compile(_category_filter("Fitness"))
    assert "@>" in sql
    assert "CAST(EVENTS.CATEGORIES AS JSONB)" in sql.upper()


def test_tag_filter_expands_through_the_canonical_vocabulary() -> None:
    # Not plain containment: tags match across spelling variants, so this one
    # unnests with jsonb_array_elements_text rather than using @>.
    sql = _compile(_canonical_tag_filter("chill"))
    assert "jsonb_array_elements_text" in sql
    assert "CAST(EVENTS.TAGS AS JSONB)" in sql.upper()
