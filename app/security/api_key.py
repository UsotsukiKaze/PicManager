import hmac
from typing import Optional

from fastapi import Header, HTTPException

from ..config import settings


def require_bot_api_key(authorization: Optional[str] = Header(default=None)) -> None:
    """Require the configured bot API token for service-to-service calls."""
    configured_token = getattr(settings, "BOT_API_TOKEN", "")
    if not configured_token:
        raise HTTPException(status_code=503, detail="Bot API token is not configured")

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Missing bot API token")

    if not hmac.compare_digest(token, configured_token):
        raise HTTPException(status_code=403, detail="Invalid bot API token")
