"""The browser fixture must refuse non-disposable databases before migration."""
from pathlib import Path
import runpy
import subprocess

import pytest


@pytest.mark.parametrize("url", [
    "postgresql://fixture:fixture@remote-db.example/local_test",
    "postgresql://fixture:fixture@127.0.0.1/ordinary_database",
    "sqlite://127.0.0.1/local_test",
    # libpq query settings override the authority and path parsed from a URL.
    "postgresql+psycopg2://fixture:fixture@127.0.0.1/local_test?host=remote-db.example&dbname=ordinary_database",
])
def test_browser_harness_refuses_unsafe_database_before_alembic(monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)

    def refuse_migration(*args, **kwargs):
        pytest.fail("Unsafe database reached the Alembic subprocess")

    monkeypatch.setattr(subprocess, "run", refuse_migration)
    with pytest.raises(SystemExit, match="local disposable PostgreSQL"):
        runpy.run_path(str(Path(__file__).parent / "browser" / "serve_api.py"))
