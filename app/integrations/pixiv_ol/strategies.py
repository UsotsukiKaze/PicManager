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
POLICY_VERSION = 'three-modes-v3'
STOCK_POLICY_VERSION = 'stock-sparse-v1'
SPARSE_CHARACTER_LIMIT = 20
STOCK_POPULARITY_FLOOR = .35


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
    """Three independently normalized channels; inventory never determines affinity."""
    channels = {kind:defaultdict(Counter) for kind in ('library', 'likes', 'cart')}
    raw_names, observed, seeds = {}, defaultdict(Counter), Counter()
    units = defaultdict(list)
    for image in images:
        units[work_id(image)].append(image)

    def record(channel, tags, match, weight=1):
        words = {normalize(tag['name']):tag['name'] for tag in tags if tag.get('name')}
        ignored = {normalize(row['pixiv_tag']) for row in match['evidence'] if row['type'] == 'ignore'}
        blocked = {normalize(tag) for tag in account.preferences.get('blocked_tags', [])}
        words = {key:word for key, word in words.items() if key not in ignored | blocked | {'pixiv', 'r-18', 'r-18g'}}
        raw_names.update(words)
        for word in words:
            channels[channel]['raw'][word] += weight / math.sqrt(max(1, len(words)))
        for field, ids in [('group', match['group_ids']), ('character', match['character_ids']), ('feature', match['feature_tag_ids'])]:
            for id_ in ids:
                if field == 'feature' and normalize(index.features[id_].name) == 'pixiv':
                    continue
                channels[channel][field][id_] += weight / max(1, len(ids))
        for evidence in match['evidence']:
            if evidence['type'] == 'feature':
                observed[evidence['id']][evidence['pixiv_tag']] += weight

    for pid, pages in units.items():
        tags = {normalize(tag['name']):tag for image in pages if image.pixiv_metadata
                and image.pixiv_metadata.status == 'verified' for tag in image.pixiv_metadata.tags or [] if tag.get('name')}
        # Old images without Pixiv snapshots still train local labels, once per work.
        match = {'group_ids':sorted({g.id for image in pages for g in image.groups}),
                 'character_ids':sorted({r.id for image in pages for r in image.characters}),
                 'feature_tag_ids':sorted({t.id for image in pages for t in image.feature_tags}),
                 'evidence':index.match(list(tags.values()), group_context={g.id for image in pages for g in image.groups})['evidence']}
        record('library', list(tags.values()), match)
        if str(pid).isdigit():
            seeds[pid] += 0.2
    likes, carts, snapshots = root_snapshots(db, index, account, images)
    for pid, art in snapshots.items():
        match = recommendation_match(index, art.get('tags', []), index.groups)
        if pid in likes:
            days = max(0, (datetime.utcnow() - likes[pid].updated_at).days)
            weight = 0.5 + 0.5 * 2 ** (-days / 30)
            record('likes', art.get('tags', []), match, weight)
            seeds[pid] += 3 * weight
        if pid in carts:
            record('cart', art.get('tags', []), match)
            seeds[pid] += 1.5
    vectors = defaultdict(Counter)
    # A large existing library cannot drown out a small explicit likes channel.
    for channel, weight in [('likes', 0.55), ('cart', 0.25), ('library', 0.20)]:
        for field, values in channels[channel].items():
            for key, value in distribution({key:math.log1p(count) for key, count in values.items()}).items():
                vectors[field][key] += weight * value
    vectors = {field:distribution(values) for field, values in vectors.items()}
    counts = Counter({g:0 for g in index.groups})
    for image in images:
        counts.update(g.id for g in image.groups)
    selected = _selected(index, counts, account.preferences)
    affinity = {g:vectors.get('group', {}).get(g, 0) for g in selected}
    total = sum(affinity.values())
    weights = {g:value / total for g, value in affinity.items()} if total else {g:1 / len(selected) for g in selected}
    return {'algorithm':'personal-affinity-v1', 'vectors':vectors, 'raw_tag_names':raw_names,
            'quotas':weights, 'inventory':dict(counts),
            'tags':{g:vectors.get('feature', {}) for g in selected},
            'characters':{g:{r.id:vectors.get('character', {}).get(r.id, 0) for r in index.characters.values() if r.group_id == g} for g in selected},
            'liked_raw_global':vectors.get('raw', {}), 'liked_raw_tags':{},
            'feature_query_tags':{t:[word for word, _ in values.most_common(3)] for t, values in observed.items()},
            'related_seeds':{}, 'personal_seeds':[pid for pid, _ in seeds.most_common(4)]}


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
    return {'algorithm':'stock-inverse-inventory-v3', 'inventory':dict(counts),
            'character_inventory':dict(roles), 'character_counts':{g:character_counts[g] for g in selected},
            'sparse_character_groups':[g for g in selected if character_counts[g] <= SPARSE_CHARACTER_LIMIT],
            'new_character_quotas':new_character_weights(group_quotas, character_counts),
            'quotas':group_quotas,
            'character_quotas':role_quotas, 'characters':role_quotas,
            'tags':{g:vector for g in selected}, 'feature_vector':vector,
            'liked_raw_global':{}, 'liked_raw_tags':{}, 'raw_tag_names':{},
            'feature_query_tags':{t:[word for word, _ in values.most_common(3)] for t, values in observed.items()},
            'related_seeds':{g:[pid for pid, _ in values.most_common(4)] for g, values in seeds.items()}}


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
            words.extend(profile['feature_query_tags'].get(tag, [])[:1] or bound[:1] or [index.features[tag].name])
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
    """Balance bookmark traction against publication age without rewarding age alone."""
    try:
        published = datetime.fromisoformat(str(item['published_at']).replace('Z', '+00:00'))
        if published.tzinfo:
            published = published.astimezone(timezone.utc).replace(tzinfo=None)
        age_days = max(0, (now - published).total_seconds() / 86400)
    except (KeyError, TypeError, ValueError):
        age_days = 90
    recency = 2 ** (-age_days / 45)
    try:
        bookmarks = max(0, int(item['bookmarks'])) if item.get('bookmarks') is not None else None
    except (TypeError, ValueError):
        bookmarks = None
    if bookmarks is None:
        return 0.1 * recency
    popularity = min(1, math.log1p(bookmarks) / math.log1p(1000))
    return popularity * (0.25 + 0.75 * recency)


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
        if batch and not origins:
            continue
        match = recommendation_match(index, art['tags'], index.groups)
        item = {**art, 'match':match, 'origins':origins, 'imported_pages':[], 'reasons':[]}
        prepared.append((item, min(native, default=100)))
    return prepared


