import pytest
from conftest import _require_disposable_database


@pytest.mark.parametrize("url", [
    "postgresql://postgres@127.0.0.1:5433/truth_of_fun",
    "postgresql://postgres@remote.example/truth_test",
    "postgresql://postgres@127.0.0.1/truth_test?host=remote.example",
    "postgresql://postgres@127.0.0.1/truth_test?dbname=production",
    "sqlite:///truth_test",
])
def test_isolated_fixture_refuses_non_disposable_database(url):
    with pytest.raises(pytest.UsageError):
        _require_disposable_database(url)


def test_isolated_fixture_accepts_disposable_loopback_database():
    _require_disposable_database("postgresql+psycopg2://postgres@127.0.0.1:15439/truth_stabilization_test")
