"""Google Calendar OAuth authentication."""

import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import httplib2
import keyring
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.errors import HttpError
from keyring.errors import PasswordDeleteError
from requests.exceptions import RequestException  # type: ignore[import-untyped]

from quinoa.config import config

logger = logging.getLogger("quinoa")


def _load_oauth_credentials() -> tuple[str, str]:
    """Load OAuth credentials from env vars or secrets.json.

    Priority: environment variables > secrets.json
    """
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if client_id and client_secret:
        return client_id, client_secret

    # Try secrets.json in project root
    secrets_path = Path(__file__).parent.parent.parent / "secrets.json"
    if secrets_path.exists():
        try:
            with open(secrets_path) as f:
                secrets = json.load(f)
                client_id = secrets.get("google_client_id")
                client_secret = secrets.get("google_client_secret")
                if client_id and client_secret:
                    return client_id, client_secret
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load secrets.json: %s", e)

    raise ValueError(
        "OAuth credentials not found. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET "
        "environment variables, or create a secrets.json file."
    )


# OAuth credentials are loaded lazily so that importing this module does not
# fail in tests or command-line tools when no secrets are configured.
GOOGLE_CLIENT_ID: str | None = None
GOOGLE_CLIENT_SECRET: str | None = None
_credentials_loaded = False


def _ensure_credentials_loaded() -> None:
    """Load OAuth credentials once and cache the result."""
    global GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, _credentials_loaded
    if _credentials_loaded:
        return
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET = _load_oauth_credentials()
    _credentials_loaded = True


# Scopes for calendar read-only access
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# Keyring storage
KEYRING_SERVICE = "quinoa"
KEYRING_TOKEN_KEY = "google_calendar_tokens"


def _get_client_config() -> dict:
    """Build OAuth client config from embedded credentials."""
    _ensure_credentials_loaded()
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise ValueError(
            "OAuth credentials not found. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET "
            "environment variables, or create a secrets.json file."
        )
    return {
        "installed": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _load_tokens() -> dict | None:
    """Load tokens from keyring.

    Decoded tokens must be a JSON object (dict). Non-dict payloads are treated
    as corruption and removed.
    """
    try:
        raw_data = keyring.get_password(KEYRING_SERVICE, KEYRING_TOKEN_KEY)
        if not raw_data:
            return None

        # Some keyring backends (especially on Linux/KDE) might return bytes
        # or be in a corrupt state that requires explicit decoding.
        if isinstance(raw_data, bytes):
            try:
                tokens_json = raw_data.decode("utf-8")
            except UnicodeDecodeError as e:
                raise ValueError("Keyring data is binary and not valid UTF-8") from e
        else:
            tokens_json = raw_data

        result = json.loads(tokens_json)
        if not isinstance(result, dict):
            raise TypeError(f"expected token JSON object, got {type(result).__name__}")
        return result
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
        # Data corruption — delete the broken entry.
        logger.warning("Corrupt calendar tokens in keyring, removing: %s", e)
        with contextlib.suppress(keyring.errors.KeyringError):
            keyring.delete_password(KEYRING_SERVICE, KEYRING_TOKEN_KEY)
    except keyring.errors.KeyringError as e:
        # Infrastructure error (DBus, keyring daemon, etc.) — don't delete
        logger.warning("Failed to read calendar tokens from keyring: %s", e)
    return None


def _save_tokens(credentials: Any) -> None:
    """Save tokens to keyring."""
    try:
        scopes = list(credentials.scopes) if credentials.scopes else list(SCOPES)
        tokens = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": scopes,
        }
        if credentials.expiry:
            tokens["expiry"] = credentials.expiry.isoformat()
        tokens_json = json.dumps(tokens, ensure_ascii=True)
        keyring.set_password(KEYRING_SERVICE, KEYRING_TOKEN_KEY, tokens_json)
        logger.debug("Saved calendar tokens to keyring (%d bytes)", len(tokens_json))
    except keyring.errors.KeyringError as e:
        logger.error("Failed to save calendar tokens to keyring: %s", e)
    except Exception as e:
        logger.error("Failed to save calendar tokens to keyring: %s", e)


def is_authenticated() -> bool:
    """Check if we have valid calendar credentials."""
    creds = get_credentials()
    return creds is not None and creds.valid


