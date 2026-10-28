import base64
import pytest
from cryptography.fernet import Fernet, InvalidToken
from app import store, share


def test_cloud_encryption_needs_the_original_key(monkeypatch):
    monkeypatch.setenv("STUDIO_MASTER_KEY", Fernet.generate_key().decode())
    saved = store.protect("private-cloud-credential")
    assert saved.startswith("fernet:") and "private-cloud-credential" not in saved
    assert store.protect(saved, decrypt=True) == "private-cloud-credential"
    monkeypatch.setenv("STUDIO_MASTER_KEY", Fernet.generate_key().decode())
    with pytest.raises(InvalidToken):
        store.protect(saved, decrypt=True)
    monkeypatch.delenv("STUDIO_MASTER_KEY")
    with pytest.raises(RuntimeError, match="STUDIO_MASTER_KEY"):
        store.protect(saved, decrypt=True)


def test_cloud_environment_keys_are_not_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG", tmp_path / "settings.json")
    monkeypatch.setenv("STUDIO_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("STUDIO_KLING_API_KEY", "runtime-only-test-key")
    monkeypatch.setenv("STUDIO_TTS_DEVICE", "cpu")
    assert store.settings()["kling_api_key"] == "runtime-only-test-key"
    assert store.settings()["tts_device"] == "cpu"
    assert not store.CONFIG.exists()


def test_persistent_config_uses_authenticated_encryption(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG", tmp_path / "settings.json")
    monkeypatch.setenv("STUDIO_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("STUDIO_KLING_API_KEY", raising=False)
    store.save_settings({"kling_api_key": "cloud-private-key"})
    assert "cloud-private-key" not in store.CONFIG.read_text()
    assert store.settings()["kling_api_key"] == "cloud-private-key"


def test_cloud_invitation_comes_from_server_environment(monkeypatch):
    monkeypatch.setenv("STUDIO_SHARE_CODE", "cloud-experience-invitation")
    monkeypatch.setattr(share, "SECRET_FILE", None)
    assert share.share_code() == "cloud-experience-invitation"
