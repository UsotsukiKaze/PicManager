"""Independent personal affinity, inventory purchasing and native discovery policies."""
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import selectinload

from ... import models
from ...config import settings
from ...pixiv_metadata import library_pixiv_pages, split_pid
from .recommendations import allowed, normalize, recommendation_match

MODES = ('personal', 'stock', 'discovery')
POLICY_VERSION = 'conditional-quality-v4'
STOCK_POLICY_VERSION = 'stock-conditional-quality-v2'
SPARSE_CHARACTER_LIMIT = 20
STOCK_POPULARITY_FLOOR = .45
STOCK_DISCOVERY_QUALITY_FLOOR = .40
BASE_NEW_CHARACTER_SHARE = .30
LEGACY_NEW_CHARACTER_SHARE = .15
MAX_NEW_CHARACTER_SHARE = .80
NEW_GROUP_SHARE = .05


def stream_key(mode, actor_id):
    return f'recommendation_stream_{mode}_{actor_id}' if mode in MODES else f'recommendation_stream_{mode}'


def policy_version(mode):
    return STOCK_POLICY_VERSION if mode == 'stock' else POLICY_VERSION


def source_key(source, mode, actor_id):
    return f'{source}_{mode}_{actor_id}' if mode in MODES else source


def inverse_weights(counts):
    values = {id_:1 / max(1, count) for id_, count in counts.items()}
    total = sum(values.values())
    return {id_:value / total for id_, value in values.items()} if total else {}


def new_character_weights(group_weights, character_counts):
    """Reserve exploration within thinly catalogued series without changing known-role quotas."""
    sparse = {group:1 + (SPARSE_CHARACTER_LIMIT - character_counts[group]) / SPARSE_CHARACTER_LIMIT
              for group in group_weights if character_counts[group] <= SPARSE_CHARACTER_LIMIT}
    if not sparse:
        return dict(group_weights)
    sparse_total = sum(sparse.values())
    return {group:0.6 * weight + 0.4 * sparse.get(group, 0) / sparse_total
            for group, weight in group_weights.items()}


def new_character_fraction(character_count):
    """A sparse group's exploration target rises smoothly to 80% at zero roles."""
    if character_count > SPARSE_CHARACTER_LIMIT:
        return BASE_NEW_CHARACTER_SHARE
    return min(MAX_NEW_CHARACTER_SHARE, BASE_NEW_CHARACTER_SHARE +
               (MAX_NEW_CHARACTER_SHARE - BASE_NEW_CHARACTER_SHARE) *
               (SPARSE_CHARACTER_LIMIT + 1 - character_count) / (SPARSE_CHARACTER_LIMIT + 1))


def stock_exploration_plan(profile, hot_groups=None):
    """Per-group targets; cold sparse groups fall back to the stock baseline."""
    fractions = profile.get('new_character_fractions', {})
    baseline = BASE_NEW_CHARACTER_SHARE if fractions else LEGACY_NEW_CHARACTER_SHARE
    effective = {g:(fractions.get(g, baseline)
                    if hot_groups is None or g in hot_groups else baseline)
                 for g in profile['quotas']}
    share = min(MAX_NEW_CHARACTER_SHARE, sum(profile['quotas'][g] * fraction
                                            for g, fraction in effective.items()))
    if profile.get('algorithm')=='stock-conditional-quality-v2':
        share *= 1-NEW_GROUP_SHARE
    known_weights = {g:weight * (1 - effective[g]) for g, weight in profile['quotas'].items()}
    new_weights = {g:weight * effective[g] for g, weight in profile['quotas'].items()}
    def normalized(weights):
        total = sum(weights.values())
        return {g:value / total for g, value in weights.items()} if total else dict(profile['quotas'])
    return share, normalized(known_weights), normalized(new_weights), effective


def library(db):
    return db.query(models.Image).filter_by(file_status='available').options(
        selectinload(models.Image.groups), selectinload(models.Image.characters),
        selectinload(models.Image.feature_tags), selectinload(models.Image.pixiv_metadata),
        selectinload(models.Image.pixiv_sources), selectinload(models.Image.tag_evidence),
    ).all()


