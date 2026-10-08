"""Refresh cached cart suggestions without replacing deliberate page labels."""
from copy import deepcopy
from .recommendations import explicit_role_bundle

FIELDS = ('group_ids', 'character_ids', 'feature_tag_ids')


def initial_state(draft):
    return {'automatic': {key: list(draft.get(key, [])) for key in FIELDS}, 'suppressed': {}}


def remember_edit(previous, edited, match):
    # Saving confirms the chosen labels. Removed suggestions stay suppressed,
    # while a newly connected target can still be suggested on the next visit.
    state = previous.get('_tag_refresh', {})
    suppressed = {}
    for key in FIELDS:
        selected = set(edited.get(key, []))
        omitted = set(match.get(key, [])) | set(state.get('automatic', {}).get(key, []))
        suppressed[key] = sorted((set(state.get('suppressed', {}).get(key, [])) | omitted) - selected)
    edited['_tag_refresh'] = {'automatic': {}, 'suppressed': suppressed}
    return edited


def contextual_match(index, tags, draft):
    context = set(draft.get('group_ids', []))
    context.update(index.characters[id_].group_id for id_ in draft.get('character_ids', []) if id_ in index.characters)
    match = index.match(tags, group_context=context)
    # Context resolves scoped mappings; it is not itself an automatic group tag.
    groups = {row['id'] for row in match['evidence'] if row['type'] == 'group'}
    groups.update(index.characters[id_].group_id for id_ in match['character_ids'])
    match['group_ids'] = sorted(groups)
    return match


def refresh_draft(index, art, draft, *, confirmed_page=False):
    updated = deepcopy(draft)
    state = draft.get('_tag_refresh', {})
    previous_auto = state.get('automatic', {})
    suppressed = state.get('suppressed', {})
    match = contextual_match(index, art.get('tags', []), draft)
    automatic = {}
    manual_roles = set(draft.get('character_ids', [])) - set(previous_auto.get('character_ids', []))
    manual_groups = set(draft.get('group_ids', [])) - set(previous_auto.get('group_ids', []))
    for key in FIELDS:
        selected = set(draft.get(key, []))
        old_auto = set(previous_auto.get(key, []))
        manual = selected - old_auto
        candidates = set(match[key]) - set(suppressed.get(key, []))
        if key == 'character_ids':
            # Work-level tags cannot append another character to a confirmed
            # page or a manual selection, nor fill an unlabelled multi-page work.
            if confirmed_page or manual_roles:
                candidates &= selected
            elif art.get('page_count', 1) > 1:
                candidates &= old_auto
            elif len(candidates) > 1 and not explicit_role_bundle(match, candidates):
                candidates &= old_auto
        elif key == 'group_ids' and manual_groups:
            candidates &= selected
        automatic[key] = sorted(candidates - manual)
        updated[key] = sorted(manual | candidates)
    for id_ in updated['character_ids']:
        role = index.characters.get(id_)
        if role and role.group_id not in updated['group_ids']:
            updated['group_ids'].append(role.group_id)
    updated['group_ids'].sort()
    updated['_tag_refresh'] = {'automatic': automatic, 'suppressed': suppressed}
    return updated


def refresh_item(index, item):
    if item.status == 'importing':
        return False
    previous = item.draft
    if previous.get('import_mode') == 'split':
        updated = deepcopy(previous)
        confirmed = set(previous.get('confirmed_pages', []))
        updated['page_drafts'] = {
            str(page): refresh_draft(index, item.metadata_json, tags, confirmed_page=int(page) in confirmed)
            for page, tags in previous.get('page_drafts', {}).items()
        }
    else:
        updated = refresh_draft(index, item.metadata_json, previous)
    if updated == previous:
        return False
    item.draft = updated
    return True
