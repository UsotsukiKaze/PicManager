"""Small sparse interest vectors, grouped feature backoff and conservative quality estimates."""

import math
import re
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime

from ... import models
from .recommendations import normalize, recommendation_match


def normalized(values):
    length = math.sqrt(sum(v * v for v in values.values()))
    return {k: v / length for k, v in values.items()} if length else {}


def backoff(observed, prior, count, strength):
    a = count / (count + strength)
    return normalized({k: a * observed.get(k, 0) + (1 - a) * prior.get(k, 0) for k in set(observed) | set(prior)})


def interest_profile(db, index, account, images, work_id, snapshots):
    likes, carts, arts = snapshots
    states = {r.pid: r for r in db.query(models.PixivBookmarkState).filter_by(account_revision=account.revision)}
    units = defaultdict(list)
    for image in images:
        units[work_id(image)].append(image)
    corpus = list(
        db.query(models.PixivArtwork)
        .filter_by(account_revision=account.revision)
        .order_by(models.PixivArtwork.fetched_at.desc())
        .limit(5000)
    )
    frequency = Counter(
        normalize(t["name"])
        for art in corpus
        for t in {normalize(t["name"]): t for t in art.metadata_json.get("tags", []) if t.get("name")}.values()
    )
    entity_frequency = defaultdict(Counter)
    for art in corpus:
        matched = recommendation_match(index, art.metadata_json.get("tags", []), index.groups)
        for field, key in (("group", "group_ids"), ("character", "character_ids"), ("feature", "feature_tag_ids")):
            entity_frequency[field].update(set(matched[key]))
    channels, raw_names, observed = defaultdict(Counter), {}, defaultdict(Counter)
    group_features, role_features, group_n, role_n = defaultdict(Counter), defaultdict(Counter), Counter(), Counter()
    seeds = defaultdict(list)
    blocked = {normalize(t) for t in account.preferences.get("blocked_tags", ())}
    for pid in sorted(set(units) | set(arts)):
        pages, art = units.get(pid, []), arts.get(pid, {})
        local_tags = {
            normalize(t["name"]): t
            for image in pages
            if image.pixiv_metadata and image.pixiv_metadata.status == "verified"
            for t in image.pixiv_metadata.tags or []
            if t.get("name")
        }
        tags = {**local_tags, **{normalize(t["name"]): t for t in art.get("tags", []) if t.get("name")}}
        match = recommendation_match(index, list(tags.values()), index.groups)
        # Page-local labels are authoritative for training library identities.
        ids = {
            "group": set(g.id for p in pages for g in p.groups),
            "character": set(r.id for p in pages for r in p.characters),
            "feature": set(t.id for p in pages for t in p.feature_tags),
        }
        if not pages:
            for field, key in (("group", "group_ids"), ("character", "character_ids"), ("feature", "feature_tag_ids")):
                ids[field].update(match[key])
        mirror = states.get(pid)
        like = likes.get(pid)
        weight = 1 if pages else 0
        if pages and any(p.tag_evidence for p in pages):
            weight = 3
        if pid in carts:
            weight = max(weight, 2)
        if like:
            weight = max(weight, 2 if mirror and mirror.source == "auto_cart" else 4)
        if not weight:
            continue
        if mirror and mirror.action_at:
            days = max(0, (datetime.utcnow() - mirror.action_at).total_seconds() / 86400)
            weight *= 0.35 + 0.65 * 2 ** (-days / 90)
        resolved = {normalize(e["pixiv_tag"]) for e in match["evidence"]}
        for key, t in tags.items():
            if (
                key in resolved
                or key in blocked
                or key in ("pixiv", "r-18", "r-18g")
                or re.search(r"\d+users入り", key)
                or index.is_ignored(t["name"])
            ):
                continue
            raw_names[key] = t["name"]
            channels["raw"][key] += weight / max(1, len(tags))
        for field, values in ids.items():
            for id_ in values:
                if field == "feature":
                    continue
                confidence = (
                    1
                    if pages
                    else max(
                        (
                            0.9 if e.get("basis") == "confirmed_mapping" else 0.25
                            for e in match["evidence"]
                            if e["type"] == field and e["id"] == id_
                        ),
                        default=0.25,
                    )
                )
                channels[field][id_] += weight * confidence / max(1, len(values))
        feature_values = {}
        for id_ in ids["feature"]:
            if normalize(index.features[id_].name) == "pixiv":
                continue
            confidence = (
                max(
                    (
                        0.9 if e.get("basis") == "confirmed_mapping" else 0.25
                        for e in match["evidence"]
                        if e["type"] == "feature" and e["id"] == id_
                    ),
                    default=0.25,
                )
                if not pages
                else max(
                    (
                        next(
                            (e.confidence for e in p.tag_evidence if e.feature_tag_id == id_),
                            0.35 if any(id_ in {t.id for t in r.feature_tags} for r in p.characters) else 1,
                        )
                        for p in pages
                        if id_ in {t.id for t in p.feature_tags}
                    ),
                    default=0.9,
                )
            )
            feature_values[id_] = weight * confidence / max(1, len(ids["feature"]))
        channels["feature"].update(feature_values)
        for g in ids["group"]:
            group_n[g] += 1
            group_features[g].update({t: v / max(1, len(ids["group"])) for t, v in feature_values.items()})
            if str(pid).isdigit():
                seeds[g].append((weight, pid))
        for c in ids["character"]:
            role_n[c] += 1
            role_features[c].update({t: v / max(1, len(ids["character"])) for t, v in feature_values.items()})
        for e in match["evidence"]:
            if e["type"] == "feature":
                observed[e["id"]][e["pixiv_tag"]] += weight

    def idf(field, key):
        df = frequency[key] if field == "raw" else entity_frequency[field][key]
        return min(3, max(1, 1 + math.log((len(corpus) + 1) / (df + 1))))

    vectors = {
        field: normalized({k: math.log1p(v) * idf(field, k) for k, v in values.items()})
        for field, values in channels.items()
    }
    global_features = vectors.get("feature", {})
    gf = {
        g: backoff(
            normalized({t: math.log1p(v) * idf("feature", t) for t, v in group_features[g].items()}),
            global_features,
            group_n[g],
            20,
        )
        for g in index.groups
    }
    cf = {
        c: backoff(
            normalized({t: math.log1p(v) * idf("feature", t) for t, v in role_features[c].items()}),
            gf.get(role.group_id, global_features),
            role_n[c],
            10,
        )
        for c, role in index.characters.items()
    }
    ranked = {g: [pid for _, pid in sorted(values, key=lambda x: (-x[0], x[1]))] for g, values in seeds.items()}
    # Round-robin across series, then rotate within series on each refresh.
    diversified = [values[i] for i in range(12) for values in ranked.values() if i < len(values)][:12]
    return {
        "vectors": vectors,
        "raw_tag_names": raw_names,
        "group_features": gf,
        "role_features": cf,
        "feature_query_tags": {t: [word for word, _ in count.most_common(3)] for t, count in observed.items()},
        "personal_seeds": diversified,
        "related_seeds": ranked,
    }


