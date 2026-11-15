"""Repair historical imported artist avatars: python scripts/backfill_artist_avatars.py."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.database import get_db_context
from app.routers.integrations.bot_cards import artist_avatar


def repair(artist_id):
    try:
        artist_avatar(artist_id)
        return True
    except Exception as exc:
        print(f"Unavailable artist {artist_id}: {exc}", flush=True)
        return False


if __name__ == "__main__":
    with get_db_context() as db:
        ids = [row.id for row in db.query(models.PixivArtist.id).all()]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(repair, ids))
    print(f"Artist avatars ready: {sum(results)}/{len(ids)}")
