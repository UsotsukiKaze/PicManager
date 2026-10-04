"""Import-time visual candidates and durable, file-bound merge reviews."""
import hashlib
import json
import secrets
from pathlib import Path

from ... import models
from ...config import settings
from ...services import ImageService
from ...pixiv_metadata import canonical_pid


def signature(image):
    path = Path(ImageService.image_full_path(image))
    try:
        stat = path.stat()
        file = [str(path), stat.st_size, stat.st_mtime_ns]
    except OSError:
        file = [str(path), None, None]
    data = [file, image.file_size, image.width, image.height, image.original_filename,
            image.pid, image.description, image.age_rating, image.file_status,
            sorted(x.id for x in image.groups), sorted(x.id for x in image.characters),
            sorted(x.id for x in image.feature_tags)]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


def candidates(db, stage, perceptual, group_ids):
    rows = db.query(models.Image).filter(
        models.Image.file_status == 'available', models.Image.perceptual_hash.isnot(None),
        models.Image.groups.any(models.Group.id.in_(group_ids)),
    ).all()
    matches = {}
    for image in rows:
        distance = ImageService.dhash_distance(perceptual, image.perceptual_hash)
        if distance <= settings.DUPLICATE_DHASH_DISTANCE:
            matches[image.image_id] = {'image_id': image.image_id, 'distance': distance, 'algorithm': 'dhash64'}
    # The same bounded fingerprint index used by recommendation hints also
    # recognizes screenshots and resized originals outside the selected group.
    from ...visual_similarity import match_cached_preview
    for match in match_cached_preview(db, stage):
        image = db.get(models.Image, match['image_id'])
        if image and image.file_status == 'available':
            matches[image.image_id] = {**matches.get(image.image_id, {}), **match, 'algorithm': 'visual64-grid-v1'}
    return sorted(matches.values(), key=lambda row: (-row.get('score', 0), row.get('distance', 65)))[:20]


def review(db, art, page, tags, stage, near, done, cart_id=None, reason=None):
    from ...routers.public_api.uploads import _incoming_duplicate_match
    from .image_limits import open_image
    with open_image(stage) as image:
        extension = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp', 'GIF': 'gif', 'BMP': 'bmp'}.get(image.format, 'img')
    incoming = _incoming_duplicate_match(db, str(stage), {
        **tags, 'pid': canonical_pid(art['pid'], page), 'description': art['title'],
        'age_rating': 'r18' if art['x_restrict'] else tags.get('age_rating', 'all'),
    }, f"{art['pid']}_p{page}.{extension}")
    incoming['feature_tag_names'] = list(dict.fromkeys(incoming['feature_tag_names'] + tags.get('new_tags', [])))
    incoming['thumbnail_url'] = (f'/api/pixiv-ol/cart/{cart_id}/reader-preview' if cart_id
                                 else f"/api/pixiv-ol/artworks/{art['pid']}/reader-preview") + f'?page={page}'
    comparisons, signatures = [], {}
    for match in near:
        image = db.get(models.Image, match['image_id'])
        if image:
            comparisons.append({**ImageService._duplicate_match(image, match.get('distance', 0)), **match,
                                'comparison_url': f'/resource/originals/{image.image_id}'})
            signatures[image.image_id] = signature(image)
    return {'page': page, 'duplicates': comparisons, 'incoming': incoming, 'done': done,
            'review_key': secrets.token_hex(16), 'candidate_signatures': signatures, 'review_reason': reason}


def feature_ids(db, tags):
    from .recommendations import TagIndex
    from .provider import PixivError
    ids = list(tags.get('feature_tag_ids', []))
    index = TagIndex(db)
    for name in tags.get('new_tags', []):
        matched = index.match([{'name': name}])
        if matched['feature_tag_ids']:
            ids.extend(matched['feature_tag_ids'])
        elif matched['group_ids'] or matched['character_ids'] or matched['conflicts']:
            raise PixivError('tag_conflict')
        else:
            tag = models.FeatureTag(name=name)
            db.add(tag)
            db.flush()
            ids.append(tag.id)
    return list(set(ids))
