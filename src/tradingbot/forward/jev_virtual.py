"""Seeded controls chosen before execution, never from realized fills/P&L."""
from collections import defaultdict
from decimal import Decimal as D
import random

from tradingbot.strategy.jev import Plan


def random_choices(real: Plan, selected: dict[str, str], virtual: Plan, *, seed: str):
    """Match observed decision pass rate within action class at each boundary.

    Exact count when candidate counts match. Different holding states can
    change candidate counts: use unbiased stochastic rounding of p * N and
    report that divergence. Unavailable real decisions contribute no passes;
    if none are available, no random decision is issued. Regime controls draw
    uniformly from the predeclared regimes, including cash.
    """
    rng = random.Random(seed)
    groups = defaultdict(list)
    valid, candidates = defaultdict(list), defaultdict(list)
    choices, audit = {}, {}
    for spec in real.decisions:
        candidates[spec.action_class].append(spec)
        if spec.key in selected:
            valid[spec.action_class].append((spec, selected[spec.key]))
    for spec in virtual.decisions:
        if spec.random_mode == "uniform":
            if valid[spec.action_class]:
                choices[spec.key] = rng.choice(sorted(spec.random_options or spec.alternatives))
            continue
        groups[spec.action_class].append(spec)
    for kind, specs in groups.items():
        observed = valid[kind]
        if not observed:
            audit[kind] = {"real_available": 0, "virtual_candidates": len(specs), "selected": 0}
            continue
        passes = sum(choice != spec.skip for spec, choice in observed)
        expected = D(passes) * len(specs) / len(candidates[kind])
        count = int(expected) + (rng.random() < float(expected-int(expected)))
        admitted = set(rng.sample(range(len(specs)), count))
        for i, spec in enumerate(specs):
            alternatives = sorted(k for k in spec.alternatives if k != spec.skip)
            choices[spec.key] = rng.choice(alternatives) if i in admitted and alternatives else spec.skip
        audit[kind] = {"real_candidates": len(candidates[kind]), "real_available": len(observed), "real_passes": passes,
                       "virtual_candidates": len(specs), "selected": count}
    return choices, audit


def matched_size_factors(real, selected, factors, virtual, choices, *, seed):
    """Shuffle passing code-size factors independently of symbol selection.

    Equal pass counts preserve the size-factor multiset; different eligibility
    cycles a seeded permutation. No future fill, P&L or model call is used.
    """
    rng, pools, counts = random.Random(seed), defaultdict(list), defaultdict(int)
    for spec in real.decisions:
        if spec.key in selected and selected[spec.key] != spec.skip:
            pools[spec.action_class].append(D(factors.get(spec.key, "1")))
    for pool in pools.values():
        rng.shuffle(pool)
    result = {}
    for spec in virtual.decisions:
        if spec.key not in choices or choices[spec.key] == spec.skip:
            continue
        pool = pools[spec.action_class]
        factor = pool[counts[spec.action_class] % len(pool)] if pool else D(1)
        result[spec.key] = str(max(spec.minimum_size_factor, min(D(1), factor)))
        counts[spec.action_class] += 1
    return result
