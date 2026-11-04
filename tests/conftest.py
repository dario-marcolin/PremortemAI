import pytest

from premortem import config


@pytest.fixture(autouse=True)
def output_dir(tmp_path, monkeypatch):
    """No test writes to the real outputs/ folder."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "outputs")
    return config.OUTPUT_DIR
