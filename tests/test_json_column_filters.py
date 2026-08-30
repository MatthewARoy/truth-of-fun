"""JSON-column filters must compile to containment, never to LIKE.

`events.tags` and `events.categories` are plain `JSON` columns. SQLAlchemy
renders `.contains()` on JSON as a SQL `LIKE`, which Postgres rejects with
`operator does not exist: json ~~ text` — a 500 on every filtered query.

The reason this keeps recurring is that it does *not* fail in the test suite:
the hermetic tests run on SQLite, which accepts the LIKE and quietly returns
nothing useful. So assert on the compiled SQL instead of on behaviour, against
the Postgres dialect, which is what production actually runs.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql
from sqlmodel import select

from app.api.discovery import _canonical_tag_filter, _category_filter
from app.models.event import Event


def _compile(condition) -> str:
    return str(select(Event.id).where(condition).compile(dialect=postgresql.dialect()))


@pytest.mark.parametrize(
    ("label", "condition"),
    [
        ("categories", _category_filter("Fitness")),
        ("tags", _canonical_tag_filter("chill")),
    ],
)
def test_json_filter_does_not_compile_to_like(label: str, condition) -> None:
    sql = _compile(condition)
    assert "LIKE" not in sql.upper(), (
        f"{label} filter compiled to a LIKE against a JSON column; Postgres will "
        f"reject this with 'operator does not exist: json ~~ text'.\n{sql}"
    )


def test_category_filter_uses_jsonb_containment() -> None:
    sql = _compile(_category_filter("Fitness"))
    assert "@>" in sql
    assert "AS JSONB" in sql.upper()


def test_tag_filter_expands_through_the_canonical_vocabulary() -> None:
    # Not containment: tags match across spelling variants, so this one goes
    # through jsonb_array_elements_text rather than @>.
    sql = _compile(_canonical_tag_filter("chill"))
    assert "jsonb_array_elements_text" in sql