def work_id(image):
    if image.pixiv_sources:
        return image.pixiv_sources[0].work_id
    if image.pixiv_metadata:
        return image.pixiv_metadata.work_id
    return (split_pid(image.pid) or (f'local:{image.image_id}',))[0]


def root_snapshots(db, index, account, images):
    root = db.query(models.User).filter_by(role='root', qq_number=settings.ROOT_QQ).first()
    if not root:
        return {}, {}, {}
    likes = {row.pid:row for row in db.query(models.PixivFeedback).filter_by(
        actor_id=root.id, account_revision=account.revision, value='like').all()}
    carts = {row.pid:row.metadata_json for row in db.query(models.PixivCartItem).filter_by(
        actor_id=root.id, account_revision=account.revision).all()}
    snapshots = dict(carts)
    pids = list(likes)
    for start in range(0, len(pids), 500):
        for row in db.query(models.PixivArtwork).filter(
            models.PixivArtwork.account_revision == account.revision,
            models.PixivArtwork.pid.in_(pids[start:start + 500]),
        ).all():
            snapshots[row.pid] = row.metadata_json
    fallback = defaultdict(list)
    for image in images:
        pid, meta = work_id(image), image.pixiv_metadata
        if pid in likes and pid not in snapshots and meta and meta.status == 'verified':
            fallback[pid].append(image)
    for pid, pages in fallback.items():
        tags = {normalize(tag['name']):tag for image in pages for tag in image.pixiv_metadata.tags or [] if tag.get('name')}
        snapshots[pid] = {'tags':list(tags.values()), 'x_restrict':int(any(image.age_rating == 'r18' for image in pages))}
    snapshots = {pid:art for pid, art in snapshots.items() if allowed(art, account.preferences)}
    return likes, {pid:art for pid, art in carts.items() if pid in snapshots}, snapshots


def distribution(values):
    total = math.sqrt(sum(value * value for value in values.values()))
    return {key:value / total for key, value in values.items()} if total else {}


def _selected(index, counts, prefs):
    return [g for g in index.groups if prefs.get('groups', {}).get(str(g), {}).get('enabled', counts[g] > 0)]


def personal_profile(db, index, account, images):
    from .learning import interest_profile
    profile = interest_profile(db, index, account, images, work_id, root_snapshots(db,index,account,images))
    counts = Counter({g:0 for g in index.groups})
    for image in images:
        counts.update(g.id for g in image.groups)
    selected = _selected(index,counts,account.preferences)
    weights = {g:profile['vectors'].get('group',{}).get(g,0) for g in selected}
    total = sum(weights.values())
    weights = {g:v/total for g,v in weights.items()} if total else {g:1/len(selected) for g in selected}
    profile.update(algorithm='personal-conditional-v2',quotas=weights,inventory=dict(counts),
        tags={g:profile['group_features'].get(g,{}) for g in selected},
        characters={g:{r.id:profile['vectors'].get('character',{}).get(r.id,0)
                       for r in index.characters.values() if r.group_id==g} for g in selected},
        liked_raw_global=profile['vectors'].get('raw',{}),liked_raw_tags={})
    return profile


