"""Shared mappings owned by library entities; exact matches never overwrite manual decisions."""
from datetime import datetime
from sqlalchemy import func
from . import models
from .integrations.pixiv_ol.recommendations import normalize


def save_mapping(db, tag, kind, target_id, context=0, source='manual', *, replace=False):
    classes={'group':models.Group,'character':models.Character,'feature':models.FeatureTag}
    target=db.get(classes[kind],target_id) if kind in classes else None
    if kind not in (*classes,'ignore') or (kind!='ignore' and not target):
        raise ValueError('目标标签不存在')
    if not str(tag).strip() or len(tag)>255:
        raise ValueError('Pixiv 标签无效')
    if kind=='character':
        if context and context!=target.group_id:
            raise ValueError('角色不属于该分组')
        context=target.group_id
    if context and not db.get(models.Group,context):
        raise ValueError('上下文分组不存在')
    key=normalize(tag)
    query=db.query(models.PixivTagMapping).filter_by(normalized_tag=key,group_context=context)
    rows=query.all()
    if not rows and context and source=='exact':
        existing=db.query(models.PixivTagMapping).filter_by(normalized_tag=key,group_context=0,source='manual').first()
        if existing:return existing,False
    if rows and source=='exact':
        return rows[0],False
    row=next((row for row in rows if (row.target_type,row.target_id)==(kind,target_id if kind!='ignore' else None)),None)
    # Ignore is a scope-wide decision; adding a target explicitly lifts it.
    for previous in rows:
        if previous is not row and (replace or kind=='ignore' or previous.target_type=='ignore'):
            db.delete(previous)
    db.flush()
    if not row:
        row=models.PixivTagMapping(normalized_tag=key,group_context=context)
        db.add(row)
    row.target_type,row.target_id=kind,target_id if kind!='ignore' else None
    row.original_tag,row.source,row.confirmed_at=tag.strip(),source,datetime.utcnow()
    db.flush()
    return row,True


def selected_groups(db, preferences):
    counts=dict(db.query(models.image_group_association.c.group_id,func.count(models.image_group_association.c.image_id)).join(models.Image,models.Image.image_id==models.image_group_association.c.image_id).filter(models.Image.file_status=='available').group_by(models.image_group_association.c.group_id).all())
    return {group.id for group in db.query(models.Group).all() if preferences.get('groups',{}).get(str(group.id),{}).get('enabled',counts.get(group.id,0)>0)}


def exact_mappings(db, tags, preferences):
    enabled=selected_groups(db,preferences)
    groups=db.query(models.Group).filter(models.Group.id.in_(enabled)).all() if enabled else []
    characters=db.query(models.Character).filter(models.Character.group_id.in_(enabled)).all() if enabled else []
    names={str(tag.get('name','')).strip() for tag in tags if isinstance(tag,dict)}
    created=0
    for kind,objects in [('group',groups),('character',characters)]:
        by_name={}
        for obj in objects:
            by_name.setdefault((obj.name.strip(),obj.group_id if kind=='character' else 0),[]).append(obj)
        for (name,context),matches in by_name.items():
            if name in names and len(matches)==1:
                _,added=save_mapping(db,name,kind,matches[0].id,context,'exact')
                created+=added
    return created


def sync_cached_exact(db):
    account=db.get(models.PixivAccount,1)
    if not account:
        return 0
    tags={}
    for (stored,) in db.query(models.PixivImageMetadata.tags).all():
        for tag in stored or []:
            if isinstance(tag,dict): tags[tag.get('name','')]=tag
    for (art,) in db.query(models.PixivArtwork.metadata_json).all():
        for tag in (art or {}).get('tags',[]):
            if isinstance(tag,dict): tags[tag.get('name','')]=tag
    return exact_mappings(db,list(tags.values()),account.preferences)


