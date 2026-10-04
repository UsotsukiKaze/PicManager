"""Deterministic tag matching, confidence-weighted profiles and inventory scheduling."""

import math
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy.orm import selectinload

from ... import models
from ...config import settings
from ...pixiv_metadata import library_pixiv_pages


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", str(text)).casefold().split())


class TagIndex:
    def __init__(self, db):
        self.groups = {x.id: x for x in db.query(models.Group).options(selectinload(models.Group.aliases)).all()}
        self.characters = {
            x.id: x
            for x in db.query(models.Character)
            .options(selectinload(models.Character.nicknames), selectinload(models.Character.feature_tags))
            .all()
        }
        self.features = {
            x.id: x for x in db.query(models.FeatureTag).options(selectinload(models.FeatureTag.aliases)).all()
        }
        self.names = defaultdict(list)
        for kind, objects, alias_attr in (
            ("group", self.groups, "aliases"),
            ("character", self.characters, "nicknames"),
            ("feature", self.features, "aliases"),
        ):
            for obj in objects.values():
                aliases = [getattr(x, "alias", getattr(x, "nickname", "")) for x in getattr(obj, alias_attr)]
                for name in {normalize(x) for x in [obj.name, *aliases] if x}:
                    self.names[name].append((kind, obj.id))
        self.mappings = {
            (x.normalized_tag, x.group_context): (x.target_type, x.target_id)
            for x in db.query(models.PixivTagMapping).all()
        }

    def match(self, tags):
        matched = {"group": set(), "character": set(), "feature": set()}
        evidence, unmatched, conflicts = [], [], []
        tags = list({normalize(x.get("name", "")): x for x in tags if normalize(x.get("name", ""))}.values())
        for phase in (0, 1):
            for tag in tags:
                name = tag["name"]
                if any(x["pixiv_tag"] == name for x in evidence):
                    continue
                mapping = self.mappings.get((normalize(name), 0))
                for group_id in sorted(matched["group"]):
                    mapping = self.mappings.get((normalize(name), group_id), mapping)
                choices = [mapping] if mapping else self.names.get(normalize(name), [])
                basis = "confirmed_mapping" if mapping else "name_or_alias"
                if not choices and tag.get("translated_name"):
                    choices = self.names.get(normalize(tag["translated_name"]), [])
                    basis = "translated_name"
                if phase == 0:
                    choices = [x for x in choices if x[0] in ("group", "ignore")]
                elif len(choices) > 1 and matched["group"]:
                    choices = [
                        x for x in choices if x[0] != "character" or self.characters[x[1]].group_id in matched["group"]
                    ]
                if len(choices) != 1:
                    if phase:
                        (conflicts if choices else unmatched).append(name)
                    continue
                kind, target_id = choices[0]
                objects = {"group": self.groups, "character": self.characters, "feature": self.features}
                if kind != "ignore" and target_id not in objects.get(kind, {}):
                    if phase:
                        conflicts.append(name)
                    continue
                if kind != "ignore":
                    matched[kind].add(target_id)
                evidence.append(
                    {
                        "pixiv_tag": name,
                        "type": kind,
                        "id": target_id,
                        "name": objects[kind][target_id].name if kind != "ignore" else name,
                        "basis": basis,
                    }
                )
                if kind == "character":
                    matched["group"].add(self.characters[target_id].group_id)
        return {
            "group_ids": sorted(matched["group"]),
            "character_ids": sorted(matched["character"]),
            "feature_tag_ids": sorted(matched["feature"]),
            "evidence": evidence,
            "unmatched": unmatched,
            "conflicts": conflicts,
        }


def inventory_quotas(counts, preferences):
    enabled = preferences.get("groups", {})
    alpha = float(preferences.get("alpha", 0.5))
    selected = {
        g: n
        for g, n in counts.items()
        if enabled.get(str(g), {}).get("enabled", n > 0)
    }
    raw = {g: (n + 5) ** -alpha for g, n in selected.items()}
    floor = min(raw.values(), default=1)
    weights = {g: min(x, floor * 4) for g, x in raw.items()}
    total = sum(weights.values())
    return {g: x / total for g, x in weights.items()} if total else {}