def stock_profile(db, index, account, images):
    counts, roles, features = Counter({g:0 for g in index.groups}), Counter({r:0 for r in index.characters}), Counter()
    units, observed = defaultdict(list), defaultdict(Counter)
    for image in images:
        counts.update(g.id for g in image.groups)
        roles.update(r.id for r in image.characters)
        units[work_id(image)].append(image)
    selected = _selected(index, counts, account.preferences)
    for pages in units.values():
        values = defaultdict(list)
        for image in pages:
            evidence = {row.feature_tag_id:row.confidence for row in image.tag_evidence}
            inherited = {tag.id for role in image.characters for tag in index.characters[role.id].feature_tags}
            for tag in image.feature_tags:
                if normalize(tag.name) != 'pixiv':
                    values[tag.id].append(evidence.get(tag.id, 0.25 if tag.id in inherited else 0.6))
            if image.pixiv_metadata and image.pixiv_metadata.status == 'verified':
                match = index.match(image.pixiv_metadata.tags or [], group_context={g.id for g in image.groups})
                for row in match['evidence']:
                    if row['type'] == 'feature':
                        observed[row['id']][row['pixiv_tag']] += 1 / len(pages)
        for tag, values_ in values.items():
            features[tag] += sum(values_) / len(pages)
    _, _, snapshots = root_snapshots(db, index, account, images)
    for art in snapshots.values():
        match = recommendation_match(index, art.get('tags', []), index.groups)
        for tag in match['feature_tag_ids']:
            if normalize(index.features[tag].name) != 'pixiv':
                features[tag] += 0.6
        for row in match['evidence']:
            if row['type'] == 'feature':
                observed[row['id']][row['pixiv_tag']] += 1
    vector = distribution(features)
    role_quotas = {g:inverse_weights({r.id:roles[r.id] for r in index.characters.values() if r.group_id == g}) for g in selected}
    seeds = defaultdict(Counter)
    for pid, pages in units.items():
        if not str(pid).isdigit():
            continue
        for image in pages:
            for role in image.characters:
                seeds[role.group_id][pid] = max(seeds[role.group_id][pid], 1 / max(1, roles[role.id]))
    group_quotas = inverse_weights({g:counts[g] for g in selected})
    character_counts = Counter(role.group_id for role in index.characters.values())
    interest = personal_profile(db,index,account,images)
    return {**interest, 'algorithm':'stock-conditional-quality-v2', 'inventory':dict(counts),
            'character_inventory':dict(roles), 'character_counts':{g:character_counts[g] for g in selected},
            'sparse_character_groups':[g for g in selected if character_counts[g] <= SPARSE_CHARACTER_LIMIT],
            'new_character_fractions':{g:new_character_fraction(character_counts[g]) for g in selected},
            'new_character_quotas':new_character_weights(group_quotas, character_counts),
            'quotas':group_quotas,
            'character_quotas':role_quotas, 'characters':role_quotas,
            'tags':{g:interest['group_features'].get(g,vector) for g in selected}, 'feature_vector':interest['vectors'].get('feature',vector),
            'liked_raw_global':{}, 'liked_raw_tags':{}, 'raw_tag_names':{},
            'feature_query_tags':interest['feature_query_tags'],
            'related_seeds':{g:[pid for pid, _ in values.most_common(12)] for g, values in seeds.items()}}


def build_profile(db, index, account, mode):
    if mode == 'discovery':
        return {'algorithm':'pixiv-native-v1', 'quotas':{}, 'related_seeds':{}}
    images = library(db)
    return personal_profile(db, index, account, images) if mode == 'personal' else stock_profile(db, index, account, images)


def search_plan(db, index, profile, preferences, mode, rotation):
    """Share tag resolution and transport, never share a ranking policy."""
    from .search_plan import build_search_plan
    if mode == 'discovery':
        return []
    targeted = build_search_plan(db, index, profile, preferences, rotation=rotation, stock=mode == 'stock')
    broad = []
    if mode == 'personal':
        words = [profile['raw_tag_names'].get(key, key) for key, _ in sorted(
            profile['vectors'].get('raw', {}).items(), key=lambda row:(-row[1], row[0]))[:8]]
    else:
        words = []
        for tag, _ in sorted(profile['feature_vector'].items(), key=lambda row:(-row[1], row[0]))[:8]:
            bound = [row.original_tag or row.normalized_tag for row in db.query(models.PixivTagMapping).filter_by(
                target_type='feature', target_id=tag, group_context=0).order_by(models.PixivTagMapping.id).all()]
            # Stock searches use a confirmed Pixiv binding first, then an
            # original tag observed on verified works; local label names are
            # not reliable Pixiv search terms.
            words.extend(bound[:1] or profile['feature_query_tags'].get(tag, [])[:1])
    blocked = {normalize(word) for word in preferences.get('blocked_tags', [])}
    for word in words:
        if normalize(word) not in blocked and not index.is_ignored(word):
            broad.append({'group':None, 'word':word, 'search_target':'exact_match_for_tags',
                          'source':'personal_tag' if mode == 'personal' else 'feature_exploration', 'terms':[word]})
    if broad:
        start = rotation % len(broad)
        broad = (broad[start:] + broad[:start])[:4]
    # Personal mixes broad queries early; stock keeps them behind shortage recall.
    result, seen = [], set()
    for query in (targeted + broad if mode == 'stock' else targeted[:2] + broad + targeted[2:]):
        key = (normalize(query['word']), query['search_target'])
        if key not in seen:
            seen.add(key)
            result.append(query)
    return result if mode == 'stock' else result[:20]


