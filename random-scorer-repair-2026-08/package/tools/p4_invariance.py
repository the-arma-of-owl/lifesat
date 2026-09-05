#!/usr/bin/env python3
"""p4_invariance.py — what the repair was allowed to move, and what it was not.

Plan step 8: "Prove unaffected non-random estimands invariant."

The repair touches ONE join. Every estimand that does not read the random
detector must come out of the successor byte-for-byte identical to the
historical package, and the ones that do read it must change — a repair that
changed nothing would not have been a repair.

Both directions are checked. Only asserting "nothing else moved" would pass
trivially if the rescoring had silently failed to run.
"""

from __future__ import annotations

import json
import os
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import p4_authority as PA  # noqa: E402
import p4_checks as PC     # noqa: E402

# The only estimand that reads the random detector.
RANDOM_ESTIMANDS = ("EST-F3-RND-01",)

# Within that estimand the arms split by whether the JOIN feeds them.
#
#   precision, fpr, recall  are computed from tp/fp/fn/tn, which is where the
#                           broken key did its damage — these must move.
#   event_recall            is computed by `state.credit_alarms(alarm_times,
#                           effect_events)` (scoring/state.py:101), which takes
#                           alarm TIMES and never touches the join key. It was
#                           correct before the repair and must stay EXACTLY as
#                           it was; if it moved, the repair leaked into a path
#                           it had no business in.
JOIN_DEPENDENT_ARMS = frozenset({"precision", "fpr", "recall"})
JOIN_INDEPENDENT_ARMS = frozenset({"event_recall"})

# The plan's audit anchors: raw random alarms per scenario, per defence cell.
# They are ANCHORS, not publication values. The repaired precision denominator
# is tp + fp — every alarm the detector raised — so it must reproduce them
# exactly. Under the old join tp + fp was 0 and precision was undefined, so this
# cross-check was not even expressible before the repair.
PLAN_ALARM_ANCHORS = {"A1": 481, "A2": 513, "A3": 513, "A4": 491, "B0": 455}


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def estimand_index(package):
    """{(cell, estimand_id, arm): canonical node} for one package."""
    index = {}
    for cell in package.get("cells", []):
        for estimand in cell.get("estimands", []):
            for arm, node in estimand.get("arms", {}).items():
                index[(cell["cell"], estimand["estimand_id"], arm)] = node
    return index


def compare(historical_path, successor_path, label):
    """Compare two package files estimand by estimand."""
    historical = PA.load_json(historical_path, dict)
    successor = PA.load_json(successor_path, dict)
    left, right = estimand_index(historical), estimand_index(successor)

    findings, moved, invariant = [], [], 0
    missing = sorted(set(left) - set(right))
    added = sorted(set(right) - set(left))
    if missing:
        findings.append(PC.finding(
            "D-P4-INVARIANCE-01",
            f"{len(missing)} estimand arms present historically are absent from "
            f"the successor, e.g. {missing[:3]}", label))
    if added:
        findings.append(PC.finding(
            "D-P4-INVARIANCE-01",
            f"{len(added)} estimand arms appear in the successor that the "
            f"historical package does not carry, e.g. {added[:3]}", label))

    undefined_both = []
    for key in sorted(set(left) & set(right)):
        same = _canonical(left[key]) == _canonical(right[key])
        is_random = key[1] in RANDOM_ESTIMANDS
        join_fed = is_random and key[2] in JOIN_DEPENDENT_ARMS
        if same:
            invariant += 1
            if join_fed:
                # An arm that is undefined on BOTH sides for a declared reason
                # is legitimately invariant: the repair cannot move a quantity
                # that has no defined run to compute it from. Recorded, not
                # excused — the reason code is what makes it checkable.
                if (left[key].get("value") is None
                        and right[key].get("value") is None
                        and right[key].get("undefined_reason_code")):
                    undefined_both.append(
                        (key, right[key]["undefined_reason_code"]))
                else:
                    findings.append(PC.finding(
                        "D-P4-REPAIR-EFFECT-01",
                        f"{key} is fed by the join, carries a defined value, "
                        f"and is byte-identical to the historical one; the "
                        f"repaired join did not reach the scored output", label))
        else:
            moved.append(key)
            if not is_random:
                findings.append(PC.finding(
                    "D-P4-INVARIANCE-01",
                    f"{key} does not read the random detector but changed; the "
                    f"repair was supposed to touch one join only", label))
            elif key[2] in JOIN_INDEPENDENT_ARMS:
                findings.append(PC.finding(
                    "D-P4-INVARIANCE-01",
                    f"{key} is computed from alarm TIMES by credit_alarms and "
                    f"never reads the join key, yet it changed; the repair "
                    f"leaked into a path it does not own", label))

    if not moved:
        findings.append(PC.finding(
            "D-P4-REPAIR-EFFECT-01",
            "no estimand arm moved at all; a rescoring that changes nothing "
            "did not rescore", label))

    findings.extend(check_plan_anchors(right, label))
    return {
        "added": added,
        "arms_compared": len(set(left) & set(right)),
        "findings": findings,
        "invariant": invariant,
        "legitimately_undefined_both_sides": undefined_both,
        "missing": missing,
        "moved": moved,
    }