def build_profile(db, index, preferences):
    images = (
        db.query(models.Image)
        .filter(models.Image.file_status == "available")
        .options(
            selectinload(models.Image.groups),
            selectinload(models.Image.characters).selectinload(models.Character.feature_tags),
            selectinload(models.Image.feature_tags),
            selectinload(models.Image.pixiv_sources),
            selectinload(models.Image.pixiv_metadata),
            selectinload(models.Image.tag_evidence),
        )
        .all()
    )
    counts = Counter({g: 0 for g in index.groups})
    units = defaultdict(list)
    for image in images:
        for group in image.groups:
            counts[group.id] += 1 / max(1, len(image.groups))
        pid = (
            image.pixiv_sources[0].work_id
            if image.pixiv_sources
            else (image.pixiv_metadata.work_id if image.pixiv_metadata else None)
        )
        units[pid or f"local:{image.image_id}"].append(image)
    account = db.get(models.PixivAccount, 1)
    likes = {
        x.pid: x
        for x in db.query(models.PixivFeedback)
        .join(models.User)
        .filter(
            models.User.role == "root",
            models.User.qq_number == settings.ROOT_QQ,
            models.PixivFeedback.value == "like",
            models.PixivFeedback.account_revision == (account.revision if account else ""),
        )
        .all()
    }

    def like_weight(pid):
        like = likes.get(pid)
        days = max(0, (datetime.utcnow() - like.updated_at).days) if like else 0
        return 1 + 2 ** (-days / 30) if like else 1

    totals, tags = Counter(), defaultdict(Counter)
    for pid, pages in units.items():
        weight = like_weight(pid)
        groups = {g.id for image in pages for g in image.groups}
        for g in groups:
            totals[g] += weight / len(groups)
        for image in pages:
            inherited = {t.id for c in image.characters for t in c.feature_tags}
            evidence = {t.feature_tag_id: t.confidence for t in image.tag_evidence}
            for group in image.groups:
                for tag in image.feature_tags:
                    if normalize(tag.name) == "pixiv":
                        continue
                    confidence = evidence.get(tag.id, 0.25 if tag.id in inherited else 0.6)
                    tags[group.id][tag.id] += weight * confidence / len(pages) / len(groups)
    if likes:
        liked = (
            db.query(models.PixivArtwork)
            .filter(models.PixivArtwork.account_revision == account.revision, models.PixivArtwork.pid.in_(likes))
            .all()
        )
        for art in liked:
            if art.pid in units:
                continue
            match = index.match(art.metadata_json["tags"])
            groups = match["group_ids"]
            for g in groups:
                weight = like_weight(art.pid) / len(groups)
                totals[g] += weight
                for t in match["feature_tag_ids"]:
                    tags[g][t] += weight * 0.6
    local = {g: {t: c / max(totals[g], 1) for t, c in tags[g].items()} for g in counts}
    global_tags = Counter()
    active = [g for g in local if totals[g] > 0]
    for g in active:
        for t, value in local[g].items():
            global_tags[t] += value / len(active)
    profile = {}
    for g in counts:
        rho = totals[g] / (totals[g] + 20)
        profile[g] = {
            t: rho * local[g].get(t, 0) + (1 - rho) * global_tags[t] for t in global_tags.keys() | local[g].keys()
        }
    return {
        "inventory": dict(counts),
        "samples": dict(totals),
        "tags": profile,
        "quotas": inventory_quotas(counts, preferences),
        "algorithm": "confidence-macro-shrink-v1",
    }


def allowed(art, preferences):
    if str(art.get("author_id")) in preferences.get("blocked_authors", []):
        return False
    rating = int(art.get("x_restrict", 0))
    if rating == 2 and not preferences.get("include_r18g", False):
        return False
    if rating and not preferences.get("include_r18", False):
        return False
    ai = preferences.get("ai", "exclude")
    if ai == "exclude" and art.get("ai_type") == 2:
        return False
    if ai == "only" and art.get("ai_type") != 2:
        return False
    blocked = {normalize(x) for x in preferences.get("blocked_tags", [])}
    return not any(normalize(x["name"]) in blocked for x in art.get("tags", []))