def cosine(vector, ids):
    ids = set(ids)
    return sum(vector.get(id_, 0) for id_ in ids) / math.sqrt(len(ids)) if ids else 0


def recent_popularity(item, now):
    from .learning import quality
    return quality(item,now)


def _candidates(db, index, account, mode, actor_id, seen_pids, *, source_batch=None):
    excluded = set(library_pixiv_pages(db)) | set(seen_pids)
    excluded.update(row[0] for row in db.query(models.PixivCartItem.pid).filter_by(
        account_revision=account.revision, actor_id=actor_id).all())
    excluded.update(row[0] for row in db.query(models.PixivFeedback.pid).filter_by(
        account_revision=account.revision, actor_id=account.owner_id, value='dislike').all())
    source = source_key('recommended', mode, actor_id)
    batch = source_batch or account.sync_state.get(source, {}).get('batch')
    prepared = []
    for row in db.query(models.PixivArtwork).filter_by(account_revision=account.revision).order_by(
        models.PixivArtwork.fetched_at.desc(), models.PixivArtwork.id.desc()).limit(5000 if mode == 'stock' else 1000).all():
        art = row.metadata_json
        if row.pid in excluded or not allowed(art, account.preferences):
            continue
        origins = [origin for origin in row.origins if origin.get('batch') == batch] if batch else row.origins
        native = [o.get('rank') if o.get('rank') is not None else 100 for o in origins if o.get('source') == source]
        if mode == 'discovery' and not native:
            continue
        if mode != 'discovery':
            native += [o['rank'] for o in origins if o.get('source') == source_key('related',mode,actor_id) and o.get('rank') is not None]
        if batch and not origins:
            continue
        match = recommendation_match(index, art['tags'], index.groups)
        item = {**art, 'match':match, 'origins':origins, 'imported_pages':[], 'reasons':[]}
        prepared.append((item, min(native) if native else None))
    return prepared


