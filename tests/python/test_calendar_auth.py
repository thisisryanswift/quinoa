"""Regression tests for lazy OAuth credential loading and error handling."""

import json
import os
from unittest.mock import MagicMock, patch

import keyring
import pytest


@pytest.fixture(autouse=True)
def _clear_auth_module(monkeypatch):
    """Ensure a fresh auth module state for every test."""
    # Wipe env secrets and the global credential cache.
    for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)

    from quinoa.calendar import auth as auth_module

    auth_module.GOOGLE_CLIENT_ID = None
    auth_module.GOOGLE_CLIENT_SECRET = None
    auth_module._credentials_loaded = False

    # Disable real keyring access by default.
    monkeypatch.setattr(keyring, "get_password", lambda *args, **kwargs: None)
    monkeypatch.setattr(keyring, "set_password", lambda *args, **kwargs: None)
    monkeypatch.setattr(keyring, "delete_password", lambda *args, **kwargs: None)

    yield

    auth_module.GOOGLE_CLIENT_ID = None
    auth_module.GOOGLE_CLIENT_SECRET = None
    auth_module._credentials_loaded = False


def test_import_without_secrets_does_not_load_credentials():
    """Importing the module must not fail or load credentials."""
    from quinoa.calendar import auth as auth_module

    assert auth_module.GOOGLE_CLIENT_ID is None
    assert auth_module.GOOGLE_CLIENT_SECRET is None
    assert auth_module._credentials_loaded is False


def test_is_authenticated_returns_false_without_secrets():
    from quinoa.calendar.auth import is_authenticated

    assert is_authenticated() is False


def test_get_credentials_returns_none_without_secrets():
    from quinoa.calendar.auth import get_credentials

    assert get_credentials() is None


def test_authenticate_returns_none_without_secrets(monkeypatch: pytest.MonkeyPatch):
    from quinoa.calendar import auth

    monkeypatch.setattr(
        auth,
        "_load_oauth_credentials",
        lambda: (_ for _ in ()).throw(ValueError("OAuth credentials not found")),
    )

    assert auth.authenticate() is None


def test_load_tokens_corrupt_non_dict_is_deleted():
    from quinoa.calendar import auth

    deleted = {"called": False}

    def fake_get(*_args):
        return json.dumps(["not", "a", "dict"])

    def fake_delete(*_args):
        deleted["called"] = True

    with (
        patch.object(keyring, "get_password", fake_get),
        patch.object(keyring, "delete_password", fake_delete),
    ):
        assert auth._load_tokens() is None
    assert deleted["called"] is True


def test_load_tokens_keyring_error_is_handled():
    from quinoa.calendar import auth

    def fake_get(*_args):
        raise keyring.errors.KeyringError("dbus unavailable")

    with patch.object(keyring, "get_password", fake_get):
        assert auth._load_tokens() is None


def test_get_credentials_uses_token_client_id_secret_without_env():
    """Tokens that include client_id/secret should work even when env vars are absent."""
    from quinoa.calendar import auth

    tokens = {
        "token": "access-token",
        "refresh_token": "refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "token-client-id",
        "client_secret": "token-client-secret",
        "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
    }

    fake_creds = MagicMock()
    fake_creds.valid = True
    fake_creds.expired = False

    with (
        patch.object(keyring, "get_password", lambda *_args: json.dumps(tokens)),
        patch.object(auth, "Credentials", return_value=fake_creds) as mock_creds,
    ):
        creds = auth.get_credentials()

    assert creds is fake_creds
    assert mock_creds.call_args.kwargs["client_id"] == "token-client-id"
    assert mock_creds.call_args.kwargs["client_secret"] == "token-client-secret"


def test_get_credentials_falls_back_to_env_when_token_missing_client_secret():
    """Missing client secret in tokens should fall back to env vars."""
    from quinoa.calendar import auth

    tokens = {
        "token": "access-token",
        "refresh_token": "refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "token-client-id",
        # no client_secret
        "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
    }

    fake_creds = MagicMock()
    fake_creds.valid = True
    fake_creds.expired = False

    auth.GOOGLE_CLIENT_ID = None
    auth.GOOGLE_CLIENT_SECRET = None
    auth._credentials_loaded = False

    with (
        patch.object(keyring, "get_password", lambda *_args: json.dumps(tokens)),
        patch.object(auth, "Credentials", return_value=fake_creds) as mock_creds,
        patch.dict(
            os.environ,
            {"GOOGLE_CLIENT_ID": "env-id", "GOOGLE_CLIENT_SECRET": "env-secret"},
        ),
    ):
        creds = auth.get_credentials()

    assert creds is fake_creds
    assert mock_creds.call_args.kwargs["client_id"] == "token-client-id"
    assert mock_creds.call_args.kwargs["client_secret"] == "env-secret"