def rank(db, index, account, mode, actor_id, seen_pids=()):
    profile = build_profile(db, index, account, mode)
    profile.update({'policy_version':policy_version(mode), 'actor_id':actor_id, 'mode':mode})
    candidates = _candidates(db, index, account, mode, actor_id, seen_pids)
    if mode == 'discovery':
        return [item for item, _ in sorted(candidates, key=lambda row:(row[1], row[0]['pid']))][:180], profile
    now = datetime.utcnow()
    for item, native_rank in candidates:
        match = item['match']
        native = 1 / math.log2(native_rank + 2)
        quality = recent_popularity(item, now)
        if mode == 'personal':
            v = profile['vectors']
            affinity = (0.55 * cosine(v.get('raw', {}), [normalize(t['name']) for t in item['tags']])
                        + 0.20 * cosine(v.get('feature', {}), match['feature_tag_ids'])
                        + 0.15 * cosine(v.get('character', {}), match['character_ids'])
                        + 0.10 * cosine(v.get('group', {}), match['group_ids']))
            item['_score'] = 0.70 * affinity + 0.20 * quality + 0.10 * native
        else:
            item['_quality'] = quality
            item['_score'] = 0.30 * cosine(profile['feature_vector'], match['feature_tag_ids']) + 0.55 * quality + 0.15 * native
    if mode == 'personal':
        pool, chosen, authors = sorted([item for item, _ in candidates], key=lambda item:(-item['_score'], item['pid'])), [], Counter()
        while pool and len(chosen) < 180:
            if len(chosen) % 20 == 0:
                authors.clear()
            best = max(range(min(30, len(pool))), key=lambda n:pool[n]['_score'] - 0.03 * authors[pool[n]['author_id']])
            item = pool.pop(best)
            authors[item['author_id']] += 1
            item.pop('_score')
            chosen.append(item)
        return chosen, profile
    return stock_schedule([item for item, _ in candidates], profile, index), profile


def stock_identity(item, profile, index):
    match = item['match']
    groups = [g for g in match['group_ids'] if g in profile['quotas']]
    if not match['group_ids'] and not match['conflicts']:
        return 'new_group', None, None
    if groups:
        roles = [r for r in match['character_ids'] if index.characters[r].group_id in groups]
        if roles:
            role = min(roles, key=lambda r:(profile['character_inventory'].get(r, 0), r))
            return 'known', index.characters[role].group_id, role
        if not match['character_ids'] and not match['conflicts']:
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
    target = max(3, math.ceil(27 * profile.get('new_character_quotas', profile['quotas']).get(group, 0)))
    return max(0, target - supply[group])


def stock_query_gap(query, profile, groups, roles):
    group, role = query['group'], query.get('character')
    target = 144 * profile['quotas'].get(group, 0)
    return max(0, target - groups[group]), max(0, target * profile.get('character_quotas', {}).get(group, {}).get(role, 0) - roles[role])