def rank(db, index, account, mode, actor_id, seen_pids=()):
    from .recommendations import input_revision
    profile = build_profile(db, index, account, mode)
    profile.update({'policy_version':policy_version(mode), 'actor_id':actor_id, 'mode':mode})
    profile['input_revision']=input_revision(index,account.preferences)
    candidates = _candidates(db, index, account, mode, actor_id, seen_pids)
    if mode=='stock':
        # Carry recent actual exposure deficits across independently refreshed batches.
        history=Counter()
        for row in db.query(models.PixivRecommendationExposure).filter(
                models.PixivRecommendationExposure.account_revision==account.revision,
                models.PixivRecommendationExposure.actor_id==actor_id,
                models.PixivRecommendationExposure.metadata_json['mode'].as_string()=='stock').order_by(
                models.PixivRecommendationExposure.id.desc()).limit(500):
            meta=row.metadata_json
            kind=meta.get('stock_pool')
            if kind:
                history[str((kind,meta.get('primary_group'),meta.get('primary_character')))]+=1
        profile['quota_history']=dict(history)
    if mode == 'discovery':
        return [item for item, _ in sorted(candidates, key=lambda row:(row[1], row[0]['pid']))][:180], profile
    from .learning import affinity, quality, QualityReference, age
    now = datetime.utcnow()
    matched={item['pid']:item['match'] for item,_ in candidates}
    historical=[]
    for row in db.query(models.PixivArtwork).filter_by(account_revision=account.revision).order_by(
            models.PixivArtwork.fetched_at.desc()).limit(5000):
        art=row.metadata_json
        if art.get('bookmarks') is not None:
            historical.append({**art,'match':matched.get(row.pid) or recommendation_match(index,art.get('tags',[]),index.groups)})
    reference = QualityReference(historical,now)
    for item, native_rank in candidates:
        native = 1 / math.log2(native_rank + 2) if native_rank is not None else 0
        q = quality(item,now,reference)
        exploratory = mode == 'stock' and stock_identity(item,profile,index)[0] != 'known'
        a = affinity(profile,item,exploration=exploratory)
        item['ranking_signals'] = {'affinity':round(a,4),'quality':round(q,4),'native':round(native,4),
                                  'policy':policy_version(mode)}
        item['_quality'] = q
        days=age(item,now)
        item['age_bucket']='recent' if days<=30 else 'middle' if days<=180 else 'historical'
        item['_score'] = .45*a+.35*q+.20*native if mode == 'personal' else .60*q+.25*a+.15*native
    if mode == 'personal':
        from .scheduling import take
        pool, chosen, authors = sorted([item for item, _ in candidates if item.get('bookmarks') is None or item['_quality']>=.50], key=lambda item:(-item['_score'], item['pid'])), [], Counter()
        while pool and len(chosen) < 180:
            if len(chosen) % 20 == 0:
                authors.clear()
            item = take(pool,chosen,authors,role_cap=True)
            authors[item['author_id']] += 1
            item.pop('_score')
            item.pop('_quality',None)
            chosen.append(item)
        return chosen, profile
    return stock_schedule([item for item, _ in candidates], profile, index), profile


def stock_identity(item, profile, index):
    match = item['match']
    confirmed_groups = {row['id'] for row in match.get('evidence', ())
                        if row['type'] == 'group' and row['basis'] == 'confirmed_mapping'}
    confirmed_roles = {row['id'] for row in match.get('evidence', ())
                       if row['type'] == 'character' and row['basis'] == 'confirmed_mapping'}
    bound_groups = getattr(index, 'bound_groups', set())
    bound_roles = getattr(index, 'bound_characters', set())
    groups = [g for g in match['group_ids'] if g in profile['quotas'] and
              (g not in bound_groups or g in confirmed_groups or
               any(index.characters[r].group_id == g for r in confirmed_roles))]
    if not match['group_ids'] and not match['conflicts']:
        return 'new_group', None, None
    if groups:
        roles = [r for r in match['character_ids'] if index.characters[r].group_id in groups
                 and (r not in bound_roles or r in confirmed_roles)]
        if roles:
            role = min(roles, key=lambda r:(profile['character_inventory'].get(r, 0), r))
            return 'known', index.characters[role].group_id, role
        if not roles and not match['conflicts'] and not confirmed_roles:
            sparse = profile.get('sparse_character_groups', ())
            weights = profile.get('new_character_quotas', profile['quotas'])
            group = max(groups, key=lambda g:(g in sparse, weights.get(g, 0),
                                               -profile['inventory'][g], -g))
            return 'new_character', group, None
    return None, None, None


def stock_supply(candidates, profile, index):
    groups, roles = Counter(), Counter()
    for item, _ in candidates:
        kind, group, role = stock_identity(item, profile, index)
        if kind == 'known':
            groups[group] += 1
            roles[role] += 1
    return groups, roles


def stock_new_character_supply(candidates, profile, index, *, min_quality=0):
    supply = Counter()
    now = datetime.utcnow()
    for item, _ in candidates:
        kind, group, _ = stock_identity(item, profile, index)
        if kind == 'new_character' and (not min_quality or recent_popularity(item, now) >= min_quality):
            supply[group] += 1
    return supply


