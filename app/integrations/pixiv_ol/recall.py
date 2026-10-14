"""Bounded weighted recall budget with durable counts and shortage-aware tag selection."""

from collections import Counter

WEIGHTS = {"native": 0.35, "related": 0.25, "search": 0.30, "ranking": 0.10}


def wave(queries, seeds, counts, *, limit, stock_selector=None):
    counts = Counter(counts)
    remaining = list(queries)
    seed_queue = list(seeds)
    picked = []
    related = []
    for _ in range(limit):
        families = []
        if any(q.get("source") == "ranking" for q in remaining):
            families.append("ranking")
        if any(q.get("source") != "ranking" for q in remaining):
            families.append("search")
        if seed_queue:
            families.append("related")
        if not families:
            break
        # Normalize only over available transports. Exhausted native streams cannot supply requests.
        total = sum(WEIGHTS[f] for f in families)
        family = max(
            families, key=lambda f: (WEIGHTS[f] / total * (sum(counts[f] for f in families) + 1) - counts[f], f)
        )
        counts[family] += 1
        if family == "related":
            related.append(seed_queue.pop(0))
        else:
            options = [q for q in remaining if (q.get("source") == "ranking") == (family == "ranking")]
            query = stock_selector(options)[0] if stock_selector and family == "search" else options[0]
            picked.append(query)
            remaining.remove(query)
    return picked, related, dict(counts)