def get_credentials() -> Any:
    """Get valid credentials, refreshing if needed.

    Returns None if not authenticated or refresh fails.

    Importing or calling this function without OAuth secrets configured returns
    None so the application and tests can start cleanly.
    """
    tokens = _load_tokens()
    if not tokens:
        return None

    client_id: str | None = tokens.get("client_id")
    client_secret: str | None = tokens.get("client_secret")

    # Only load embedded env/secrets credentials if the token payload does not
    # already include them. Missing credentials must not raise at call time.
    if not client_id or not client_secret:
        try:
            _ensure_credentials_loaded()
        except ValueError:
            logger.warning("OAuth credentials not configured; calendar unavailable")
            return None
        client_id = client_id or GOOGLE_CLIENT_ID
        client_secret = client_secret or GOOGLE_CLIENT_SECRET

    if not client_id or not client_secret:
        logger.warning("OAuth credentials not configured; calendar unavailable")
        return None

    try:
        creds = Credentials(
            token=tokens.get("token"),
            refresh_token=tokens.get("refresh_token"),
            token_uri=tokens.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=client_id,
            client_secret=client_secret,
            scopes=tokens.get("scopes", SCOPES),
        )

        # Check if expired and refresh
        if creds.expired and creds.refresh_token:
            try:
                logger.info("Refreshing expired calendar credentials...")
                creds.refresh(Request())
                _save_tokens(creds)
            except (RefreshError, TransportError, RequestException, httplib2.HttpLib2Error) as e:
                error_str = str(e).lower()
                if "invalid_grant" in error_str or "token has been expired" in error_str:
                    logger.warning("Calendar refresh token invalid/expired. Clearing tokens.")
                    config.set("calendar_auth_expired", True)
                    logout()
                logger.warning("Calendar credential refresh failed: %s", e)
                return None

        if creds.valid:
            config.set("calendar_auth_expired", False)

        return creds if creds.valid else None

    except Exception as e:
        if not isinstance(e, (KeyError, TypeError)):  # Don't log expected token parsing errors
            logger.error("Failed to get/refresh calendar credentials: %s", e)
        return None


def authenticate() -> Any:
    """Run OAuth flow to authenticate with Google Calendar.

    Opens a browser window for the user to authorize access.
    Returns credentials on success, None on failure/cancel.

    Importing or calling this function without secrets configured returns None
    instead of raising, so the application and tests can start cleanly.
    """
    try:
        _ensure_credentials_loaded()
    except ValueError:
        logger.warning("Calendar authentication skipped: OAuth secrets are not configured")
        return None

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        logger.warning("Calendar authentication skipped: OAuth secrets are not configured")
        return None

    try:
        flow = InstalledAppFlow.from_client_config(_get_client_config(), SCOPES)

        # Run local server for OAuth callback
        # This opens the browser and waits for authorization
        creds = flow.run_local_server(
            port=0,  # Use any available port
            prompt="consent",  # Always show consent screen
            success_message="Authorization successful! You can close this window.",
            open_browser=True,
        )

        if creds:
            _save_tokens(creds)
            config.set("calendar_auth_expired", False)
            logger.info("Calendar authentication successful")
            return creds

    except (
        ValueError,
        RefreshError,
        TransportError,
        RequestException,
        httplib2.HttpLib2Error,
    ) as e:
        logger.error("Calendar authentication failed: %s", e)
    except Exception as e:
        logger.error("Calendar authentication failed: %s", e)

    return None


def get_user_email() -> str | None:
    """Get the authenticated user's email address.

    Uses the Calendar API to get the primary calendar's owner email,
    since we only have calendar.readonly scope.
    """
    creds = get_credentials()
    if not creds:
        return None

    try:
        from googleapiclient.discovery import build

        service = build("calendar", "v3", credentials=creds)
        # Get primary calendar - its id is the user's email
        calendar = service.calendars().get(calendarId="primary").execute()
        email: str | None = calendar.get("id")
        return email  # Primary calendar ID is the user's email
    except (HttpError, httplib2.HttpLib2Error) as e:
        logger.warning("Failed to get user email: %s", e)
        return None
    except Exception as e:
        logger.warning("Failed to get user email: %s", e)
        return None


def logout() -> None:
    """Clear stored calendar credentials."""
    config.set("calendar_auth_expired", False)
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_TOKEN_KEY)
        logger.info("Calendar credentials cleared")
    except PasswordDeleteError:
        pass  # Already deleted or never existed
    except keyring.errors.KeyringError as e:
        logger.warning("Failed to clear calendar credentials: %s", e)