def stock_new_character_gap(group, supply, profile):
    fractions = profile.get('new_character_fractions')
    if fractions:
        target = max(3, math.ceil(180 * profile['quotas'].get(group, 0) *
                                  fractions.get(group, BASE_NEW_CHARACTER_SHARE)))
    else:
        target = max(3, math.ceil(27 * profile.get('new_character_quotas', profile['quotas']).get(group, 0)))
    return max(0, target - supply[group])


def recall_quality_floor(profile):
    return .60 if profile.get('algorithm')=='stock-conditional-quality-v2' else STOCK_POPULARITY_FLOOR


def stock_query_gap(query, profile, groups, roles):
    group, role = query['group'], query.get('character')
    share, known_weights, _, _ = stock_exploration_plan(profile)
    target = 180 * (1 - share - NEW_GROUP_SHARE) * known_weights.get(group, 0)
    return max(0, target - groups[group]), max(0, target * profile.get('character_quotas', {}).get(group, {}).get(role, 0) - roles[role])


def stock_recall_queries(queries, candidates, profile, index, limit=3):
    """Search mapped series for new faces before topping up familiar roles."""
    groups, roles = stock_supply(candidates, profile, index)
    new_roles = stock_new_character_supply(candidates, profile, index, min_quality=recall_quality_floor(profile))
    picked, remaining = [], list(queries)
    ranking=next((query for query in remaining if query.get('source')=='ranking'),None)
    if ranking and limit:
        picked.append(ranking)
        remaining.remove(ranking)
    used_groups = set()
    sparse = set(profile.get('sparse_character_groups', ()))
    for _ in range(min(2, max(0, limit - len(picked) - 1))):
        anchors = [query for query in remaining if query['group'] in profile['quotas']
                   and query.get('source') in ('group_popular', 'group_mapping', 'group_name')
                   and stock_new_character_gap(query['group'], new_roles, profile) > 0]
        if not anchors:
            break
        query = max(anchors, key=lambda entry:(
            entry['group'] not in used_groups,
            entry.get('source') == 'group_popular',
            stock_new_character_gap(entry['group'], new_roles, profile),
            entry['group'] in sparse,
            entry.get('source') == 'group_mapping',
            profile.get('new_character_quotas', profile['quotas']).get(entry['group'], 0),
            -remaining.index(entry)))
        picked.append(query)
        remaining.remove(query)
        used_groups.add(query['group'])
    while remaining and len(picked) < limit:
        def priority(query):
            group, role = query['group'], query.get('character')
            gap, role_gap = stock_query_gap(query, profile, groups, roles)
            anchored = group is not None
            # An exact role mapping can supply the known-role pool directly;
            # a missing series mapping must not demote its bound characters.
            return (anchored and (gap > 0 or role_gap > 0), group not in used_groups,
                    max(gap, role_gap), query.get('source') == 'character_mapping' and role_gap > 0,
                    role_gap, anchored, -remaining.index(query))
        query = max(remaining, key=priority)
        picked.append(query)
        remaining.remove(query)
        used_groups.add(query['group'])
    return picked


def _weighted_pick(active, weights, credits):
    """Accumulate normalized credit only while a bucket has actual supply."""
    total = sum(weights.get(key, 0) for key in active)
    for key in active:
        credits[key] += weights.get(key, 0) / total if total else 1 / len(active)
    key = max(active, key=lambda key:(credits[key], -key))
    credits[key] -= 1
    return key


