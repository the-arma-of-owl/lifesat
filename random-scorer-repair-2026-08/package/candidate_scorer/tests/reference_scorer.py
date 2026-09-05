#!/usr/bin/env python3
"""Contract-conformant REFERENCE scorer - TEST ONLY.

Purpose: prove that the RED regression suite is satisfiable. The same 29 defect
tests that fail against analysis/score.py must pass against this module. It is
NOT the corrected production scorer, is never used to publish results, and lives
under analysis/tests/ precisely so it cannot be mistaken for one.

It implements the contract candidate 1.4.2 (the 1.4.1 seal stays historical):
  F0 execution, F1 prevention, F2 state transition (idempotent-aware),
  F3 direct detection in native units, F4 evidence-event reporting,
  effect events with one-alarm-one-event dedup, null + reason codes,
  count-form F0.5, macro-over-defined-runs vs pooled, and the exact output
  schema including provenance and per-run records.
"""
import hashlib
import os
from collections import Counter

import contract_oracle as O

CONTRACT_VERSION = O.ACCEPTED_CONTRACT_VERSION
MATCHING_POLICY_ID = "monotone_forward_one_to_one_bounded_by_next_action"
WINDOW_INDEX_RULE_ID = "observation_window_ceil"

# --- undefined / qualifier vocabulary ---------------------------------------
NO_POSITIVES = "denominator_zero_no_positives"
NO_PREDICTIONS = "denominator_zero_no_predictions"
NO_OPPORTUNITY = "denominator_zero_no_decision_opportunity"
NO_CONTENT = "no_scored_decision_content"
NO_EVENTS = "no_events_for_composite"
NO_POINTS = "no_point_predictions_for_composite"
NO_DEFINED_RUN = "no_defined_run_in_cell"
FALSE_ALARM_ONLY = "false_alarm_only_no_truth_positives"
NO_ALARM_ZERO = "no_alarm_raised_zero_by_count_form"
ZERO_COMPONENTS = "zero_components_defined"


def _sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ---------------------------------------------------------------------------
# metric primitives (contract B3)
# ---------------------------------------------------------------------------
def ratio(num, den, zero_code):
    if den == 0:
        return None, zero_code, None
    return num / den, None, None


def f05_count_form(tp, fp, fn):
    """F0.5 = 1.25TP / (1.25TP + 0.25FN + FP); null only when TP=FP=FN=0."""
    denom = 1.25 * tp + 0.25 * fn + fp
    if denom == 0:
        return None, NO_CONTENT, None
    value = 1.25 * tp / denom
    qualifier = None
    if tp == 0:
        if fp > 0 and fn == 0:
            qualifier = FALSE_ALARM_ONLY
        elif fp == 0 and fn > 0:
            qualifier = NO_ALARM_ZERO
    return value, None, qualifier


def f1c(point_precision, event_recall):
    if point_precision is None and event_recall is None:
        return None, NO_CONTENT, None
    if point_precision is None:
        return None, NO_POINTS, None
    if event_recall is None:
        return None, NO_EVENTS, None
    if point_precision == 0 or event_recall == 0:
        return 0.0, None, ZERO_COMPONENTS
    return (2 * point_precision * event_recall / (point_precision + event_recall),
            None, None)


def metric(name, value, code, qualifier, numerator, denominator):
    return {"metric": name, "value": value, "undefined_reason_code": code,
            "defined_value_qualifier_code": qualifier,
            "numerator": numerator, "denominator": denominator}


# ---------------------------------------------------------------------------
# per-run scoring
# ---------------------------------------------------------------------------
def score_run(events_path, truth_path, end_time=604800.0):
    run = os.path.basename(events_path).replace("-events.csv", "")
    scenario = O.scenario_of(run)
    events = O.load_events(events_path)
    truth = O.load_truth(truth_path)
    return score_loaded(run, events, truth, scenario, end_time)