def affinity(profile, item, *, exploration=False):
    from .strategies import cosine

    match, vectors = item["match"], profile.get("vectors", {})
    roles, groups = match["character_ids"], match["group_ids"]
    features = profile.get("role_features", {}) if roles else profile.get("group_features", {})
    keys = roles or groups
    feature_score = (
        sum(
            cosine(features.get(k, features.get(str(k), vectors.get("feature", {}))), match["feature_tag_ids"])
            for k in keys
        )
        / max(1, len(keys))
        if keys
        else cosine(vectors.get("feature", {}), match["feature_tag_ids"])
    )
    resolved = {normalize(e["pixiv_tag"]) for e in match.get("evidence", ())}
    raw = cosine(
        vectors.get("raw", {}), [normalize(t["name"]) for t in item["tags"] if normalize(t["name"]) not in resolved]
    )
    group = cosine(vectors.get("group", {}), groups)
    if exploration:
        parts = [
            (vectors.get("group"), 0.30, group),
            (vectors.get("feature"), 0.55, feature_score),
            (vectors.get("raw"), 0.15, raw),
        ]
    else:
        parts = [
            (vectors.get("group"), 0.20, group),
            (vectors.get("character"), 0.30, cosine(vectors.get("character", {}), roles)),
            (vectors.get("feature"), 0.35, feature_score),
            (vectors.get("raw"), 0.15, raw),
        ]
    # Missing training channels are not evidence against a candidate.
    denominator = sum(weight for trained, weight, _ in parts if trained)
    return sum(weight * score for trained, weight, score in parts if trained) / denominator if denominator else 0


