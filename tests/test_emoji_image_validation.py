import pytest
from fastapi import HTTPException
from PIL import Image

from app.routers.public_api.emojis import _verify_emoji_file


def test_static_png_is_valid_emoji_resource(tmp_path):
    image_path = tmp_path / "emoji.png"
    Image.new("RGBA", (24, 24), (40, 120, 220, 255)).save(image_path, format="PNG")

    _verify_emoji_file(str(image_path), "png")


def test_animated_gif_is_valid_emoji_resource(tmp_path):
    image_path = tmp_path / "emoji.gif"
    frames = [
        Image.new("RGB", (24, 24), (240, 80, 90)),
        Image.new("RGB", (24, 24), (90, 180, 120)),
    ]
    frames[0].save(image_path, format="GIF", save_all=True, append_images=frames[1:], duration=80, loop=0)

    _verify_emoji_file(str(image_path), "gif")


def test_emoji_extension_must_match_image_content(tmp_path):
    image_path = tmp_path / "disguised.png"
    Image.new("RGB", (24, 24), (255, 255, 255)).save(image_path, format="JPEG")

    with pytest.raises(HTTPException) as exc_info:
        _verify_emoji_file(str(image_path), "png")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "File extension does not match image content"
