"""Shared mappings owned by library entities; exact matches never overwrite manual decisions."""
from datetime import datetime
from sqlalchemy import func
from . import models
from .integrations.pixiv_ol.recommendations import normalize


def save_mapping(db, tag, kind, target_id, context=0, source='manual'):
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
    row=db.query(models.PixivTagMapping).filter_by(normalized_tag=key,group_context=context).first()
    if not row and context and source=='exact':
        existing=db.query(models.PixivTagMapping).filter_by(normalized_tag=key,group_context=0,source='manual').first()
        if existing:return existing,False
    if row and source=='exact':
        return row,False
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


def check_image_tags(db,image,art,*,apply_matches=True):
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
