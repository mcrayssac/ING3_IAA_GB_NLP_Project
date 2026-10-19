"""Paired race-cluster uncertainty with protocol 1.1.0 draws and limits."""

from __future__ import annotations

import hashlib
import math
import random
from collections import Counter

from .metrics import DIRECTIONS, MACROS, all_measures


def quantile(values: list[float], probability: float) -> float:
    """Linear/type-7 sample quantile."""
    if not values or not 0 <= probability <= 1:
        raise ValueError("quantile requires observations and probability in [0, 1]")
    ordered = sorted(values)
    h = (len(ordered) - 1) * probability
    j = math.floor(h)
    return ordered[j] + (h - j) * (ordered[min(j + 1, len(ordered) - 1)] - ordered[j])


def bootstrap_compare(
    observations: dict[str, list[dict]],
    old: str,
    new: str,
    *,
    human: bool = False,
    seed: int = 2026,
    replications: int = 10000,
) -> dict:
    """Use common whole-race draws; small replication counts are for unit checks only."""
    if replications < 1:
        raise ValueError("replications must be positive")
    if human:
        observations = {
            version: [row for row in rows if row.get("review_selected")]
            for version, rows in observations.items()
        }
    previous, current = observations[old], observations[new]
    if [(r["case_id"], r["input_sha256"]) for r in previous] != [
        (r["case_id"], r["input_sha256"]) for r in current
    ]:
        raise ValueError("pairing_error: different target inputs/order")
    races = sorted({r["race_id"] for r in previous})
    points = {v: all_measures(observations[v], human) for v in (old, new)}
    keys = list(points[old])
    simple = [key for key in keys if key not in MACROS]
    race_counts = {
        v: {
            race: all_measures(
                [r for r in observations[v] if r["race_id"] == race], human
            )
            for race in races
        }
        for v in (old, new)
    }
    draws: dict[str, list[float]] = {key: [] for key in keys}
    rng = random.Random(seed)
    draw_fingerprint = hashlib.sha256()
    for _ in range(replications):
        draw = [rng.randrange(len(races)) for _ in races]
        draw_fingerprint.update((",".join(map(str, draw)) + "\n").encode())
        multiplicity = Counter(draw)
        values = {}
        for version in (old, new):
            pooled = {}
            for key in simple:
                n = sum(
                    race_counts[version][races[i]][key].numerator * m
                    for i, m in multiplicity.items()
                )
                d = sum(
                    race_counts[version][races[i]][key].denominator * m
                    for i, m in multiplicity.items()
                )
                pooled[key] = float(n / d) if d else None
            for key, components in MACROS.items():
                parts = [pooled[c] for c in components]
                pooled[key] = (
                    sum(parts) / len(parts)
                    if all(p is not None for p in parts)
                    else None
                )
            values[version] = pooled
        for key in keys:
            a, b = values[old][key], values[new][key]
            if a is not None and b is not None:
                draws[key].append(b - a)
    metrics = {}
    for key in keys:
        a, b = points[old][key], points[new][key]
        difference = (
            b.exact - a.exact if a.exact is not None and b.exact is not None else None
        )
        contributors = (
            [
                race
                for race in races
                if race_counts[old][race][key].denominator > 0
                and race_counts[new][race][key].denominator > 0
            ]
            if key not in MACROS
            else []
        )
        components = {
            component: [
                race
                for race in races
                if race_counts[old][race][component].denominator > 0
                and race_counts[new][race][component].denominator > 0
            ]
            for component in MACROS.get(key, ())
        }
        if components:
            contributors = sorted(set().union(*(set(rs) for rs in components.values())))
        count = min(map(len, components.values())) if components else len(contributors)
        samples = draws[key]
        if a.reason == "incomplete_ratings" or b.reason == "incomplete_ratings":
            status = "incomplete_ratings"
        elif difference is None:
            status = a.reason or b.reason or "empty_population"
        elif count < 2:
            status = "single_race"
        elif len(samples) < math.ceil(0.95 * replications):
            status = "insufficient_valid_replicates"
        else:
            status = "few_races" if count < 5 else "ok"
        interval = (
            [quantile(samples, 0.025), quantile(samples, 0.975)]
            if status in {"ok", "few_races"}
            else None
        )
        direction = DIRECTIONS.get(key.rsplit("/", 1)[-1], "higher")
        gain_interval = (
            [-interval[1], -interval[0]]
            if direction == "lower" and interval
            else interval
            if direction == "higher"
            else None
        )
        metrics[key] = {
            "old": a.as_dict(),
            "new": b.as_dict(),
            "difference": float(difference) if difference is not None else None,
            "gain": None
            if difference is None or direction == "descriptive"
            else float(-difference if direction == "lower" else difference),
            "difference_interval": interval,
            "gain_interval": gain_interval,
            "direction": direction,
            "interval_status": status,
            "valid_replications": len(samples),
            "invalid_replications": replications - len(samples),
            "conditional_on_valid_replications": len(samples) < replications,
            "contributing_races": contributors,
            "component_races": components,
        }
    sizes = Counter(r["race_id"] for r in previous)
    scenarios = Counter(r["scenario_id"] for r in previous)
    return {
        "old": old,
        "new": new,
        "analysis_population": "selected_review_targets"
        if human
        else "all_ledger_cases",
        "settings": {
            "seed": seed,
            "replications": replications,
            "confidence_level": 0.95,
            "method": "paired_whole_race_percentile",
            "quantiles": "linear_type_7",
            "minimum_valid_replications": math.ceil(0.95 * replications),
            "protocol_settings": seed == 2026 and replications == 10000,
        },
        "race_order": races,
        "race_case_counts": dict(sizes),
        "largest_race_case_share": max(sizes.values(), default=0) / len(previous)
        if previous
        else None,
        "scenario_sizes": dict(scenarios),
        "draws_sha256": draw_fingerprint.hexdigest(),
        "metrics": metrics,
        "limitations": [
            "Resamples observed cases/races, not training seeds or source revisions.",
            "Many related variants do not create independent races.",
            "Zero-width intervals do not prove equivalence.",
            "Intervals with invalid draws condition on the valid draws; the discarded count is reported without redrawing.",
        ],
    }