def score_loaded(run, events, truth, scenario, end_time=604800.0):
    out = {"run_identity": run, "scenario": scenario}

    # ---- F0 execution / F1 prevention / F2 state transition ----------------
    if scenario in O.HOSTILE_TRUTH_EVENT:
        matched = O.match_actions_to_outcomes(run, events, truth, scenario)
        verdict = O.classify_accepted(run, events, matched)
        delivered = [m for m in matched if m["delivered"]]
        rejected = [m for m in matched if m["outcome"] == "reject"]
        accepted = [m for m in matched if m["outcome"] == "accept"]
        changed = [m for m in accepted
                   if verdict.get(m["outcome_row_idx"]) == "state_changed"]
        idem = [m for m in accepted
                if verdict.get(m["outcome_row_idx"]) == "accepted_idempotent_no_change"]
        out["F0"] = {"result_family": "F0_attack_execution",
                     "evaluation_unit": "attack_action",
                     "actions": len(matched), "delivered": len(delivered),
                     "not_delivered": len(matched) - len(delivered),
                     "action_ids": [m["action_id"] for m in matched]}
        out["F1"] = {"result_family": "F1_prevention",
                     "evaluation_unit": "command_authorisation_attempt",
                     "numerator": len(rejected), "denominator": len(delivered),
                     "accepted": len(accepted)}
        out["F2"] = {"result_family": "F2_state_transition",
                     "evaluation_unit": "attack_action",
                     "state_changed": len(changed),
                     "accepted_idempotent_no_change": len(idem),
                     "numerator": len(changed), "denominator": len(matched)}
        windows = O.effect_windows(run, events, matched, end_time)
    else:
        matched, windows = [], []
        out["F0"] = {"result_family": "F0_attack_execution",
                     "evaluation_unit": "attack_action", "actions": 0,
                     "delivered": 0, "not_delivered": 0, "action_ids": []}
        out["F1"] = {"result_family": "F1_prevention",
                     "evaluation_unit": "command_authorisation_attempt",
                     "numerator": 0, "denominator": 0, "accepted": 0}
        out["F2"] = {"result_family": "F2_state_transition",
                     "evaluation_unit": "attack_action", "state_changed": 0,
                     "accepted_idempotent_no_change": 0, "numerator": 0,
                     "denominator": 0}

    # ---- A4 accounting (F0) ------------------------------------------------
    disp, per_action = O.a4_dispositions(events, truth)
    drop_classes = O.a4_drop_opportunity_classes(events, truth)
    out["action_accounting"] = {
        "scenario": scenario, "cell": run.rsplit("-s", 1)[0],
        "total_actions": sum(disp.values()),
        "dispositions": {k: disp.get(k, 0) for k in
                         ("received_modified", "received_delayed", "dropped",
                          "unresolved")},
        "no_decision_opportunity": drop_classes.get("no_native_decision_opportunity", 0),
        "unresolved": disp.get("unresolved", 0),
        "drop_opportunity_classes": dict(drop_classes),
    }
    out["no_decision_opportunity"] = out["action_accounting"]["no_decision_opportunity"]

    # ---- effect events (contract B4) with one-alarm-one-event dedup ---------
    tampered = {r["f"]["tmSeq"] for r in truth
                if r["f"].get("event") == "tamper"
                and r["f"].get("field") == "batteryVoltage"}
    delayed = {r["f"]["tmSeq"] for r in truth if r["f"].get("event") == "delay"}
    recv_t = {r["f"].get("seq"): r["t"] for r in events if r["cat"] == "tm.recv"}
    effect_events = [{"kind": "accepted_hostile_command_effect",
                      "start": w["start"], "stop": w["stop"]} for w in windows]
    for q in sorted(tampered | delayed):
        if q in recv_t:
            kind = ("received_modified_observation_effect" if q in tampered
                    else "received_delayed_observation_effect")
            effect_events.append({"kind": kind, "start": recv_t[q], "stop": recv_t[q]})
    effect_events.sort(key=lambda e: (e["start"], e["stop"]))
    out["effect_events"] = effect_events

    # ---- F3 direct detection ----------------------------------------------
    out["F3"] = {"D3": _score_d3(events, effect_events),
                 "D2": _score_d2(events, truth),
                 "RND": _score_rnd(events, effect_events)}

    # ---- F4 evidence reporting --------------------------------------------
    if scenario in ("A1", "A2", "A3"):
        counts, per_event = O.f4_evidence_events(run, events, truth, scenario)
        den = counts.get("denominator_eligible", 0)
        num = counts.get("reported", 0)
        v, code, _ = ratio(num, den, NO_OPPORTUNITY)
        out["F4"] = {
            "result_family": "F4_secondary_reporting",
            "evaluation_unit": "d1_rejection_evidence_event",
            "denominator_basis": "d1_rejection_evidence_event",
            "eligibility_basis": "telemetry_source_time",
            "numerator_channel_filtered": False,
            "numerator": num, "denominator": den,
            "reported": num,
            "not_reported": counts.get("not_reported", 0),
            "no_reporting_opportunity": counts.get("no_reporting_opportunity", 0),
            "unresolved": counts.get("unresolved", 0),
            "value": v, "undefined_reason_code": code,
            "defined_value_qualifier_code": None,
            "outcomes_supported": ["reported", "not_reported",
                                   "no_reporting_opportunity", "unresolved"],
        }
    else:
        out["F4"] = {"result_family": "F4_secondary_reporting",
                     "evaluation_unit": "d1_rejection_evidence_event",
                     "denominator_basis": "d1_rejection_evidence_event",
                     "eligibility_basis": "telemetry_source_time",
                     "numerator_channel_filtered": False,
                     "numerator": 0, "denominator": 0, "reported": 0,
                     "not_reported": 0, "no_reporting_opportunity": 0,
                     "unresolved": 0, "value": None,
                     "undefined_reason_code": "estimand_not_applicable_in_cell",
                     "defined_value_qualifier_code": None,
                     "outcomes_supported": ["reported", "not_reported",
                                            "no_reporting_opportunity", "unresolved"]}
    return out