def stock_schedule(items, profile, index):
    if profile.get('policy_version') == STOCK_POLICY_VERSION:
        from .scheduling import stock_schedule as schedule
        return schedule(items,profile,index)
    known, new_roles, new_groups = defaultdict(lambda:defaultdict(list)), defaultdict(list), []
    adaptive = bool(profile.get('new_character_fractions'))
    for item in items:
        kind, group, role = stock_identity(item, profile, index)
        if adaptive and kind in ('new_character', 'new_group') and item.get('_quality', 0) < STOCK_DISCOVERY_QUALITY_FLOOR:
            continue
        if kind:
            item['stock_pool'] = kind
        if kind == 'new_group':
            new_groups.append(item)
        elif kind == 'known':
            item['primary_group'], item['primary_character'] = group, role
            known[group][role].append(item)
        elif kind == 'new_character':
            item['primary_group'] = group
            new_roles[group].append(item)
    all_pools = [pool for roles in known.values() for pool in roles.values()] + list(new_roles.values()) + [new_groups]
    for pool in all_pools:
        pool.sort(key=lambda item:(-item['_score'], item['pid']))
    sparse = set(profile.get('sparse_character_groups', ()))
    for group in sparse:
        if group in new_roles:
            new_roles[group].sort(key=lambda item:(-item.get('_quality', 0), -item['_score'], item['pid']))
    hot_sparse = {g for g in sparse if any(item.get('_quality', 0) >= STOCK_POPULARITY_FLOOR
                                          for item in new_roles.get(g, ()))}
    share, known_weights, new_weights, fractions = stock_exploration_plan(profile, hot_sparse)
    known_n = sum(len(pool) for roles in known.values() for pool in roles.values())
    role_n, group_n = sum(map(len, new_roles.values())), len(new_groups)
    target = min(180, known_n + role_n + group_n)
    hot_counts = {g:sum(item.get('_quality', 0) >= STOCK_POPULARITY_FLOOR for item in pool)
                  for g, pool in new_roles.items()}
    def exploration_cap(group, batch_size):
        baseline = math.ceil(batch_size * profile['quotas'][group] * BASE_NEW_CHARACTER_SHARE)
        target_cap = math.ceil(batch_size * profile['quotas'][group] * fractions[group])
        return min(target_cap, baseline + hot_counts[group] if group in sparse else target_cap)
    new_caps = ({g:exploration_cap(g, target) for g in new_roles}
                if adaptive else {g:len(pool) for g, pool in new_roles.items()})
    role_n = sum(min(len(pool), new_caps[g]) for g, pool in new_roles.items())
    desired_known = target - min(role_n, int(target * share)) - min(group_n, int(target * NEW_GROUP_SHARE))
    group_caps = {g:max(2, math.ceil(desired_known * weight * 1.25)) for g, weight in known_weights.items()}
    role_caps = {g:{r:max(2, math.ceil(group_caps[g] * weight * 1.25))
                   for r, weight in weights.items()} for g, weights in profile['character_quotas'].items()}
    # Bounded rounding/25% overflow is allowed. A missing cold group must not
    # donate its entire budget to a large group with abundant native candidates.
    for g, roles in known.items():
        for r in roles:
            roles[r] = roles[r][:role_caps[g][r]]
    known_n = sum(min(group_caps[g], sum(map(len, roles.values()))) for g, roles in known.items())
    # Never silently turn a short supply of known roles into mostly exploration.
    while True:
        if adaptive:
            new_caps = {g:exploration_cap(g, target) for g in new_roles}
            role_n = sum(min(len(pool), new_caps[g]) for g, pool in new_roles.items())
        next_target = min(target, known_n + min(role_n, int(target * share)) +
                          min(group_n, int(target * NEW_GROUP_SHARE)))
        if next_target == target:
            break
        target = next_target
    limits = {'new_character':min(role_n, int(target * share)), 'new_group':min(group_n, int(target * NEW_GROUP_SHARE))}
    limits['known'] = min(known_n, target - sum(limits.values()))
    assigned, group_assigned, role_assigned, new_assigned, authors = Counter(), Counter(), Counter(), Counter(), Counter()
    group_credit, role_credit, new_credit = Counter(), defaultdict(Counter), Counter()
    chosen = []

    def take(pool, *, popularity_first=False):
        best = max(range(min(30, len(pool))), key=lambda n:(
            (0.7 * pool[n].get('_quality', 0) + 0.3 * pool[n]['_score'] if popularity_first else pool[n]['_score'])
            - .03 * authors[pool[n]['author_id']]))
        return pool.pop(best)

    while len(chosen) < sum(limits.values()):
        if len(chosen) % 20 == 0:
            authors.clear()
        category = max((kind for kind in limits if assigned[kind] < limits[kind]),
                       key=lambda kind:({'known':1 - share - NEW_GROUP_SHARE,
                                         'new_character':share, 'new_group':NEW_GROUP_SHARE}[kind] * (len(chosen) + 1) - assigned[kind], kind))
        if category == 'known':
            groups = [g for g, roles in known.items() if any(roles.values()) and group_assigned[g] < group_caps[g]]
            g = _weighted_pick(groups, known_weights, group_credit)
            roles = [r for r, pool in known[g].items() if pool]
            r = _weighted_pick(roles, profile['character_quotas'][g], role_credit[g])
            item = take(known[g][r])
            group_assigned[g] += 1
            role_assigned[r] += 1
        elif category == 'new_character':
            active = [g for g, pool in new_roles.items() if pool and new_assigned[g] < new_caps[g]]
            boosted = profile.get('new_character_quotas', profile['quotas'])
            weights = new_weights if adaptive else ({g:(profile['quotas'][g] if g in sparse and g not in hot_sparse else boosted[g])
                                                      for g in active} if hot_sparse else profile['quotas'])
            g = _weighted_pick(active, weights, new_credit)
            item = take(new_roles[g], popularity_first=g in sparse)
            new_assigned[g] += 1
        else:
            item = take(new_groups)
        item.pop('_score')
        item.pop('_quality', None)
        chosen.append(item)
        assigned[category] += 1
        authors[item['author_id']] += 1
    profile.update({'new_character_share':share, 'known_target':desired_known,
                    'new_character_caps':new_caps, 'group_caps':group_caps,
                    'group_shortfalls':{g:max(0, math.ceil(desired_known * weight) - group_assigned[g])
                                        for g, weight in known_weights.items()},
                    'assigned_pools':dict(assigned), 'assigned_groups':dict(group_assigned),
                    'assigned_new_character_groups':dict(new_assigned),
                    'assigned_characters':dict(role_assigned), 'supply_gaps':[kind for kind in ('new_character', 'new_group') if assigned[kind] < int(len(chosen) * {'new_character':share, 'new_group':NEW_GROUP_SHARE}[kind])]})
    return chosen