def age(item, now):
    from .service import iso_date

    try:
        return max(0, (now - iso_date(item["published_at"])).total_seconds() / 86400)
    except (KeyError, TypeError, PixivError):
        return 180


from .provider import PixivError


def age_bin(days):
    return 0 if days <= 2 else 1 if days <= 7 else 2 if days <= 30 else 3 if days <= 180 else 4


class QualityReference:
    """Build distributions once per ranking pass, then score in logarithmic time."""

    def __init__(self, items, now):
        pools = defaultdict(list)
        for item in items:
            if item.get("bookmarks") is None:
                continue
            base = (age_bin(age(item, now)), item.get("x_restrict"))
            pools[base].append(item)
            for g in item.get("match", {}).get("group_ids", ()):
                pools[(*base, g)].append(item)
        self.pools = {
            k: {
                "b": sorted(max(0, int(r["bookmarks"])) for r in rows),
                "rates": sorted(
                    r["bookmarks"] / r["views"]
                    for r in rows
                    if r.get("views", 0) and r["views"] >= max(200, r["bookmarks"])
                ),
                "velocities": sorted(r["bookmark_velocity"] for r in rows if r.get("bookmark_velocity") is not None),
            }
            for k, rows in pools.items()
        }

    def get(self, key):
        return self.pools.get(key, {"b": [], "rates": [], "velocities": []})


def quality(item, now, reference=()):
    bookmarks = item.get("bookmarks")
    # Missing metrics are an uncertain prior, never a claim of high popularity.
    if bookmarks is None:
        return 0.35
    b = max(0, int(bookmarks))
    days = age(item, now)
    if not isinstance(reference, QualityReference):
        reference = QualityReference(reference, now)
    base = (age_bin(days), item.get("x_restrict"))
    cohort = reference.get(base)
    group_pools = [reference.get((*base, g)) for g in item.get("match", {}).get("group_ids", ())]
    narrowed = max(group_pools, key=lambda p: len(p["b"]), default=cohort)

    def percentile(value, values):
        return (bisect_left(values, value) + bisect_right(values, value)) / (2 * len(values))

    global_p = percentile(b, cohort["b"]) if len(cohort["b"]) >= 50 else b / (b + 150)
    local_p = percentile(b, narrowed["b"]) if len(narrowed["b"]) >= 50 else global_p
    popularity = 0.6 * local_p + 0.4 * global_p
    rates = cohort["rates"]
    base = rates[len(rates) // 2] if rates else 0.05
    views = item.get("views")
    rate = (b + 200 * base) / (views + 200) if views is not None and views >= b else None
    rate_score = percentile(rate, rates) if rate is not None and len(rates) >= 50 else 0.5
    if views is not None:
        rate_score = 0.5 + (rate_score - 0.5) * views / (views + 200)
    velocity = item.get("bookmark_velocity")
    velocities = cohort["velocities"]
    growth = percentile(velocity, velocities) if velocity is not None and len(velocities) >= 50 else 0.5
    ranking = max(
        (
            1 / math.log2(o["rank"] + 2)
            for o in item.get("origins", ())
            if o.get("source", "").startswith("ranking_") and o.get("rank") is not None
        ),
        default=0,
    )
    return 0.45 * popularity + 0.20 * rate_score + 0.20 * growth + 0.15 * ranking