def rank_candidates(db, account, mode="combined"):
    index = TagIndex(db)
    profile = build_profile(db, index, account.preferences)
    source_pages = library_pixiv_pages(db)
    feedback = {
        x.pid: x.value
        for x in db.query(models.PixivFeedback)
        .join(models.User, models.User.id == models.PixivFeedback.actor_id)
        .filter(
            models.PixivFeedback.account_revision == account.revision,
            models.User.role == "root",
            models.User.qq_number == settings.ROOT_QQ,
        )
        .all()
    }
    rows = (
        db.query(models.PixivArtwork)
        .filter(models.PixivArtwork.account_revision == account.revision)
        .order_by(models.PixivArtwork.fetched_at.desc(), models.PixivArtwork.id.desc())
        .limit(1000)
        .all()
    )
    buckets, exploration = defaultdict(list), []
    background, bg_n = defaultdict(Counter), Counter()
    prepared = []
    source_batch = account.sync_state.get("recommended", {}).get("batch")
    candidate_batch = account.sync_state.get("candidate_batch", source_batch)
    feed_count = 0
    for row in rows:
        art = row.metadata_json
        if not allowed(art, account.preferences) or feedback.get(row.pid) == "dislike":
            continue
        if mode != "native" and candidate_batch:
            current = any(o.get("batch") == candidate_batch for o in row.origins)
            if not current:
                if feed_count >= 10 or not any(o["source"].startswith("feed_") for o in row.origins):
                    continue
                feed_count += 1
        imported = sorted(page for page in source_pages.get(row.pid, []) if page < art["page_count"])
        if len(imported) == art["page_count"]:
            continue
        match = index.match(art["tags"])
        groups = [g for g in match["group_ids"] if g in profile["quotas"]]
        for g in groups:
            bg_n[g] += 1
            background[g].update(set(match["feature_tag_ids"]))
        prepared.append((row, art, match, groups, imported))
    now = datetime.utcnow()
    for row, art, match, groups, imported in prepared:
        local_scores = []
        for g in groups or [None]:
            pref = profile["tags"].get(g, {})
            scores = []
            for tag in match["feature_tag_ids"]:
                value = pref.get(tag, 0)
                if bg_n[g] >= 50:
                    p0 = (background[g][tag] + 1) / (bg_n[g] + 2)
                    value = max(0, min(1, 0.5 + math.log((value + 0.01) / (p0 + 0.01)) / 4))
                scores.append(value)
            interest = sum(scores) / len(scores) if scores else 0.5
            if feedback.get(row.pid) in ("like", "imported"):
                interest = max(interest, 0.9)
            rank = min(
                [
                    o.get("rank", 100)
                    for o in row.origins
                    if o["source"] == "recommended" and o.get("batch") == source_batch
                ],
                default=None,
            )
            native = 1 / math.log2(rank + 1) if rank else 0.5
            fresh = 2 ** (-max(0, (now - row.published_at).days) / 90)
            score = 0.4 * interest + 0.25 * bool(g) + 0.15 * native + 0.1 * fresh + 0.1 * 0.5
            local_scores.append((g, score))
        item = {
            **art,
            "imported_pages": imported,
            "match": match,
            "origins": row.origins,
            "reasons": [
                "来自 Pixiv 推荐" if any(o["source"] == "recommended" for o in row.origins) else "本地分组/标签候选"
            ],
            "scores": {str(g): round(s, 4) for g, s in local_scores},
            "group_ids": groups,
        }
        if mode == "native":
            native = [o for o in row.origins if o["source"] == "recommended" and o.get("batch") == source_batch]
            if native:
                item["score"] = -min(o.get("rank", 100) for o in native)
                exploration.append(item)
        elif groups:
            for g, score in local_scores:
                buckets[g].append((score, item))
        else:
            item["score"] = local_scores[0][1]
            exploration.append(item)
    if mode == "native":
        return sorted(exploration, key=lambda x: (-x["score"], x["pid"])), profile
    for g in buckets:
        buckets[g].sort(key=lambda x: (-x[0], x[1]["pid"]))
    chosen, seen, assigned, authors = [], set(), Counter(), Counter()
    while any(buckets.values()) and len(chosen) < 180:
        groups = sorted(
            (g for g in buckets if buckets[g]),
            key=lambda g: (profile["quotas"][g] * (len(chosen) + 1) - assigned[g]),
            reverse=True,
        )
        g = groups[0]
        pool = buckets[g]
        # Soft diversity penalty restarts per 20-item page; it never changes group quota.
        if len(chosen) % 20 == 0:
            authors.clear()
        best = max(range(min(len(pool), 30)), key=lambda n: pool[n][0] - 0.12 * authors[pool[n][1]["author_id"]])
        score, item = pool.pop(best)
        if item["pid"] in seen:
            continue
        seen.add(item["pid"])
        item = {**item, "primary_group": g, "inventory": round(profile["inventory"][g], 2), "score": round(score, 4)}
        item["reasons"] = [
            *item["reasons"],
            f"{index.groups[g].name}有效库存 {item['inventory']} 张",
            "按分组补图配额分配",
        ]
        chosen.append(item)
        assigned[g] += 1
        authors[item["author_id"]] += 1
    unknown_budget = min(len(exploration), len(chosen) // 9)
    for position, item in enumerate(sorted(exploration, key=lambda x: (-x["score"], x["pid"]))[:unknown_budget]):
        item["reasons"] = [*item["reasons"], "探索待归类，不计入分组补图"]
        chosen.insert(min(len(chosen), 19 + 20 * position), item)
    profile["assigned"] = dict(assigned)
    profile["supply_gaps"] = [g for g in profile["quotas"] if assigned[g] == 0]
    return chosen, profile
