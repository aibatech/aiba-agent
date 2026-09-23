import pytest
from config.settings import Settings,SettingsError

def test_ssh_backend_requires_second_feature_gate(monkeypatch,tmp_path):
    monkeypatch.setenv("AIBA_ROOT",str(tmp_path))
    monkeypatch.setenv("AIBA_SANDBOX_MODE","ssh")
    monkeypatch.delenv("AIBA_TERMINAL_BACKENDS_ENABLED",raising=False)
    with pytest.raises(SettingsError):Settings.load()
