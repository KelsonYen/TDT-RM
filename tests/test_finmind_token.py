import importlib.util
import sys
from pathlib import Path


def _load_finmind_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "fetch_daily_data_finmind.py"
    spec = importlib.util.spec_from_file_location("fetch_daily_data_finmind", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_finmind_api_token_env_alias(monkeypatch):
    module = _load_finmind_module()
    monkeypatch.delenv("FINMIND_TOKEN", raising=False)
    monkeypatch.setenv("FINMIND_API_TOKEN", "api-token")

    assert module.finmind_token_from_env() == "api-token"


def test_finmind_token_takes_precedence(monkeypatch):
    module = _load_finmind_module()
    monkeypatch.setenv("FINMIND_TOKEN", "primary-token")
    monkeypatch.setenv("FINMIND_API_TOKEN", "api-token")

    assert module.finmind_token_from_env() == "primary-token"
