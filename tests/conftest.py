import pytest

from premortem import config


@pytest.fixture(autouse=True)
def output_dir(tmp_path, monkeypatch):
    """No test writes to the real outputs/ folder."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "outputs")
    return config.OUTPUT_DIR


@pytest.fixture(autouse=True)
def no_real_provider_keys(monkeypatch):
    """The per-provider keys of the real .env (loaded at import) never reach a test:
    they would take precedence over the fake LLM_API_KEY of the tests."""
    from premortem.providers import PRESETS

    for name in PRESETS:
        monkeypatch.delenv(f"{name.upper()}_API_KEY", raising=False)
