from io import BytesIO

from PIL import Image

from app.config import settings
from app.routers.public_api.avatars import process_avatar_bytes


def test_avatar_processing_outputs_square_webp_under_256_kib():
    source = Image.effect_noise((1800, 1200), 96).convert("RGB")
    raw = BytesIO()
    source.save(raw, format="PNG")

    processed = process_avatar_bytes(raw.getvalue())

    assert len(processed) <= settings.AVATAR_MAX_FILE_SIZE
    with Image.open(BytesIO(processed)) as avatar:
        assert avatar.format == "WEBP"
        assert avatar.width == avatar.height
        assert avatar.width <= settings.AVATAR_SIZE
