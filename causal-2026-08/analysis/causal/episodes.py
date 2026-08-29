#!/usr/bin/env python3
"""episodes.py -- one episode record per pilot run, decided by the ACCEPTED oracle.

The oracle is not reimplemented here.  `causal_core.run_oracle` and
`causal_core.build_evidence_records` are imported from the read-only accepted
Phase 2 v7 tree and executed unchanged, so the prediction this package records
is produced by the same code the accepted validator uses to recompute it.  If
the two ever disagreed, the disagreement would be in the raw events, which is
exactly where Phase 3's work is.

Truth is read from the run's own truth authority and is used for TWO things
only: the episode boundaries and `truth_cause`.  It never reaches the binder,
never reaches a feature, and the isolation test in the Phase 3 suite proves it
by scrambling every truth field and requiring the prediction not to move.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True

ACCEPTED_TOOLS = os.environ.get("LIFESAT_TOOLS", str(Path(__file__).resolve().parents[2] / "tools"))
if not os.path.isdir(ACCEPTED_TOOLS):
    raise SystemExit(
        "the accepted tools package is not present at %s.\n"
        "It is deposited with the run artefacts rather than with the source. "
        "Set LIFESAT_TOOLS to the directory holding causal_core.py."
        % ACCEPTED_TOOLS)
if ACCEPTED_TOOLS not in sys.path:
    sys.path.insert(0, ACCEPTED_TOOLS)

import causal_core as CC  # noqa: E402


class EpisodeError(Exception):
    pass


def _kind(row):
    """The row's kind, in either shape it can arrive in.

    Straight off the producer's CSV it is a `kind=` field; after
    `canonical.canonical_truth` it has been lifted to a top-level key, because
    that is the shape the accepted truth authority uses. Both are read here so
    the same code decides an episode whichever side of the lift it is called on.
    """
    return row["fields"].get("kind", row.get("kind"))


def analysis_cutoff(events, episode_end):
    """decision_mode.cutoff_derivation, literally.

    'analysis_cutoff = the FIRST pass.end whose time is >= the episode's truth
    episode.end time.'  A run whose target episode has no closing contact is a
    run whose evidence was never complete; that is reported, not patched.
    """
    ends = sorted(e["time"] for e in events if e["category"] == "pass.end")
    later = [t for t in ends if t >= episode_end]
    if not later:
        raise EpisodeError(
            f"no pass.end at or after the episode end {episode_end}; the "
            f"analysis cutoff is undefined for this run")
    return later[0]


def derive_truth_cause(interventions):
    """truth_reference_spec.cause_derivation_rule, as a total function."""
    causes = {row["fields"]["cause"] for row in interventions}
    if not causes:
        raise EpisodeError("an episode with no intervention has no derivable cause")
    if "third_cause" in causes:
        return "third_cause"
    if {"attack", "fault"} <= causes:
        return "compound"
    if len(causes) != 1:
        raise EpisodeError(f"cause set {causes} is not resolvable")
    return next(iter(causes))


def build_episode(contract, cell, events, truth, ignore_truth_binding=False):
    """Returns one schema-shaped episode record for one pilot run."""
    begins = [r for r in truth if _kind(r) == "episode.begin"]
    ends = [r for r in truth if _kind(r) == "episode.end"]
    mids = [r for r in truth if _kind(r) == "intervention"]
    if len(begins) != 1 or len(ends) != 1:
        raise EpisodeError(f"{cell['run_id']}: {len(begins)} episode.begin and "
                           f"{len(ends)} episode.end rows, expected one of each")
    if not mids:
        raise EpisodeError(f"{cell['run_id']}: no intervention truth row")

    # episode_id IS the run id.  The producer writes `episode_ref` into every
    # truth row of the run, and the accepted validator compares that field to
    # episode_id directly; a decorative prefix here would mean the two never
    # match. It also makes event_id = "{episode_id}-E{n}" resolve back to its
    # own episode under the validator's own episode_of().
    episode_id = cell["run_id"]
    begin, end = begins[0]["time"], ends[0]["time"]
    cutoff = analysis_cutoff(events, end)

    pair = next(p for p in contract["pair_intervention_registry"]["pairs"]
                if p["pair_id"] == cell["pair_id"])

    episode = {
        "analysis_cutoff": cutoff,
        "arm": cell["arm"],
        "episode_begin": begin,
        "episode_end": end,
        "episode_id": episode_id,
        "pair_id": cell["pair_id"],
        "primary_channel": pair["primary_channel"],
        "run_seed_index": cell["run_seed_index"],
        "symptom_class": cell["symptom_class"],
        "truth_cause": derive_truth_cause(mids),
        "truth_episode_begin_id": _truth_id(begins[0], cell, 0),
        "truth_episode_end_id": _truth_id(ends[0], cell, len(truth) - 1),
        "truth_intervention_ids": [_truth_id(r, cell, i)
                                   for i, r in enumerate(mids, start=1)],
        "truth_run_id": cell["run_id"],
        "truth_seed_index": cell["run_seed_index"],
    }

    rule = next(r for r in contract["decision_rules"]
                if r["pair_id"] == cell["pair_id"])
    predicted, reason, trace = CC.run_oracle(contract, episode, events)
    scope = trace["scope"]

    episode["predicted_class"] = predicted
    episode["abstention_reason_code"] = reason
    episode["symptom_onset_available_time"] = trace.get("symptom_onset_available_time")
    episode["evidence_records"] = CC.build_evidence_records(
        episode, scope, contract, rule)
    # 'episodes with at least one admissible observation at the cutoff'
    episode["evaluable"] = bool(scope.children.get("units"))
    # decision_mode.ordering_rule: decision_time > analysis_cutoff for every
    # evaluable episode. The decision is taken when the analyst runs the oracle
    # over the closed record, which is after the cutoff by construction.
    episode["decision_time"] = cutoff + contract["model_authority"]["telemetry_interval_s"]

    if not ignore_truth_binding:
        _check_truth_binding(contract, cell, episode, mids, begins[0], ends[0])
    return episode


def _truth_id(row, cell, index):
    return row.get("truth_id") or f"{cell['run_id']}-T{row['index']:03d}"


def _check_truth_binding(contract, cell, episode, interventions, begin, end):
    """truth_reference_spec, enforced HERE as well as by the validator.

    A defect that only the accepting party's validator catches is a defect this
    package shipped. The same rules are checked at production time so that a
    broken run fails where it was produced.
    """
    pair = next(p for p in contract["pair_intervention_registry"]["pairs"]
                if p["pair_id"] == cell["pair_id"])
    for row in (begin, end, *interventions):
        fields = row["fields"]
        if fields.get("run_id") != cell["run_id"]:
            raise EpisodeError(f"{cell['run_id']}: truth row run_id "
                               f"{fields.get('run_id')!r} does not own this episode")
        if fields.get("pair_id") != cell["pair_id"]:
            raise EpisodeError(f"{cell['run_id']}: truth row pair_id mismatch")
        if int(fields.get("seed_index", -1)) != cell["run_seed_index"]:
            raise EpisodeError(f"{cell['run_id']}: truth row seed_index mismatch")
    for row in interventions:
        if not episode["episode_begin"] <= row["time"] <= episode["episode_end"]:
            raise EpisodeError(f"{cell['run_id']}: intervention at {row['time']} "
                               f"lies outside the episode window")
        cause = row["fields"]["cause"]
        if cause in ("attack", "fault"):
            declared = pair[f"{cause}_arm"]
            if row["fields"]["intervention_class"] != declared["truth_intervention_class"]:
                raise EpisodeError(
                    f"{cell['run_id']}: intervention class "
                    f"{row['fields']['intervention_class']!r} != registry "
                    f"{declared['truth_intervention_class']!r}")
            if row["fields"].get("units") != declared["units"]:
                raise EpisodeError(
                    f"{cell['run_id']}: units {row['fields'].get('units')!r} != "
                    f"registry {declared['units']!r}")
