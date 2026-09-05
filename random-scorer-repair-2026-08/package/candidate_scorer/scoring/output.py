"""The contract output schema: provenance, cells, per-run records, delays.

Contract: output_schema (closed key set, typed fields, non-negative integer
counts, non-empty cells, mandatory per-run records and provenance).
"""
import hashlib
import os

from . import metrics

CONTRACT_RELPATH = os.path.join("specs", "scoring-contract-v1.json")
MATCHING_POLICY_DEFAULT = "monotone_forward_one_to_one_bounded_by_next_action"
WINDOW_INDEX_RULE = "observation_window_ceil"
TREE_DIGEST_SPEC = "lifesat-tree-digest/v1"


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root):
    """lifesat-tree-digest/v1 over a directory of regular files."""
    rows = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            rows.append((rel, full))
    rows.sort(key=lambda item: item[0].encode("utf-8"))
    digest = hashlib.sha256()
    for rel, full in rows:
        digest.update(("%s  %s\n" % (sha256_file(full), rel)).encode("utf-8"))
    return digest.hexdigest()


def build_provenance(sim_root, run_identities, generated_utc, contract_version,
                     matching_policy=MATCHING_POLICY_DEFAULT):
    results = os.path.join(sim_root, "results")
    return {
        "contract_version": contract_version,
        "contract_json_sha256": sha256_file(os.path.join(sim_root, CONTRACT_RELPATH)),
        "scorer_sha256": scorer_digest(sim_root),
        "matrix_json_sha256": sha256_file(os.path.join(results, "matrix.json")),
        "results_tree_digest": tree_digest(results),
        "results_tree_digest_spec": TREE_DIGEST_SPEC,
        "generated_utc": generated_utc,
        "run_identities": list(run_identities),
        "matching_policy_id": matching_policy,
        "window_index_rule_id": WINDOW_INDEX_RULE,
        "omnetpp_version": "6.4.0",
        "inet_version": "4.7.0",
    }


def scorer_digest(sim_root):
    """Digest of the production scoring code actually used."""
    return scorer_digest_of_analysis(os.path.join(sim_root, "analysis"))


def scorer_digest_of_analysis(analysis):
    """Same recipe, addressed by the analysis root directly.

    Phase 4 splits the two: the candidate scorer does not sit under a
    `<sim>/analysis` path, and the digest recipe must stay byte-identical to the
    accepted one or the successor's scorer digest cannot be compared with the
    historical pin at all.
    """
    parts = [os.path.join(analysis, "score.py")]
    package = os.path.join(analysis, "scoring")
    for name in sorted(os.listdir(package)):
        if name.endswith(".py"):
            parts.append(os.path.join(package, name))
    digest = hashlib.sha256()
    for path in parts:
        digest.update(("%s  %s\n" % (sha256_file(path),
                                     os.path.relpath(path, analysis))).encode("utf-8"))
    return digest.hexdigest()


BOOTSTRAP_METHOD = "two-sided 95% percentile bootstrap"
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 12345
RESAMPLING_UNIT = "run"


def percentile_bootstrap(values, resamples=BOOTSTRAP_RESAMPLES,
                         seed=BOOTSTRAP_SEED, alpha=0.05):
    """Two-sided 95% percentile bootstrap over the DEFINED per-run values.

    Contract uncertainty policy:
      · applies to run-macro estimands only, never to a pooled ratio;
      · the resampling unit is the seven-day run / seed index;
      · 2000 resamples, seed 12345, so the interval is deterministic;
      · undefined runs are excluded before resampling, exactly as they are
        excluded from the macro mean, so the interval describes the same
        `over defined runs` estimand;
      · an all-zero cell returns NO interval: resampling zeros yields [0,0] by
        construction and that is a bootstrap artefact, not an unseen-risk bound.

    Returns None when no interval may be published.
    """
    import random

    defined = [v for v in values if v is not None]
    if not defined:
        return None
    if all(v == 0.0 for v in defined):
        return None                      # all-zero cell: observed counts only
    rng = random.Random(seed)
    n = len(defined)
    means = []
    for _ in range(resamples):
        total = 0.0
        for _i in range(n):
            total += defined[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    low = means[int(alpha / 2 * resamples)]
    high = means[int((1 - alpha / 2) * resamples) - 1]
    return {"method": BOOTSTRAP_METHOD, "resamples": resamples, "seed": seed,
            "resampling_unit": RESAMPLING_UNIT, "ci_low": low, "ci_high": high}


def estimand_is_all_zero(per_run):
    """True when EVERY defined per-run value of THIS estimand is zero.

    The zero-event policy is scoped to the estimand, not to the cell. A cell can
    hold an estimand that is uniformly zero (A1/D3 state transitions: 0 of 474)
    next to one that varies (A1/D3 execution: 0.75 to 1.0). Suppressing the
    second because the first is zero would delete a legitimate interval and hide
    real seed-to-seed variability; publishing an interval for the first would
    present a [0,0] bootstrap artefact as an unseen-risk bound. Each estimand is
    therefore judged on its own defined runs.
    """
    defined = [p.get("value") for p in per_run or [] if p.get("value") is not None]
    return bool(defined) and all(v == 0.0 for v in defined)


def estimand_result(estimand_id, family, unit, pairs, run_identities):
    """One estimand over a cell: macro over defined runs plus a pooled ratio."""
    per_run = []
    values = []
    for (numerator, denominator), run in zip(pairs, run_identities):
        value, code = metrics.ratio(numerator, denominator, metrics.NO_POSITIVES)
        values.append(value)
        per_run.append({"run_identity": run, "numerator": int(numerator),
                        "denominator": int(denominator), "value": value,
                        "undefined_reason_code": code,
                        "defined_value_qualifier_code": None})
    macro, macro_code, defined, total = metrics.macro_over_defined_runs(values)
    pooled_value = metrics.pooled([n for n, _d in pairs], [d for _n, d in pairs])
    observed_numerator = int(sum(n for n, _d in pairs))
    observed_denominator = int(sum(d for _n, d in pairs))
    return {"estimand_id": estimand_id, "result_family": family,
            "evaluation_unit": unit,
            "numerator": observed_numerator,
            "denominator": observed_denominator,
            "observed_numerator": observed_numerator,
            "observed_denominator": observed_denominator,
            "value": macro, "undefined_reason_code": macro_code,
            "defined_value_qualifier_code": None,
            "macro_mean_over_defined_runs": macro, "pooled_ratio": pooled_value,
            "defined_run_count": defined, "total_run_count": total,
            "uncertainty": (None if estimand_is_all_zero(per_run)
                            else percentile_bootstrap(values)),
            "per_run": per_run}


def delay_record(clock_id, origin, endpoint, conditioning, detected, scored, value):
    code = None if value is not None else metrics.NO_DELAY
    return {"clock_id": clock_id, "delay_origin": origin,
            "delay_endpoint": endpoint, "conditioning": conditioning,
            "detected_count": int(detected), "scored_count": int(scored),
            "value": value, "undefined_reason_code": code}
