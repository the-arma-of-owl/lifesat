#!/usr/bin/env python3
"""p4_reference_oracle.py — an INDEPENDENT derivation of the random join.

Plan step 10: "Compare production scorer with independently written reference
oracle."

⚠️ WHY A NEW ONE. The repository already ships `analysis/tests/reference_scorer.py`,
and it was NOT independent for this estimand — it carried the identical defect:

    alarms = {r["f"].get("tmSeq") for r in events if r["cat"] == "rnd.alarm"}
                                        └── tests/reference_scorer.py:297

Two implementations agreed because one copied the other's mistake. An oracle
that shares the assumption under test cannot falsify it, so agreement with that
file would have been worth nothing.

INDEPENDENCE, CONCRETELY. This oracle never reads the field `n` and never counts
positions. It joins on the SIMULATION TIME WITNESS instead: `tm.recv` is logged
and `observe()` is called inside a single `GroundStation::handleTelemetry`
invocation, so an alarm and its observation carry the same timestamp. The
production scorer derives the pairing from the ordinal; this one derives it from
the clock. They share the raw file and nothing else, so agreement between them
is evidence and not an echo.

Where the time witness is ambiguous — more than one observation at the same
instant — this oracle refuses that row rather than guessing. A refusal is
reported; it is never silently resolved in favour of the production answer.
"""

from __future__ import annotations

import collections
import os
import sys

sys.dont_write_bytecode = True

TOLERANCE = 1e-9


def bind_by_time(events):
    """Pair each rnd.alarm with the observation sharing its instant.

    Returns {"pairs": {alarm_index: observation_index}, "ambiguous": [...],
             "unwitnessed": [...]} using positions in the tm.recv sequence so
    the result is directly comparable with the ordinal derivation — comparable,
    but arrived at without ever reading `n`.
    """
    observations = [row for row in events if row["cat"] == "tm.recv"]
    by_time = collections.defaultdict(list)
    for position, row in enumerate(observations, start=1):
        by_time[round(row["t"], 9)].append(position)

    pairs, ambiguous, unwitnessed = {}, [], []
    alarm_index = 0
    for row in events:
        if row["cat"] != "rnd.alarm":
            continue
        alarm_index += 1
        candidates = by_time.get(round(row["t"], 9), [])
        if len(candidates) == 1:
            pairs[alarm_index] = candidates[0]
        elif not candidates:
            unwitnessed.append({"alarm_index": alarm_index, "time": row["t"]})
        else:
            ambiguous.append({"alarm_index": alarm_index, "time": row["t"],
                              "candidates": candidates})
    return {"ambiguous": ambiguous, "observation_count": len(observations),
            "pairs": pairs, "unwitnessed": unwitnessed}


def alarmed_ordinals(events):
    """The set of observation positions the TIME derivation says were alarmed."""
    return set(bind_by_time(events)["pairs"].values())


def confusion(events, effect_events):
    """The random detector's confusion counts, derived from the time witness.

    Deliberately written as a straight loop over observations rather than by
    calling any production helper: sharing code would reintroduce exactly the
    coupling this oracle exists to break.
    """
    positives = {e["start"] for e in effect_events
                 if e["kind"].startswith("received_")}
    alarmed = alarmed_ordinals(events)
    tp = fp = fn = tn = 0
    position = 0
    for row in events:
        if row["cat"] != "tm.recv":
            continue
        position += 1
        truth_positive = row["t"] in positives
        has_alarm = position in alarmed
        if truth_positive and has_alarm:
            tp += 1
        elif truth_positive:
            fn += 1
        elif has_alarm:
            fp += 1
        else:
            tn += 1
    return {"fn": fn, "fp": fp, "tn": tn, "tp": tp}


def compare(events, effect_events, production_block, production_binding):
    """Disagreements between the two derivations, as findings.

    Reports EVERY axis it can compare — the alarmed set, the confusion counts,
    and the ambiguity the oracle itself hit — because an oracle that only
    reports a single boolean tells you nothing about where it diverged.
    """
    findings = []
    witness = bind_by_time(events)
    oracle_set = set(witness["pairs"].values())
    production_set = set(production_binding.alarmed_ordinals)

    if witness["ambiguous"]:
        findings.append({
            "detector_id": "D-P4-ORACLE-AMBIGUOUS-01",
            "message": (f"{len(witness['ambiguous'])} alarms share an instant "
                        f"with more than one observation; the time witness "
                        f"cannot resolve them and this oracle refuses to guess"),
        })
    if oracle_set != production_set:
        only_oracle = sorted(oracle_set - production_set)[:5]
        only_production = sorted(production_set - oracle_set)[:5]
        findings.append({
            "detector_id": "D-P4-ORACLE-AGREEMENT-01",
            "message": (f"the alarmed observation sets differ: "
                        f"{len(oracle_set - production_set)} only in the time "
                        f"derivation {only_oracle}, "
                        f"{len(production_set - oracle_set)} only in the ordinal "
                        f"derivation {only_production}"),
        })
    expected = confusion(events, effect_events)
    observed = {key: production_block.get(key) for key in ("tp", "fp", "fn", "tn")}
    if expected != observed:
        findings.append({
            "detector_id": "D-P4-ORACLE-AGREEMENT-01",
            "message": (f"confusion counts differ: time derivation {expected} "
                        f"vs production {observed}"),
        })
    return findings