def check_image_tags(db,image,art,*,apply_matches=False):
    from .integrations.pixiv_ol.recommendations import TagIndex
    account=db.get(models.PixivAccount,1)
    if not account:return 0
    created=exact_mappings(db,art.get('tags',[]),account.preferences)
    if not apply_matches:
        return created
    match=TagIndex(db).match(art.get('tags',[]))
    enabled=selected_groups(db,account.preferences)
    for group in db.query(models.Group).filter(models.Group.id.in_(set(match['group_ids']) & enabled)).all():
        if group not in image.groups:image.groups.append(group)
    for character in db.query(models.Character).filter(models.Character.id.in_(match['character_ids']),models.Character.group_id.in_(enabled)).all():
        if character not in image.characters:image.characters.append(character)
        if character.group not in image.groups:image.groups.append(character.group)
    return created


class CachedImageTagCheck:
    """Repair cached library tag links without fetching or replacing page labels."""
    def __init__(self, db):
        self.db = db
        self.index = None

    def check(self, image):
        from .pixiv_metadata import backfill_checked_tags, ensure_source_tag
        from .integrations.pixiv_ol.recommendations import TagIndex, explicit_role_bundle

        result = dict(tag_checked=0, tag_updated=0, tag_links_added=0,
                      tag_mappings_created=0, tag_pending=0)
        before = ({row.id for row in image.groups}, {row.id for row in image.characters},
                  {row.id for row in image.feature_tags})
        repaired = backfill_checked_tags(self.db, images=[image])
        meta = image.pixiv_metadata
        if not meta or meta.status != 'verified':
            return result
        tags = [tag for tag in meta.tags or [] if isinstance(tag, dict)
                and isinstance(tag.get('name'), str) and tag['name'].strip()]
        if not tags:
            return result
        ensure_source_tag(self.db, image)
        if self.index is None:
            self.db.flush()
            self.index = TagIndex(self.db)
        index = self.index
        context = {row.id for row in image.groups} | {row.group_id for row in image.characters}
        match = index.match(tags, group_context=context)
        # Restore missing parent links for manual roles; preserve populated groups.
        for role in image.characters:
            if role.group not in image.groups:
                image.groups.append(role.group)
        if not image.groups and (meta.page_count == 1 or len(match['group_ids']) == 1):
            image.groups.extend(index.groups[id_] for id_ in match['group_ids'])
        # Work tags cannot decide a multi-page image's characters. A populated
        # role selection is always a manual decision, even for single-page work.
        if not image.characters and meta.page_count == 1 and (
            len(match['character_ids']) == 1 or explicit_role_bundle(match, match['character_ids'])
        ):
            for id_ in match['character_ids']:
                role = index.characters[id_]
                if not image.groups or role.group_id in {row.id for row in image.groups}:
                    image.characters.append(role)
                    if role.group not in image.groups:
                        image.groups.append(role.group)
        for id_ in match['feature_tag_ids']:
            tag = index.features[id_]
            if tag not in image.feature_tags:
                image.feature_tags.append(tag)
        selected = {'group':{row.id for row in image.groups},
                    'character':{row.id for row in image.characters},
                    'feature':{row.id for row in image.feature_tags}}
        pending = set(match['unmatched'] + match['conflicts'])
        for evidence in match['evidence']:
            kind, target_id = evidence['type'], evidence['id']
            if kind == 'ignore':
                continue
            if target_id not in selected[kind]:
                pending.add(evidence['pixiv_tag'])
                continue
            if evidence['basis'] == 'confirmed_mapping':
                continue
            if len(evidence['pixiv_tag']) > 255:
                pending.add(evidence['pixiv_tag'])
                continue
            row, created = save_mapping(self.db, evidence['pixiv_tag'], kind, target_id, source='exact')
            key = (row.normalized_tag, row.group_context)
            index.mappings[key] = index.mappings.get(key, frozenset()) | {(row.target_type, row.target_id)}
            result['tag_mappings_created'] += int(created)
        after = (selected['group'], selected['character'], selected['feature'])
        result['tag_checked'] = 1
        result['tag_links_added'] = sum(len(current - previous) for current, previous in zip(after, before))
        result['tag_updated'] = int(bool(repaired or result['tag_links_added'] or result['tag_mappings_created']))
        result['tag_pending'] = int(bool(pending))
        return result
