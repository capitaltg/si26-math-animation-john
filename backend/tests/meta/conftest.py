import pytest

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolate_meta_tests_from_local_dotenv(monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
