from app.main import app


def test_ui_contract_v1_paths_exist() -> None:
    schema = app.openapi()
    paths = schema["paths"]

    expected_paths = [
        "/events",
        "/events/{event_id}",
        "/recommendations",
        "/users/me/onboarding",
        "/users/me/interests",
        "/concierge/itinerary",
        "/folders",
        "/folders/{folder_id}",
        "/folders/{folder_id}/items",
        "/folders/{folder_id}/votes",
        "/folders/{folder_id}/invite",
        "/shared/folders/{token}",
        "/health",
        "/health/live",
        "/health/ready",
        "/health/sources",
        "/health/summary",
    ]
    for path in expected_paths:
        assert path in paths


def test_every_route_declares_an_operation_id_and_summary() -> None:
    """MCP clients and codegen key on these; an auto-generated id is unstable.

    FastAPI derives operation ids from the function name plus path when they're
    not declared, so renaming a handler silently renames a generated client
    method. Declaring them pins the contract.
    """
    schema = app.openapi()

    missing_operation_id: list[str] = []
    missing_summary: list[str] = []
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not operation.get("operationId"):
                missing_operation_id.append(f"{method.upper()} {path}")
            if not operation.get("summary"):
                missing_summary.append(f"{method.upper()} {path}")

    assert missing_operation_id == []
    assert missing_summary == []


def test_operation_ids_are_unique() -> None:
    """Duplicate ids silently collide in generated clients."""
    schema = app.openapi()

    seen: list[str] = []
    for operations in schema["paths"].values():
        for method, operation in operations.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                seen.append(operation["operationId"])

    assert len(seen) == len(set(seen)), f"duplicate operationIds: {sorted(seen)}"


def test_schema_declares_a_version() -> None:
    """Agents and codegen pin against this; an unversioned schema is unusable."""
    assert app.openapi()["info"]["version"] == "1.0.0"


def test_event_detail_exposes_provenance_fields() -> None:
    """Agents must be able to cite a source and qualify freshness honestly."""
    schema = app.openapi()
    properties = schema["components"]["schemas"]["EventDetailResponse"]["properties"]

    for field in ("first_seen_at", "updated_at", "source_name", "source_tier"):
        assert field in properties

    # created_at must not leak under a name that implies the announcement date.
    assert "created_at" not in properties
