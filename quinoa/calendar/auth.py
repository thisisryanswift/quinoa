"""Google Calendar OAuth authentication."""

import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import keyring
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from keyring.errors import PasswordDeleteError

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


# Load credentials at module import
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET = _load_oauth_credentials()

# Scopes for calendar read-only access
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# Keyring storage
KEYRING_SERVICE = "quinoa"
KEYRING_TOKEN_KEY = "google_calendar_tokens"


def _get_client_config() -> dict:
    """Build OAuth client config from embedded credentials."""
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
    """Load tokens from keyring."""
    try:
        tokens_json = keyring.get_password(KEYRING_SERVICE, KEYRING_TOKEN_KEY)
        if tokens_json:
            result: dict = json.loads(tokens_json)
            return result
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
        # Data corruption — delete the broken entry
        logger.warning("Corrupt calendar tokens in keyring, removing: %s", e)
        with contextlib.suppress(Exception):
            keyring.delete_password(KEYRING_SERVICE, KEYRING_TOKEN_KEY)
    except Exception as e:
        # Infrastructure error (DBus, keyring daemon, etc.) — don't delete
        logger.warning("Failed to read calendar tokens from keyring: %s", e)
    return None


def _save_tokens(credentials: Any) -> None:
    """Save tokens to keyring."""
    try:
        tokens = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": list(credentials.scopes) if credentials.scopes else SCOPES,
        }
        if credentials.expiry:
            tokens["expiry"] = credentials.expiry.isoformat()
        tokens_json = json.dumps(tokens, ensure_ascii=True)
        keyring.set_password(KEYRING_SERVICE, KEYRING_TOKEN_KEY, tokens_json)
        logger.debug("Saved calendar tokens to keyring (%d bytes)", len(tokens_json))
    except Exception as e:
        logger.error("Failed to save calendar tokens to keyring: %s", e)


def is_authenticated() -> bool:
    """Check if we have valid calendar credentials."""
    creds = get_credentials()
    return creds is not None and creds.valid


def get_credentials() -> Any:
    """Get valid credentials, refreshing if needed.

    Returns None if not authenticated or refresh fails.
    """
    tokens = _load_tokens()
    if not tokens:
        return None

    try:
        creds = Credentials(
            token=tokens.get("token"),
            refresh_token=tokens.get("refresh_token"),
            token_uri=tokens.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=tokens.get("client_id", GOOGLE_CLIENT_ID),
            client_secret=tokens.get("client_secret", GOOGLE_CLIENT_SECRET),
            scopes=tokens.get("scopes", SCOPES),
        )

        # Check if expired and refresh
        if creds.expired and creds.refresh_token:
            try:
                logger.info("Refreshing expired calendar credentials...")
                creds.refresh(Request())
                _save_tokens(creds)
            except Exception as e:
                error_str = str(e).lower()
                if "invalid_grant" in error_str or "token has been expired" in error_str:
                    logger.warning("Calendar refresh token invalid/expired. Clearing tokens.")
                    config.set("calendar_auth_expired", True)
                    logout()
                raise

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
    """
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
    except Exception as e:
        logger.warning("Failed to clear calendar credentials: %s", e)
