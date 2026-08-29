#!/usr/bin/env python3
"""
LIFESAT -- scoring one run: matching detector verdicts against the answer key.

THIS IS THE MEASUREMENT POINT OF THE STUDY.  The real question is not "how
many alarms" but "which alarm corresponds to which attack" -- and before that,
"what happened": was an action executed, was it prevented, did it really change the state.

How R1 is preserved: the answer key (*-truth.csv) is invisible to every detector
during the run. This script runs offline and joins the two files, so scoring
never lets a detector see the key.

This version implements the accepted scoring contract
(lifesat-scoring-contract/v1, 1.4.3-candidate; the 1.4.2 seal is the historical authority):

  · the action id derives from the truth row index; cmdId is provenance only,
    so in A3 the replayed command's own legitimate acceptance stays benign;
  · F0 execution, F1 prevention and F2 state change are separate families; an
    acceptance that rewrites the same value is `accepted_idempotent_no_change`
    and produces no effect event;
  · the effect window closes on the next acceptance writing a DIFFERENT value to
    the same key -- legitimate or adversarial alike; one alarm credits at most one
    effect event;
  · D2's decision unit is the (run, window) pair; per-observation duplication and
    the asymmetric 60 s grace have been removed;
  · A4 actions partition exactly into modification/delay/drop/unresolved and the
    decision-opportunity class of the drops is reported;
  · the F4 denominator is D1 reject EVIDENCE events (not the observed counter
    transition), eligibility is set by telemetry source time, and the counter
    is not filtered;
  · an undefined ratio is null plus a reason code, never 0.0; F0.5 is computed
    from the count form; macro-over-defined-runs and the pooled ratio are separate fields.

Metrics (§6 decision, K-59):
  · F0.5   precision-weighted (a false alarm is expensive for the operator), count form
  · F1C    event-based recall + point-based precision (composite F-score)
  · FPR    separately, on its own
  F1PA is not used -- the random detector scores 0.912 there (K-59).
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scoring import artefacts, families, matching, ontology, output, state  # noqa: E402
from scoring.artefacts import (ArtefactError, load_events, load_truth,  # noqa: E402,F401
                               parse_fields)

SIM_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT_VERSION = "1.4.3-candidate"

# Tier-1 estimands emitted per cell, in contract order.
CELL_ESTIMANDS = (
    ("EST-F0-01", "F0_attack_execution", "attack_action",
     lambda r: (r["F0"]["delivered"], r["F0"]["actions"])),
    ("EST-F1-01", "F1_prevention", "command_authorisation_attempt",
     lambda r: (r["F1"]["numerator"], r["F1"]["denominator"])),
    ("EST-F2-01", "F2_state_transition", "attack_action",
     lambda r: (r["F2"]["numerator"], r["F2"]["denominator"])),
    ("EST-F4-01", "F4_secondary_reporting", "d1_rejection_evidence_event",
     lambda r: (r["F4"]["numerator"], r["F4"]["denominator"])),
)


def score_run(events_path, truth_path, end_time=artefacts.RUN_HORIZON):
    """Score one run against the accepted contract."""
    run = artefacts.run_identity(events_path)
    events = load_events(events_path)
    truth = load_truth(truth_path)
    return score_loaded(run, events, truth, end_time)


def score_loaded(run, events, truth, end_time=artefacts.RUN_HORIZON):
    scenario = artefacts.scenario_of(run)
    action_records = ontology.actions(run, truth, scenario)
    command_actions = matching.command_actions_of(action_records)
    telemetry_actions = [a for a in action_records
                         if a["action"] in ontology.TELEMETRY_SIDE]

    matched, policy = matching.match(events, command_actions)
    hostile_rows = {a["outcome_row"] for a in matched if a["outcome"] == "accepted"}
    verdicts = state.replay_parameter_store(events, hostile_rows)

    effect_events = state.effect_windows(events, verdicts, end_time)
    effect_events += state.telemetry_effect_events(events, telemetry_actions)
    effect_events.sort(key=lambda e: (e["start"], e["stop"]))

    defence = run.split("-")[1] if "-" in run else ""
    if families.f4_applicable(scenario, defence):
        f4_block, reporting_observations = families.secondary_reporting(events, matched)
    else:
        f4_block, reporting_observations = families.not_applicable_reporting()

    accounting = families.action_accounting(run, events, telemetry_actions)

    result = {
        "run_identity": run,
        "scenario": scenario,
        "matching_policy_id": policy,
        "F0": families.execution(matched, telemetry_actions,
                                 accounting["dispositions"]),
        "F1": families.prevention(matched),
        "F2": families.state_transition(matched, verdicts),
        "F4": f4_block,
        "action_accounting": accounting,
        "effect_events": effect_events,
        "F3": {
            "D3": families.direct_detection_d3(events, effect_events,
                                               reporting_observations),
            "D2": families.direct_detection_d2(events, telemetry_actions),
            "RND": families.direct_detection_rnd(events, effect_events),
        },
    }
    result["no_decision_opportunity"] = \
        result["action_accounting"]["no_decision_opportunity"]
    result["truth"] = _truth_summary(result, telemetry_actions)
    result["a4_subtype_detection"] = families.a4_subtype_detection(
        scenario, effect_events,
        result["F3"]["D3"].get("credited_effect_indices", []),
        telemetry_actions)
    result["effectIntervals"] = len(effect_events)
    result["episodes"] = sum(1 for r in truth
                             if r["f"].get("event") == "episode.begin")
    # Backwards-compatible detector handles for analysis/run_matrix.py.
    for detector in ("D2", "D3", "RND"):
        result[detector] = result["F3"][detector]
    return result


def _truth_summary(result, telemetry_actions):
    dispositions = result["action_accounting"]["dispositions"]
    return {"hostileCommands": result["F0"]["actions"],
            "hostileDelivered": result["F0"]["delivered"],
            "stateChanged": result["F2"]["state_changed"],
            "acceptedIdempotentNoChange":
                result["F2"]["accepted_idempotent_no_change"],
            "tamperedTm": dispositions["received_modified"],
            "delayedTm": dispositions["received_delayed"],
            "droppedTm": dispositions["dropped"],
            "unresolvedTm": dispositions["unresolved"]}


def score_corpus(pattern, end_time=artefacts.RUN_HORIZON, results_dir=None):
    """Score a glob of runs and emit the contract output document."""
    import glob
    base = results_dir or os.path.join(SIM_ROOT, "results")
    paths = sorted(glob.glob(os.path.join(base, pattern)))
    if not paths:
        raise ArtefactError("empty run set for pattern %r: an empty cells array is "
                            "fail-closed" % pattern)
    runs = [score_run(p, p.replace("-events.csv", "-truth.csv"), end_time)
            for p in paths]

    by_cell = {}
    for r in runs:
        by_cell.setdefault(r["run_identity"].rsplit("-s", 1)[0], []).append(r)

    cells = []
    for cell, members in sorted(by_cell.items()):
        scenario, defence = cell.split("-", 1)
        identities = [m["run_identity"] for m in members]
        results = [output.estimand_result(est_id, family, unit,
                                          [pick(m) for m in members], identities)
                   for est_id, family, unit, pick in CELL_ESTIMANDS]
        cells.append({"scenario": scenario, "defence": defence, "cell": cell,
                      "estimand_results": results})

    provenance = output.build_provenance(
        SIM_ROOT, [r["run_identity"] for r in runs],
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        CONTRACT_VERSION,
        matching_policy=runs[0]["matching_policy_id"])

    return {"contract_ref": {"contract_version": CONTRACT_VERSION,
                             "contract_json_sha256":
                                 provenance["contract_json_sha256"]},
            "provenance": provenance,
            "cells": cells,
            "action_accounting": [r["action_accounting"] for r in runs],
            "delays": _delays(runs),
            "notes": ["scored under %s" % CONTRACT_VERSION],
            "runs": runs}


def _delays(runs):
    """DL2 and DL4, each with its origin, endpoint and detection cardinality."""
    detected = scored = 0
    reported = evidence = 0
    for r in runs:
        d3 = r["F3"]["D3"]
        detected += d3["detectedEvents"]
        scored += d3["events"]
        reported += r["F4"]["reported"]
        evidence += r["F4"]["denominator"]
    return [
        output.delay_record(
            "DL2_received_observation_to_direct_alarm",
            "tm.recv timestamp of the affected observation",
            "timestamp of the D3 alarm raised on that observation",
            "detected received tampered/delayed observations only",
            detected, scored, 0.0 if detected else None),
        output.delay_record(
            "DL4_eligible_observation_to_twin_alarm",
            "arrival timestamp of the first eligible observation",
            "timestamp of the twin alarm raised on that observation",
            "reported evidence events", reported, evidence,
            0.0 if reported else None),
    ]


def _fmt(value, digits=3):
    return " -- " if value is None else "%.*f" % (digits, value)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events")
    ap.add_argument("--truth", default=None)
    ap.add_argument("--end", type=float, default=artefacts.RUN_HORIZON)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    truth = args.truth or args.events.replace("-events.csv", "-truth.csv")
    r = score_run(args.events, truth, args.end)

    if args.json:
        print(json.dumps({k: v for k, v in r.items()
                          if k not in ("D2", "D3", "RND")}, indent=2))
        return 0

    t = r["truth"]
    print(f"\nanswer key: {r['episodes']} episodes · {t['hostileCommands']} hostile "
          f"actions ({t['hostileDelivered']} delivered) · {t['stateChanged']} state "
          f"changes · {t['acceptedIdempotentNoChange']} idempotent acceptances")
    print(f"telemetry     : {t['tamperedTm']} tampered · {t['delayedTm']} delayed "
          f"· {t['droppedTm']} dropped · {t['unresolvedTm']} unresolved")
    print(f"effect events : {r['effectIntervals']}")
    print(f"F1 prevention : {r['F1']['numerator']}/{r['F1']['denominator']}"
          f"   F4 raporlama: {r['F4']['reported']}/{r['F4']['denominator']}\n")
    print(f"{'detector':<10}{'unit':<28}{'TP':>5}{'FP':>5}{'FN':>5}"
          f"{'precision':>10}{'recall':>9}{'FPR':>9}{'F0.5':>8}{'F1C':>8}")
    print("-" * 97)
    for name in ("D3", "D2", "RND"):
        s = r["F3"][name]
        print(f"{name:<10}{s['evaluation_unit']:<28}{s['tp']:>5}{s['fp']:>5}"
              f"{s['fn']:>5}{_fmt(s['precision']):>10}{_fmt(s['recall']):>9}"
              f"{_fmt(s['fpr'], 4):>9}{_fmt(s['f05']):>8}{_fmt(s['f1c']):>8}")
    print("\n[FAIL] Undefined values are shown as ' -- '; they must not be confused with 0.0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
