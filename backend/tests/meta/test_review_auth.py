import pytest
from fastapi import HTTPException

from app.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    yield
    get_settings.cache_clear()


def test_require_reviewer_token_rejects_when_unset(monkeypatch):
    from app.meta.review_api import require_reviewer_token

    monkeypatch.setattr(get_settings(), "meta_reviewer_token", None)
    with pytest.raises(HTTPException) as exc_info:
        require_reviewer_token(authorization="Bearer anything")
    assert exc_info.value.status_code == 401
    assert "not configured" in exc_info.value.detail


def test_require_reviewer_token_rejects_missing_header(monkeypatch):
    from app.meta.review_api import require_reviewer_token

    monkeypatch.setattr(get_settings(), "meta_reviewer_token", "good-token")
    with pytest.raises(HTTPException) as exc_info:
        require_reviewer_token(authorization=None)
    assert exc_info.value.status_code == 401


def test_require_reviewer_token_rejects_non_bearer_header(monkeypatch):
    from app.meta.review_api import require_reviewer_token

    monkeypatch.setattr(get_settings(), "meta_reviewer_token", "good-token")
    with pytest.raises(HTTPException) as exc_info:
        require_reviewer_token(authorization="good-token")
    assert exc_info.value.status_code == 401


def test_require_reviewer_token_rejects_wrong_token(monkeypatch):
    from app.meta.review_api import require_reviewer_token

    monkeypatch.setattr(get_settings(), "meta_reviewer_token", "good-token")
    with pytest.raises(HTTPException) as exc_info:
        require_reviewer_token(authorization="Bearer wrong-token")
    assert exc_info.value.status_code == 401


def test_require_reviewer_token_accepts_matching_token(monkeypatch):
    from app.meta.review_api import require_reviewer_token

    monkeypatch.setattr(get_settings(), "meta_reviewer_token", "good-token")
    require_reviewer_token(authorization="Bearer good-token")  # must not raise