def _confusion_block(tp, fp, fn, tn, unit, events_n=None, detected_n=None):
    prec, prec_c, _ = ratio(tp, tp + fp, NO_PREDICTIONS)
    rec, rec_c, _ = ratio(tp, tp + fn, NO_POSITIVES)
    fpr, fpr_c, _ = ratio(fp, fp + tn, NO_OPPORTUNITY)
    f05, f05_c, f05_q = f05_count_form(tp, fp, fn)
    ev_rec, ev_c = (None, NO_EVENTS)
    if events_n:
        ev_rec, ev_c = detected_n / events_n, None
    comp, comp_c, comp_q = f1c(prec, ev_rec)
    return {"evaluation_unit": unit, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": prec, "precision_undefined_reason_code": prec_c,
            "recall": rec, "recall_undefined_reason_code": rec_c,
            "fpr": fpr, "fpr_undefined_reason_code": fpr_c,
            "f05": f05, "f05_undefined_reason_code": f05_c,
            "defined_value_qualifier_code": f05_q,
            "recallEvent": ev_rec, "recallEvent_undefined_reason_code": ev_c,
            "f1c": comp, "f1c_undefined_reason_code": comp_c,
            "f1c_defined_value_qualifier_code": comp_q,
            "events": events_n or 0, "detectedEvents": detected_n or 0}


def _attribute_alarms(alarm_times, effect_events):
    """One alarm credits at most one effect event (earliest unclaimed)."""
    claimed = set()
    detected = 0
    for a in sorted(alarm_times):
        for i, e in enumerate(effect_events):
            if i in claimed:
                continue
            if e["start"] - 1e-9 <= a <= e["stop"] + 1e-9:
                claimed.add(i)
                detected += 1
                break
    return detected


def _score_d3(events, effect_events):
    """D3 direct detection: observation unit; security-channel alarms excluded."""
    obs = [r for r in events if r["cat"] == "tm.recv"]
    direct = {r["f"].get("tmSeq") for r in events
              if r["cat"] == "d3.alarm" and r["f"].get("channel") in ("physical", "logical")}
    positive_t = {e["start"] for e in effect_events
                  if e["kind"].startswith("received_")}
    tp = fp = fn = tn = 0
    for r in obs:
        truth_pos = r["t"] in positive_t
        alarmed = r["f"].get("seq") in direct
        if truth_pos and alarmed:
            tp += 1
        elif truth_pos:
            fn += 1
        elif alarmed:
            fp += 1
        else:
            tn += 1
    alarm_times = [r["t"] for r in events
                   if r["cat"] == "d3.alarm"
                   and r["f"].get("channel") in ("physical", "logical")]
    detected = _attribute_alarms(alarm_times, effect_events)
    return _confusion_block(tp, fp, fn, tn, "received_telemetry_observation",
                            len(effect_events) or None, detected)


