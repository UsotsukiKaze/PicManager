import asyncio
import io

import pytest
import qrcode
from fastapi import HTTPException, UploadFile
from PIL import Image

from app.routers.integrations import bot_cards
from app import artist_avatars


def qr_bytes(value):
    output = io.BytesIO()
    qrcode.make(value).save(output, "PNG")
    return output.getvalue()


def test_signed_card_identity_survives_jpeg_and_keeps_audience(monkeypatch):
    payload = qr_bytes(bot_cards.card_token("A123456789"))
    output = io.BytesIO()
    Image.open(io.BytesIO(payload)).convert("RGB").save(output, "JPEG", quality=60)
    calls = []
    monkeypatch.setattr(bot_cards, "card_info", lambda *args: calls.append(args) or {"image_id": args[0]})
    result = asyncio.run(bot_cards.card_original(UploadFile(file=io.BytesIO(output.getvalue())), "group", "42"))
    assert result["image_id"] == "A123456789"
    assert calls == [("A123456789", "group", "42")]


def test_forged_identity_does_not_resolve(monkeypatch):
    monkeypatch.setattr(bot_cards, "card_info", lambda *args: pytest.fail("Forged card must not query images"))
    payload = qr_bytes("picmanager:card:v1:A123456789:" + "0" * 32)
    with pytest.raises(HTTPException) as error:
        asyncio.run(bot_cards.card_original(UploadFile(file=io.BytesIO(payload)), "group", "42"))
    assert error.value.status_code == 404


def test_plain_image_number_qr_keeps_audience(monkeypatch):
    calls = []
    monkeypatch.setattr(bot_cards, 'card_info', lambda *args: calls.append(args) or {'image_id':args[0]})
    result = asyncio.run(bot_cards.card_original(UploadFile(file=io.BytesIO(qr_bytes('picmanager:image:A123456789'))), 'group', '42'))
    assert result['image_id'] == 'A123456789'
    assert calls == [('A123456789','group','42')]


def test_gallery_link_qr_and_foreign_links(monkeypatch):
    monkeypatch.setattr(bot_cards.settings, 'PUBLIC_BASE_URL', 'https://pic.usotsuki-kaze.com')
    calls = []
    monkeypatch.setattr(bot_cards, 'card_info', lambda *args: calls.append(args) or {'image_id':args[0]})
    url = bot_cards.card_url('A123456789')
    result = asyncio.run(bot_cards.card_original(UploadFile(file=io.BytesIO(qr_bytes(url))), 'group', '42'))
    assert result['image_id'] == 'A123456789'
    assert calls == [('A123456789','group','42')]
    assert bot_cards.link_image_id(url.replace('pic.usotsuki-kaze.com','evil.example')) is None
    assert bot_cards.link_image_id('http://[') is None


def test_valid_identity_does_not_bypass_rating(monkeypatch):
    def restricted(*args):
        raise HTTPException(403, "restricted")
    monkeypatch.setattr(bot_cards, "card_info", restricted)
    with pytest.raises(HTTPException) as error:
        asyncio.run(bot_cards.card_original(UploadFile(file=io.BytesIO(qr_bytes(bot_cards.card_token("A123456789"))))))
    assert error.value.status_code == 403


def test_artist_avatar_download_is_persistent_and_reused(tmp_path, monkeypatch):
    from app.integrations.pixiv_ol import provider
    monkeypatch.setattr(artist_avatars.settings, "AVATAR_PATH", str(tmp_path))
    calls = []

    def download(url, destination, **kwargs):
        calls.append(url)
        Image.new("RGB", (512, 512), "blue").save(destination, "PNG")

    monkeypatch.setattr(provider, "download", download)
    art = {"author_id": "123", "author_avatar": "https://i.pximg.net/user-profile/test.jpg"}
    first = artist_avatars.cache_avatar(art)
    assert first == artist_avatars.cache_avatar(art)
    assert len(calls) == 1
    with Image.open(first) as avatar:
        assert avatar.format == "WEBP"
        assert avatar.size == (256, 256)


def test_help_pool_prefers_panorama_and_excludes_portrait():
    from types import SimpleNamespace as Row
    rows=[Row(width=w,height=h) for w,h in [(1000,2000),(1000,0),(1800,1000),(3000,1000),(2600,1000)]]
    pool=bot_cards.wide_help_pool(rows)
    assert [r.width for r in pool]==[3000,2600]
    assert bot_cards.wide_help_pool([Row(width=100,height=200)])==[]


def test_help_pool_sparse_library_keeps_only_widest_group():
    from types import SimpleNamespace as Row
    rows=[Row(width=w,height=1000) for w in [2300,2200,1800,1500,1000]]
    assert [r.width for r in bot_cards.wide_help_pool(rows)]==[2300,2200]