def stock_page(rows, limit, profile=None):
    """Reapply independent exploration caps after live library/cart exclusions.

    Positions remain the immutable batch offsets. Skipped exploration can be
    reconsidered by the next ranked batch; seen PIDs only include returned cards.
    """
    if (profile or {}).get('policy_version') == STOCK_POLICY_VERSION:
        return rows[:limit]
    supply = Counter(item.get('stock_pool', 'known') for _, item in rows)
    share = min(MAX_NEW_CHARACTER_SHARE, max(LEGACY_NEW_CHARACTER_SHARE,
                (profile or {}).get('new_character_share', LEGACY_NEW_CHARACTER_SHARE)))
    target = min(limit, len(rows))
    while target > supply['known'] + min(supply['new_character'], int(target * share)) + min(supply['new_group'], int(target * NEW_GROUP_SHARE)):
        target = supply['known'] + min(supply['new_character'], int(target * share)) + min(supply['new_group'], int(target * NEW_GROUP_SHARE))
    caps = {'new_character':min(supply['new_character'], int(target * share)), 'new_group':min(supply['new_group'], int(target * NEW_GROUP_SHARE))}
    caps['known'] = target - sum(caps.values())
    chosen, counts = [], Counter()
    for row in rows:
        kind = row[1].get('stock_pool', 'known')
        if counts[kind] < caps.get(kind, 0):
            chosen.append(row)
            counts[kind] += 1
            if len(chosen) == target:
                break
    return chosen
