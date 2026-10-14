"""Quota buckets reserve scarce inventory independently of candidate score."""

import math
from collections import Counter, defaultdict

from .recommendations import normalize


def overlap(a, b):
    x, y = {normalize(t["name"]) for t in a["tags"]}, {normalize(t["name"]) for t in b["tags"]}
    return len(x & y) / max(1, len(x | y))


def take(pool, chosen, authors, *, role_cap=False):
    window = chosen[-20:]
    allowed = [n for n, i in enumerate(pool[:60]) if authors[i["author_id"]] < 2]
    choices = allowed or list(range(min(60, len(pool))))
    temporal = Counter(i.get("age_bucket", "recent") for i in chosen)
    weights = {"recent": 0.70, "middle": 0.20, "historical": 0.10}
    available = {pool[n].get("age_bucket", "recent") for n in choices}
    bucket = max(available, key=lambda b: weights[b] * (len(chosen) + 1) - temporal[b])
    choices = [n for n in choices if pool[n].get("age_bucket", "recent") == bucket]

    def score(n):
        item = pool[n]
        similarity = max((overlap(item, old) for old in window), default=0)
        role_penalty = 0
        if role_cap and item["match"]["character_ids"]:
            role_penalty = 0.08 * max(
                sum(r in old["match"]["character_ids"] for old in window) for r in item["match"]["character_ids"]
            )
        penalty = 0.12 * similarity + 0.06 * authors[item["author_id"]] + role_penalty
        return item["_score"] - min(penalty, 0.25 * item["_score"])

    return pool.pop(max(choices, key=score))


def stock_schedule(items, profile, index):
    from .strategies import stock_identity

    weights, pools = {}, defaultdict(list)
    weights[("new_group", None, None)] = 0.05
    for group, q in profile["quotas"].items():
        e = profile["new_character_fractions"][group]
        weights[("new_character", group, None)] = 0.95 * q * e
        roles = profile["character_quotas"][group]
        if not roles:
            weights[("unfilled", group, None)] = 0.95 * q * (1 - e)
        for role, rq in roles.items():
            weights[("known", group, role)] = 0.95 * q * (1 - e) * rq
    if not profile["quotas"]:
        profile["supply_gaps"] = ["no_selected_groups"]
        return []
    for item in items:
        kind, g, r = stock_identity(item, profile, index)
        threshold = 0.50 if kind == "known" else 0.60 if kind == "new_character" else 0.65
        if item.get("bookmarks") is not None and item["_quality"] < threshold:
            continue
        key = (kind, g, r)
        if key not in weights:
            continue
        item["stock_pool"] = kind
        if g is not None:
            item["primary_group"] = g
        if r is not None:
            item["primary_character"] = r
        pools[key].append(item)
    for pool in pools.values():
        pool.sort(key=lambda i: (-i["_score"], i["pid"]))
    chosen, counts, authors = [], Counter(), Counter()
    history = {key: profile.get("quota_history", {}).get(str(key), 0) for key in weights}
    history_total = sum(history.values())
    # Use a fixed batch budget rather than shrinking away exploration when supply is thin.
    # Repeated pages consume this one immutable schedule, with no per-page rounding.
    for slot in range(180):
        if len(chosen) % 20 == 0:
            authors.clear()
        supplied = [key for key in weights if pools[key] and counts[key] < max(2, math.ceil(180 * weights[key]))]
        if not supplied:
            break
        active = [key for key in supplied if counts[key] < max(2, math.ceil(weights[key] * (slot + 1)))]
        if not active:
            continue
        key = max(active, key=lambda k: (weights[k] * (history_total + slot + 1) - history[k] - counts[k], str(k)))
        item = take(pools[key], chosen, authors)
        item.pop("_score", None)
        item.pop("_quality", None)
        chosen.append(item)
        counts[key] += 1
        authors[item["author_id"]] += 1
    # Ratios also constrain returned supply, not just a hypothetical full batch.
    # Missing known-role stock must not turn a short result into 100% exploration.
    known = Counter(i.get("primary_group") for i in chosen if i["stock_pool"] == "known")
    caps = {
        g: math.floor(known[g] * e / max(0.01, 1 - e) + 1e-9) for g, e in profile["new_character_fractions"].items()
    }
    new_counts = Counter()
    filtered = []
    for item in chosen:
        if item["stock_pool"] == "new_character":
            g = item["primary_group"]
            if new_counts[g] >= caps[g]:
                continue
            new_counts[g] += 1
        filtered.append(item)
    max_new_groups = math.floor(sum(i["stock_pool"] != "new_group" for i in filtered) * 0.05 / 0.95 + 1e-9)
    chosen = []
    for item in filtered:
        if item["stock_pool"] == "new_group":
            if max_new_groups <= 0:
                continue
            max_new_groups -= 1
        chosen.append(item)
    counts = Counter((i["stock_pool"], i.get("primary_group"), i.get("primary_character")) for i in chosen)
    profile.update(
        bucket_probabilities={str(k): v for k, v in weights.items()},
        assigned_pools=dict(
            Counter(
                {
                    kind: sum(n for (k, _, _), n in counts.items() if k == kind)
                    for kind in ("known", "new_character", "new_group")
                }
            )
        ),
        assigned_groups={
            g: sum(n for (kind, group, _), n in counts.items() if group == g and kind == "known")
            for g in profile["quotas"]
        },
        group_shortfalls={
            g: max(
                0,
                math.ceil(180 * 0.95 * q * (1 - profile["new_character_fractions"][g]))
                - sum(n for (kind, group, _), n in counts.items() if kind == "known" and group == g),
            )
            for g, q in profile["quotas"].items()
        },
        bucket_shortfalls={str(k): max(0, math.floor(180 * v) - counts[k]) for k, v in weights.items()},
    )
    return chosen
