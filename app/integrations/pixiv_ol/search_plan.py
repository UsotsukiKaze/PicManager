"""Bounded, group-anchored search plans built from cached preferences."""
from collections import defaultdict
import re

from ... import models
from .recommendations import normalize


def build_search_plan(db, index, profile, preferences, *, rotation=0, stock=False):
    mapped = defaultdict(list)
    blocked = {normalize(tag) for tag in preferences.get('blocked_tags', [])}
    for row in db.query(models.PixivTagMapping).order_by(models.PixivTagMapping.id).all():
        if row.target_type == 'ignore':
            continue
        word = (row.original_tag or row.normalized_tag).strip()
        if not word or normalize(word) in blocked:
            continue
        mapped[(row.target_type, row.target_id)].append((row.group_context, word))

    def words(kind, id_, group):
        values = [word for context, word in mapped[(kind, id_)] if context in (0, group)
                  and index.mappings.get((normalize(word), group),
                                         index.mappings.get((normalize(word), 0))) == (kind, id_)]
        unique = list(dict.fromkeys(values))
        if stock:
            # Popularity qualifiers are narrower than the actual series/role tag.
            unique.sort(key=lambda word: (bool(re.search(r'\d+users入り', word)),
                                         not bool(re.search(r'[ぁ-ヿa-zA-Z]', word))))
        if unique:
            preferred = [word for word in unique if not re.search(r'\d+users入り', word)] if stock else unique
            preferred = preferred or unique
            offset = rotation % len(preferred)
            return preferred[offset:] + preferred[:offset]
        return []

    ordered = sorted(profile['quotas'], key=lambda g: (-profile['quotas'][g], g))
    if len(ordered) > 10 and not stock:
        # Keep the largest inventory gaps active; rotate the remaining groups
        # so enabled large groups are not excluded from search forever.
        tail = ordered[5:]
        start = (rotation * 5) % len(tail)
        ordered = ordered[:5] + (tail[start:] + tail[:start])[:5]
    queues = {}
    for group in ordered:
        anchors = words('group', group, group)
        anchor = anchors[0] if anchors else index.groups[group].name
        queue, seen = [], set()

        def add(word, source, exact=True, terms=None, character=None):
            key = normalize(word)
            terms = terms or [word]
            if any(normalize(term) in blocked or
                   index.mappings.get((normalize(term), group),
                                      index.mappings.get((normalize(term), 0), ('', None)))[0] == 'ignore'
                   for term in terms):
                return
            if key and key not in seen and len(word) <= 512:
                seen.add(key)
                queue.append({'group':group, 'word':word,
                              'search_target':'exact_match_for_tags' if exact else 'partial_match_for_tags',
                              'source':source, 'terms':terms})
                if character is not None:
                    queue[-1]['character'] = character
                return True
            return False

        add(anchor, 'group_mapping' if anchors else 'group_name', bool(anchors))
        roles = sorted((role for role in index.characters.values() if role.group_id == group),
                       key=lambda role: (-profile['characters'].get(group, {}).get(role.id, 0), role.id))
        role_words = [(role.id, bound[0]) for role in roles if (bound := words('character', role.id, group))]
        if stock and len(role_words) > 4:
            tail = role_words[1:]
            start = (rotation * 3) % len(tail)
            role_words = role_words[:1] + (tail[start:] + tail[:start])[:3]
        elif not stock and len(role_words) > 2:
            tail = role_words[1:]
            role_words = [role_words[0], tail[rotation % len(tail)]]
        for role_id, word in role_words:
            add(word, 'character_mapping', character=role_id)
        features = sorted(profile['tags'].get(group, {}).items(), key=lambda entry: (-entry[1], entry[0]))
        added_features = 0
        for feature, weight in features:
            if weight <= 0 or feature not in index.features or normalize(index.features[feature].name) == 'pixiv':
                continue
            bound = words('feature', feature, group)
            observed = profile['feature_query_tags'].get(feature, [])
            token = next(iter(bound or observed), index.features[feature].name)
            if normalize(token) == normalize(anchor):
                continue
            added_features += bool(add(f'{anchor} {token}', 'library_feature', bool(anchors and (bound or observed)), [anchor, token]))
            if added_features == 2:
                break
        raw = dict(profile['liked_raw_global'])
        raw.update(profile['liked_raw_tags'].get(group, {}))
        for key, _ in sorted(raw.items(), key=lambda entry: (-entry[1], entry[0]))[:2]:
            token = profile['raw_tag_names'].get(key, key)
            if normalize(token) != normalize(anchor):
                add(f'{anchor} {token}', 'liked_tag', bool(anchors), [anchor, token])
        for alternate in anchors[1:2]:
            add(alternate, 'group_mapping')
        # Rotate extra signal families so a large catalog's request cap does not
        # permanently starve feature/like queries behind character queries.
        anchor_queries = queue[:1] if queue and queue[0]['word'] == anchor else []
        extras = queue[len(anchor_queries):]
        families = ['character_mapping', 'library_feature', 'liked_tag', 'group_mapping']
        offset = rotation % len(families)
        families = families[offset:] + families[:offset]
        buckets = {family:[entry for entry in extras if entry['source'] == family] for family in families}
        interleaved = [entries[round_] for round_ in range(2) for entries in buckets.values() if round_ < len(entries)]
        queues[group] = queue if stock else anchor_queries + interleaved

    if stock:
        # Keep an anchor and rare-role queries for every selected group. The
        # consumer chooses by live shortage, rather than this static FIFO order.
        return [queues[group][round_] for round_ in range(max((len(q) for q in queues.values()), default=0))
                for group in ordered if round_ < len(queues[group])][:160]

    # Every enabled group gets an anchor before additional queries are allotted
    # according to the same inventory quotas as the final recommendation list.
    plan, seen, assigned = [], set(), defaultdict(int)
    def take(group):
        while queues[group]:
            entry = queues[group].pop(0)
            key = (normalize(entry['word']), entry['search_target'])
            if key not in seen:
                seen.add(key); plan.append(entry); assigned[group] += 1
                return
    for group in ordered:
        take(group)
    while len(plan) < 20 and any(queues.values()):
        group = max((g for g in ordered if queues[g]),
                    key=lambda g: (profile['quotas'][g] * (len(plan) + 1) - assigned[g], -g))
        take(group)
    return plan


def restored_query(value):
    if isinstance(value, dict):
        return value
    # Continue an already saved stream from versions using [group, keyword].
    group, word = value
    return {'group':group, 'word':word, 'search_target':'partial_match_for_tags', 'source':'legacy'}