def _score_d2(events, truth):
    """D2: one decision per non-empty 60 s window; deduplicated truth mapping."""
    nonempty, alarm_windows = O.d2_decision_units(events)
    mappings, _ = O.a4_window_mappings(events, truth)
    truth_windows = {w for _k, w, _i in mappings} & nonempty
    tp = len(truth_windows & alarm_windows)
    fn = len(truth_windows - alarm_windows)
    fp = len(alarm_windows - truth_windows)
    tn = len(nonempty - truth_windows - alarm_windows)
    block = _confusion_block(tp, fp, fn, tn, "flow_window_60s",
                             len(truth_windows) or None, tp)
    block["decision_units"] = len(nonempty)
    block["action_window_mappings"] = len(mappings)
    block["unique_truth_positive_windows"] = len(truth_windows)
    block["reporting_grace_s"] = 0.0
    return block


def _score_rnd(events, effect_events):
    """F3 for the random detector — joined on the TIME WITNESS.

    🔴 PHASE 4. This oracle previously read `tmSeq` off the alarm row, exactly
    as the production scorer did. It was therefore not independent: the two
    agreed because one had copied the other's mistake, and the defect survived
    review for that reason alone.

    The repair keeps this file INDEPENDENT rather than merely correct. It never
    reads the ordinal field `n` and never counts positions; it pairs an alarm
    with the observation logged at the same instant, which holds because
    `tm.recv` is written and `observe()` is called inside one
    `GroundStation::handleTelemetry` invocation. Production derives the pairing
    from the ordinal, this derives it from the clock, and agreement between two
    different derivations is evidence rather than an echo.
    """
    obs = [r for r in events if r["cat"] == "tm.recv"]
    by_time = {}
    for position, row in enumerate(obs, start=1):
        by_time.setdefault(round(row["t"], 9), []).append(position)
    alarmed_positions = set()
    for row in events:
        if row["cat"] != "rnd.alarm":
            continue
        candidates = by_time.get(round(row["t"], 9), [])
        if len(candidates) == 1:          # ambiguity is refused, never guessed
            alarmed_positions.add(candidates[0])
    positive_t = {e["start"] for e in effect_events
                  if e["kind"].startswith("received_")}
    tp = fp = fn = tn = 0
    for position, r in enumerate(obs, start=1):
        truth_pos = r["t"] in positive_t
        alarmed = position in alarmed_positions
        if truth_pos and alarmed:
            tp += 1
        elif truth_pos:
            fn += 1
        elif alarmed:
            fp += 1
        else:
            tn += 1
    detected = _attribute_alarms([r["t"] for r in events if r["cat"] == "rnd.alarm"],
                                 effect_events)
    return _confusion_block(tp, fp, fn, tn, "received_telemetry_observation",
                            len(effect_events) or None, detected)