def check_plan_anchors(successor_index, label):
    """The repaired precision denominator reproduces the plan's raw anchors."""
    findings, observed = [], {}
    for (cell, estimand, arm), node in successor_index.items():
        if estimand not in RANDOM_ESTIMANDS or arm != "precision":
            continue
        scenario = cell.split("-")[0]
        denominator = node.get("denominator")
        if denominator is None:
            continue
        previous = observed.setdefault(scenario, denominator)
        if previous != denominator:
            findings.append(PC.finding(
                "D-P4-ANCHOR-01",
                f"{scenario}: the alarm count differs between its defence "
                f"cells ({previous} vs {denominator}); the random detector is "
                f"defence-independent and must not", label))
    for scenario, expected in sorted(PLAN_ALARM_ANCHORS.items()):
        got = observed.get(scenario)
        if got is None:
            findings.append(PC.finding(
                "D-P4-ANCHOR-01",
                f"{scenario}: no defined random precision denominator, so the "
                f"plan's audit anchor {expected} cannot be checked", label))
        elif got != expected:
            findings.append(PC.finding(
                "D-P4-ANCHOR-01",
                f"{scenario}: {got} random alarms scored, the plan's audit "
                f"anchor is {expected}", label))
    return findings


def check_historical_untouched():
    """The rollback target is byte-exact. Checked, not assumed."""
    findings = []
    info = PA.historical()
    for name, pinned in sorted(info["digests"].items()):
        path = os.path.join(PA.HISTORICAL_PACKAGE, name)
        if not os.path.exists(path):
            findings.append(PC.finding(
                "D-P4-HISTORICAL-IMMUTABLE-01",
                f"the historical package member {name} is absent", path))
        elif PA.sha256_file(path) != pinned:
            findings.append(PC.finding(
                "D-P4-HISTORICAL-IMMUTABLE-01",
                f"{name} is {PA.sha256_file(path)}, the phase opened with "
                f"{pinned}", path))
    live = PA.pre_repair_scorer_sha256()
    if live != PA.EXPECT_PRE_REPAIR_SCORER_SHA256:
        findings.append(PC.finding(
            "D-P4-HISTORICAL-IMMUTABLE-01",
            f"the historical v7 scorer is {live}, not the pinned "
            f"{PA.EXPECT_PRE_REPAIR_SCORER_SHA256}; the repair was applied in "
            f"place instead of in the candidate", PA.V7_ANALYSIS))
    return findings


def check_corpus_identity():
    """The successor consumed exactly the corpus the historical package did."""
    findings, checked = [], 0
    for run in PA.corpus()["runs"]:
        problems = PA.verify_run_inputs(run)
        checked += 1
        for problem in problems:
            findings.append(PC.finding("D-P4-CORPUS-IDENTITY-01", problem,
                                       run["identity"]))
    return findings, checked


def main():
    historical = os.path.join(PA.HISTORICAL_PACKAGE, "CORRECTED_RESULTS.json")
    successor = os.path.join(PA.PHASE4_ROOT, "successor", "package",
                             "CORRECTED_RESULTS.json")
    result = compare(historical, successor, "CORRECTED_RESULTS.json")
    print(f"estimand arms compared : {result['arms_compared']}")
    print(f"  invariant            : {result['invariant']}")
    print(f"  moved                : {len(result['moved'])}")
    print(f"  undefined both sides : "
          f"{len(result['legitimately_undefined_both_sides'])}")
    for key, reason in result["legitimately_undefined_both_sides"][:4]:
        print(f"     {key}  {reason}")
    print(f"findings               : {len(result['findings'])}")
    for row in result["findings"][:10]:
        print(f"  {row['detector_id']}  {row['message'][:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
