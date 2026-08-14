import hashlib
import hmac
import time

from ..config import settings


BOT_IMAGE_URL_TTL_SECONDS = 300


def sign_bot_image(image_id: str, expires: int | None = None) -> tuple[int, str]:
    expires = int(expires or (time.time() + BOT_IMAGE_URL_TTL_SECONDS))
    message = f"bot-image|{image_id}|{expires}".encode()
    signature = hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()
    return expires, signature


def verify_bot_image(image_id: str, expires: int, signature: str) -> bool:
    if int(expires) < int(time.time()):
        return False
    _, expected = sign_bot_image(image_id, int(expires))
    return hmac.compare_digest(expected, str(signature or ""))