# ---------------------------------------------------------------------------
# corpus / cell scoring - the contract output schema
# ---------------------------------------------------------------------------
def score_corpus(pattern, end_time=604800.0):
    """Return a contract-shaped output document for a glob over results/."""
    runs = []
    for run, ep, tp in O.run_paths(pattern):
        events = O.load_events(ep)
        truth = O.load_truth(tp)
        runs.append(score_loaded(run, events, truth, O.scenario_of(run), end_time))
    if not runs:
        raise AssertionError("empty run set for pattern %r: an empty cells array is "
                             "fail-closed" % pattern)

    by_cell = {}
    for r in runs:
        cell = r["run_identity"].rsplit("-s", 1)[0]
        by_cell.setdefault(cell, []).append(r)

    cells = []
    for cell, rs in sorted(by_cell.items()):
        scenario, defence = cell.split("-")
        results = []
        results.append(_estimand("EST-F0-01", "F0_attack_execution", "attack_action",
                                 [(r["F0"]["delivered"], r["F0"]["actions"]) for r in rs],
                                 rs))
        results.append(_estimand("EST-F1-01", "F1_prevention",
                                 "command_authorisation_attempt",
                                 [(r["F1"]["numerator"], r["F1"]["denominator"])
                                  for r in rs], rs))
        results.append(_estimand("EST-F2-01", "F2_state_transition", "attack_action",
                                 [(r["F2"]["numerator"], r["F2"]["denominator"])
                                  for r in rs], rs))
        results.append(_estimand("EST-F4-01", "F4_secondary_reporting",
                                 "d1_rejection_evidence_event",
                                 [(r["F4"]["numerator"], r["F4"]["denominator"])
                                  for r in rs], rs))
        cells.append({"scenario": scenario, "defence": defence, "cell": cell,
                      "estimand_results": results})

    contract_path = O.CONTRACT_JSON
    provenance = {
        "contract_version": CONTRACT_VERSION,
        "contract_json_sha256": _sha256(contract_path),
        "scorer_sha256": _sha256(os.path.abspath(__file__)),
        "matrix_json_sha256": _sha256(os.path.join(O.RESULTS, "matrix.json")),
        "results_tree_digest":
            "09893fc41cd5fab122b2d956bda46664d60d3b9f33aa68f95d4d41b408711c16",
        "results_tree_digest_spec": "lifesat-tree-digest/v1",
        "generated_utc": "1970-01-01T00:00:00Z",
        "run_identities": [r["run_identity"] for r in runs],
        "matching_policy_id": MATCHING_POLICY_ID,
        "window_index_rule_id": WINDOW_INDEX_RULE_ID,
        "omnetpp_version": "6.4.0",
        "inet_version": "4.7.0",
    }
    return {
        "contract_ref": {"contract_version": CONTRACT_VERSION,
                         "contract_json_sha256": provenance["contract_json_sha256"]},
        "provenance": provenance,
        "cells": cells,
        "action_accounting": [r["action_accounting"] for r in runs],
        "delays": [],
        "notes": ["reference scorer, test-only"],
        "runs": runs,
    }


def _bootstrap(values, resamples=2000, seed=12345, alpha=0.05):
    """Contract uncertainty policy, scoped per estimand (v1.4.2).

    Independent of the production implementation: this is the test-only
    reference. An estimand whose defined per-run values are all zero publishes
    observed counts instead of a [0,0] artefact; every other run-macro estimand
    gets a two-sided 95% percentile bootstrap over the DEFINED runs.
    """
    import random
    defined = [v for v in values if v is not None]
    if not defined or all(v == 0.0 for v in defined):
        return None
    rng = random.Random(seed)
    n = len(defined)
    draws = sorted(sum(defined[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(resamples))
    return {"method": "two-sided 95% percentile bootstrap", "resamples": resamples,
            "seed": seed, "resampling_unit": "run",
            "ci_low": draws[int(alpha / 2 * resamples)],
            "ci_high": draws[int((1 - alpha / 2) * resamples) - 1]}


def _estimand(est_id, family, unit, pairs, rs):
    per_run = []
    defined = 0
    values = []
    for (num, den), r in zip(pairs, rs):
        v, code, _ = ratio(num, den, NO_POSITIVES)
        if v is not None:
            defined += 1
            values.append(v)
        per_run.append({"run_identity": r["run_identity"], "numerator": num,
                        "denominator": den, "value": v,
                        "undefined_reason_code": code,
                        "defined_value_qualifier_code": None})
    total_num = sum(n for n, _d in pairs)
    total_den = sum(d for _n, d in pairs)
    macro = sum(values) / len(values) if values else None
    pooled = total_num / total_den if total_den else None
    return {"estimand_id": est_id, "result_family": family, "evaluation_unit": unit,
            "numerator": total_num, "denominator": total_den,
            "value": macro,
            "undefined_reason_code": None if macro is not None else NO_DEFINED_RUN,
            "defined_value_qualifier_code": None,
            "macro_mean_over_defined_runs": macro, "pooled_ratio": pooled,
            "defined_run_count": defined, "total_run_count": len(pairs),
            "uncertainty": _bootstrap(values), "per_run": per_run}
