"""One bounded pixel policy for Pixiv originals, independent of upload byte limits."""

from contextlib import contextmanager

from PIL import Image

from ...config import settings
from .provider import PixivError


def pixel_limit():
    # Do not allow configuration to disable Pillow's decompression guard.
    return max(1, min(100_000_000, settings.PIXIV_MAX_IMAGE_PIXELS))


@contextmanager
def open_image(path):
    try:
        image = Image.open(path)
    except Image.DecompressionBombError:
        raise PixivError("image_too_large") from None
    try:
        if image.width * image.height > pixel_limit():
            raise PixivError("image_too_large")
        yield image
    finally:
        image.close()
