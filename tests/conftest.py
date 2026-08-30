import pytest

from app.core.ratelimit import SlidingWindowLimiter


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Rate-limit windows are process-global; start each test with clean ones."""
    SlidingWindowLimiter.reset_all()
    yield
    SlidingWindowLimiter.reset_all()