def stock_recall_queries(queries, candidates, profile, index, limit=3):
    """Recall thin-series exploration once, then fill missing known-role supply."""
    groups, roles = stock_supply(candidates, profile, index)
    new_roles = stock_new_character_supply(candidates, profile, index, min_quality=STOCK_POPULARITY_FLOOR)
    picked, remaining = [], list(queries)
    used_groups = set()
    sparse = set(profile.get('sparse_character_groups', ()))
    anchors = [query for query in remaining if query['group'] in sparse
               and query.get('source') in ('group_mapping', 'group_name')
               and stock_new_character_gap(query['group'], new_roles, profile) > 0]
    if anchors and limit:
        query = max(anchors, key=lambda entry:(
            stock_new_character_gap(entry['group'], new_roles, profile),
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
    known, new_roles, new_groups = defaultdict(lambda:defaultdict(list)), defaultdict(list), []
    for item in items:
        kind, group, role = stock_identity(item, profile, index)
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
    known_n = sum(len(pool) for roles in known.values() for pool in roles.values())
    role_n, group_n = sum(map(len, new_roles.values())), len(new_groups)
    target = min(180, known_n + role_n + group_n)
    desired_known = target - min(role_n, int(target * .15)) - min(group_n, int(target * .05))
    group_caps = {g:max(2, math.ceil(desired_known * weight * 1.25)) for g, weight in profile['quotas'].items()}
    role_caps = {g:{r:max(2, math.ceil(group_caps[g] * weight * 1.25))
                   for r, weight in weights.items()} for g, weights in profile['character_quotas'].items()}
    # Bounded rounding/25% overflow is allowed. A missing cold group must not
    # donate its entire budget to a large group with abundant native candidates.
    for g, roles in known.items():
        for r in roles:
            roles[r] = roles[r][:role_caps[g][r]]
    known_n = sum(min(group_caps[g], sum(map(len, roles.values()))) for g, roles in known.items())
    # Never silently turn a short supply of known roles into mostly exploration.
    while target > known_n + min(role_n, int(target * .15)) + min(group_n, int(target * .05)):
        target = known_n + min(role_n, int(target * .15)) + min(group_n, int(target * .05))
    limits = {'new_character':min(role_n, int(target * .15)), 'new_group':min(group_n, int(target * .05))}
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
                       key=lambda kind:({'known':.8, 'new_character':.15, 'new_group':.05}[kind] * (len(chosen) + 1) - assigned[kind], kind))
        if category == 'known':
            groups = [g for g, roles in known.items() if any(roles.values()) and group_assigned[g] < group_caps[g]]
            g = _weighted_pick(groups, profile['quotas'], group_credit)
            roles = [r for r, pool in known[g].items() if pool]
            r = _weighted_pick(roles, profile['character_quotas'][g], role_credit[g])
            item = take(known[g][r])
            group_assigned[g] += 1
            role_assigned[r] += 1
        elif category == 'new_character':
            active = [g for g, pool in new_roles.items() if pool]
            hot_sparse = {g for g in active if g in sparse and
                          max(item.get('_quality', 0) for item in new_roles[g][:30]) >= STOCK_POPULARITY_FLOOR}
            boosted = profile.get('new_character_quotas', profile['quotas'])
            weights = ({g:(profile['quotas'][g] if g in sparse and g not in hot_sparse else boosted[g])
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
    profile.update({'known_target':desired_known, 'group_caps':group_caps,
                    'group_shortfalls':{g:max(0, math.ceil(desired_known * weight) - group_assigned[g])
                                        for g, weight in profile['quotas'].items()},
                    'assigned_pools':dict(assigned), 'assigned_groups':dict(group_assigned),
                    'assigned_new_character_groups':dict(new_assigned),
                    'assigned_characters':dict(role_assigned), 'supply_gaps':[kind for kind in ('new_character', 'new_group') if assigned[kind] < int(len(chosen) * {'new_character':.15, 'new_group':.05}[kind])]})
    return chosen


def stock_page(rows, limit):
    """Reapply independent exploration caps after live library/cart exclusions.

    Positions remain the immutable batch offsets. Skipped exploration can be
    reconsidered by the next ranked batch; seen PIDs only include returned cards.
    """
    supply = Counter(item.get('stock_pool', 'known') for _, item in rows)
    target = min(limit, len(rows))
    while target > supply['known'] + min(supply['new_character'], int(target * .15)) + min(supply['new_group'], int(target * .05)):
        target = supply['known'] + min(supply['new_character'], int(target * .15)) + min(supply['new_group'], int(target * .05))
    caps = {'new_character':min(supply['new_character'], int(target * .15)), 'new_group':min(supply['new_group'], int(target * .05))}
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
