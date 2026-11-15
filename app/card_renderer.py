"""Compressed library cards with a signed, recoverable original-image identity."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import os
from functools import lru_cache
from threading import local
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
import qrcode

ASSETS = Path(__file__).resolve().parent / "card-assets-static"
_thread = local()


def font(size, bold=False):
    # FreeType objects stay on their rendering thread; opening CJK fonts is costly.
    if not hasattr(_thread, "fonts"):
        _thread.fonts = {}
    key = (size, bold, os.getenv("PICMANAGER_CARD_FONT", ""))
    if key in _thread.fonts:
        return _thread.fonts[key]
    candidates = [os.getenv("PICMANAGER_CARD_FONT", ""), str(ASSETS / "card-font.ttc"),
                  f"C:/Windows/Fonts/msyh{'bd' if bold else ''}.ttc",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    for path in candidates:
        if path and Path(path).is_file():
            face = ImageFont.truetype(path, size)
            _thread.fonts[key] = face
            return face
    raise RuntimeError("Install a CJK font or set PICMANAGER_CARD_FONT")


@lru_cache(maxsize=8)
def _asset_avatar(name, size):
    with Image.open(ASSETS / name) as image:
        return ImageOps.fit(image.convert("RGBA"), (size, size), method=Image.Resampling.LANCZOS)


@lru_cache(maxsize=2)
def _wallpaper(theme):
    filename = "day.webp" if theme == "light" else "night.webp"
    with Image.open(ASSETS / "backgrounds" / filename) as image:
        wallpaper = image.convert("RGB")
        wallpaper.thumbnail((512, 1024), Image.Resampling.LANCZOS)
        return wallpaper


@lru_cache(maxsize=8)
def _backdrop(theme, width, height):
    # Parser's acrylic wallpaper/gradient, calculated at quarter size and reused.
    small_w, small_h = width // 4, (height + 3) // 4
    dark = theme == "dark"
    wallpaper = ImageOps.fit(_wallpaper(theme), (small_w + 36, small_h + 36),
                             centering=(.5, .43 if dark else .42))
    wallpaper = ImageEnhance.Color(wallpaper).enhance(1.12).filter(ImageFilter.GaussianBlur(12 if dark else 10.5))
    wallpaper = wallpaper.crop((18, 18, small_w + 18, small_h + 18)).convert("RGBA")
    stops = [(0, (13, 21, 42, 173)), (.39, (16, 24, 45, 120)),
             (.66, (16, 24, 45, 120)), (1, (12, 20, 38, 184))] if dark else [
                 (0, (245, 250, 255, 204)), (.39, (248, 250, 255, 158)),
                 (.66, (248, 250, 255, 158)), (1, (246, 249, 255, 209))]
    wash = Image.new("RGBA", wallpaper.size)
    painter = ImageDraw.Draw(wash)
    for y in range(small_h):
        position = y / max(1, small_h - 1)
        for (start, a), (end, b) in zip(stops, stops[1:]):
            if start <= position <= end:
                weight = (position - start) / (end - start)
                color = tuple(round(v + (w - v) * weight) for v, w in zip(a, b))
                painter.line((0, y, small_w, y), fill=color)
                break
    return Image.alpha_composite(wallpaper, wash).resize((width, height), Image.Resampling.BILINEAR)


def render_card(data, original: bytes, *, character_avatar=None, artist_avatar=None, theme="dark") -> bytes:
    if theme not in {"light", "dark"}:
        raise ValueError("Invalid card theme")
    with Image.open(BytesIO(original)) as source:
        if source.width * source.height > 100_000_000:
            raise ValueError("Image too large")
        art = ImageOps.exif_transpose(source).convert("RGB")
    art.thumbnail((896, 1280), Image.Resampling.LANCZOS)
    width, hero_y = 1000, 168
    hero_h = art.height
    author_y = hero_y + hero_h + 44
    height = author_y + 360
    background = _backdrop(theme, width, height).copy()
    draw = ImageDraw.Draw(background)
    white, muted = ("#202d41", "#58697f") if theme == "light" else ("#f2f6ff", "#c0ccdf")
    divider = "#94a4b9" if theme == "light" else "#7d8da9"

    def text(x, y, value, size=26, color=white, bold=False, max_width=None):
        value = str(value)
        face = font(size, bold)
        if max_width:
            while len(value) > 1 and draw.textlength(value, font=face) > max_width:
                value = value[:-2] + "…"
        draw.text((x, y), value, font=face, fill=color, stroke_width=0)

    def avatar(payload, x, y, size, label="画", fallback=None, outlined=True):
        image = None
        try:
            if payload:
                image = payload if isinstance(payload, Image.Image) else Image.open(BytesIO(payload)).convert("RGBA")
        except (OSError, ValueError):
            pass
        if image is None and fallback is not None:
            image = fallback.convert("RGBA")
        if image is None:
            draw.ellipse((x, y, x + size, y + size), fill="#526485")
            text(x + size * .23, y + size * .16, label[:1], int(size * .48))
            return
        image = ImageOps.fit(image, (size, size), method=Image.Resampling.LANCZOS)
        mask = Image.new("L", (size, size))
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        mask = Image.composite(image.getchannel("A"), Image.new("L", image.size), mask)
        background.paste(image, (x, y), mask)
        if outlined:
            draw.ellipse((x, y, x + size - 1, y + size - 1), outline="#9aaac4", width=1)

    characters = data.get("characters") or []
    character = characters[0] if characters else {}
    groups = data.get("groups") or []
    name = character.get("name") or (groups[0].get("name") if groups else "图库精选")
    group = character.get("group_name") or (groups[0].get("name") if groups else "未分组")
    fallback = art.crop((0, 0, art.width, min(art.width, art.height)))
    avatar(character_avatar, 52, 48, 80, name, fallback=fallback)
    text(154, 45, name, 34, bold=True, max_width=590)
    group_font = font(23)
    while draw.textlength(group, font=group_font) > 390:
        group = group[:-2] + "…"
    text(154, 98, group, 23, muted)
    divider_x = 172 + int(draw.textlength(group, font=group_font))
    draw.line((divider_x, 102, divider_x, 124), fill=divider, width=2)
    rating = {"all": "全年龄", "r12": "R12", "r16": "R16", "r18": "R18"}.get(data.get("age_rating"), "全年龄")
    text(divider_x + 19, 98, rating, 23, muted)
    avatar(_asset_avatar("ukp.png", 80), 866, 48, 80)
    art_mask = Image.new("L", art.size)
    ImageDraw.Draw(art_mask).rounded_rectangle((0, 0, art.width - 1, art.height - 1), radius=14, fill=255)
    background.paste(art, ((width - art.width) // 2, hero_y), art_mask)

    artist = data.get("artist") or {}
    if artist.get("id") or artist.get("name"):
        avatar(artist_avatar, 52, author_y, 74, artist.get("name") or "画")
        author_name = artist.get("name") or f"画师 {artist['id']}"
        author_subtitle = f"Pixiv UID: {artist.get('id') or '未登记'}"
    else:
        avatar(_asset_avatar("picmanager-transparent.png", 74), 52, author_y, 74, outlined=False)
        author_name = "小爱图库"
        site = urlsplit(data.get("card_page_url") or data.get("card_token") or "")
        author_subtitle = site.netloc if site.scheme in {"http", "https"} and site.netloc else "pic.usotsuki-kaze.com"
    text(148, author_y - 2, author_name, 31, bold=True, max_width=540)
    text(148, author_y + 45, author_subtitle, 22, muted, max_width=540)
    text(52, author_y + 102, f"PID: {data.get('pid') or '未记录'}", 24, muted, max_width=600)
    text(52, author_y + 160, "引用本图片并发送", 24, muted)
    command_x = 52 + int(draw.textlength("引用本图片并发送", font=font(24)))
    text(command_x, author_y + 160, "「pic原图」", 24, white, bold=True)
    hint_x = command_x + int(draw.textlength("「pic原图」", font=font(24, bold=True)))
    text(hint_x, author_y + 160, "即可获取原图。", 24, muted)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=5)
    qr.add_data(data["card_token"])
    qr.make(fit=True)
    # Integer-sized light modules with transparent quiet zone on the dark backdrop.
    module_size = max(1, 252 // len(qr.get_matrix()))
    qr_image = qr.make_image(fill_color=white, back_color="transparent").convert("RGBA")
    qr_size = len(qr.get_matrix()) * module_size
    qr_image = qr_image.resize((qr_size, qr_size), Image.Resampling.NEAREST)
    # Align the visible QR top with the author avatar, excluding its quiet zone.
    quiet_zone = qr.border * module_size
    qr_y = author_y - quiet_zone
    background.alpha_composite(qr_image, (948 - qr_size, qr_y))
    footer_y = author_y + 254
    # Both brands form one centered, compact footer instead of spanning the card.
    footer_right = 438  # Same 32px gap as the divider-to-UKP-icon spacing.
    brand_width = max(draw.textlength("PICMANAGER", font=font(16)),
                      draw.textlength("小爱图库", font=font(25, bold=True)))
    avatar(_asset_avatar("picmanager-circle.png", 64), int(footer_right - brand_width - 82), footer_y, 64, outlined=False)
    text(footer_right - draw.textlength("PICMANAGER", font=font(16)), footer_y + 2, "PICMANAGER", 16, muted)
    text(footer_right - brand_width, footer_y + 29, "小爱图库", 25, bold=True)
    draw.line((470, footer_y + 9, 470, footer_y + 55), fill=divider, width=2)
    avatar(_asset_avatar("ukp.png", 60), 502, footer_y + 2, 60, outlined=False)
    text(580, footer_y + 2, "POWERED BY", 16, muted)
    text(580, footer_y + 29, "UsotsukiKaze", 25, bold=True)
    mask = Image.new("L", background.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=36, fill=255)
    canvas = Image.new("RGB", background.size, "#d8e7f3" if theme == "light" else "#111d36")
    canvas.paste(background, mask=mask)
    output = BytesIO()
    canvas.save(output, "JPEG", quality=88, optimize=True)
    return output.getvalue()
