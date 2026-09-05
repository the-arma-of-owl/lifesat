"""The six result families, each with its own numerator, denominator and unit.

Contract: result_families F0..F6, f4_semantics, cross_detector_comparison.
Execution, prevention, state transition, direct detection and secondary
reporting never merge.
"""
from . import metrics, rndjoin, state, windows
from .artefacts import telemetry_source_time
from .ontology import COMMAND_SIDE, TELEMETRY_SIDE

DIRECT_CHANNELS = frozenset({"physical", "logical"})


MATERIALISED = frozenset({"received_modified", "received_delayed", "dropped"})


def execution(command_records, telemetry_actions=(), dispositions=None):
    """F0: did the injected action execute against the system boundary?

    Command-side: the action executed when it was delivered to the command
    handler, whatever D1 then decided. Telemetry-side: the action executed when
    its consequence materialised (received_modified, received_delayed or
    dropped); an `unresolved` telemetry action did not.
    """
    command = [a for a in command_records if a["action"] in COMMAND_SIDE]
    delivered = [a for a in command if a["delivered"]]
    telemetry = list(telemetry_actions)
    materialised = 0
    if dispositions:
        materialised = sum(dispositions.get(k, 0) for k in MATERIALISED)
    actions = len(command) + len(telemetry)
    executed = len(delivered) + materialised
    return {"result_family": "F0_attack_execution",
            "evaluation_unit": "attack_action",
            "actions": actions, "delivered": executed,
            "not_delivered": actions - executed,
            "command_actions": len(command), "command_delivered": len(delivered),
            "telemetry_actions": len(telemetry),
            "telemetry_materialised": materialised,
            "action_ids": [a["action_id"] for a in command] +
                          [a["action_id"] for a in telemetry]}


def prevention(command_records):
    """F1: did D1 stop the hostile command before it changed state?"""
    delivered = [a for a in command_records if a["delivered"]]
    rejected = [a for a in delivered if a["outcome"] == "rejected"]
    accepted = [a for a in delivered if a["outcome"] == "accepted"]
    value, code = metrics.ratio(len(rejected), len(delivered), metrics.NO_POSITIVES)
    return {"result_family": "F1_prevention",
            "evaluation_unit": "command_authorisation_attempt",
            "numerator": len(rejected), "denominator": len(delivered),
            "accepted": len(accepted), "value": value,
            "undefined_reason_code": code}


def state_transition(command_records, verdicts):
    """F2: did the spacecraft state actually change?"""
    changed = idempotent = 0
    for record in command_records:
        effect = state.spacecraft_effect(record, verdicts)
        if effect == state.STATE_CHANGED:
            changed += 1
        elif effect == state.IDEMPOTENT:
            idempotent += 1
    value, code = metrics.ratio(changed, len(command_records), metrics.NO_POSITIVES)
    return {"result_family": "F2_state_transition",
            "evaluation_unit": "attack_action",
            "state_changed": changed,
            "accepted_idempotent_no_change": idempotent,
            "numerator": changed, "denominator": len(command_records),
            "value": value, "undefined_reason_code": code}


def action_accounting(run, events, telemetry_actions):
    """F0 layer L1 + L3b: every A4 action reconciles to exactly one disposition."""
    sent = {r["f"].get("seq") for r in events if r["cat"] == "tm.send"}
    received = {r["f"].get("seq") for r in events if r["cat"] == "tm.recv"}
    dispositions = {"received_modified": 0, "received_delayed": 0, "dropped": 0,
                    "unresolved": 0}
    for a in telemetry_actions:
        seq = a["tm_seq"]
        if a["action"] == "tamper_telemetry":
            key = "received_modified" if seq in received else "unresolved"
        elif a["action"] == "delay_telemetry":
            key = "received_delayed" if seq in received else "unresolved"
        elif a["action"] == "drop_telemetry":
            key = ("dropped" if seq in sent and seq not in received else "unresolved")
        else:
            key = "unresolved"
        dispositions[key] += 1
    classes = windows.drop_opportunity_classes(events, telemetry_actions)
    return {"scenario": run.split("-")[0], "cell": run.rsplit("-s", 1)[0],
            "total_actions": len(telemetry_actions),
            "dispositions": dispositions,
            "no_decision_opportunity": classes["no_native_decision_opportunity"],
            "unresolved": dispositions["unresolved"],
            "drop_opportunity_classes": classes}


def _direct_alarm_seqs(events):
    return {r["f"].get("tmSeq") for r in events
            if r["cat"] == "d3.alarm" and r["f"].get("channel") in DIRECT_CHANNELS}


def direct_detection_d3(events, effect_events, reporting_observations):
    """F3 for the twin: observation unit, physical/logical divergence only."""
    positives = {e["start"] for e in effect_events
                 if e["kind"].startswith("received_")}
    alarmed = _direct_alarm_seqs(events)
    tp = fp = fn = tn = 0
    for row in events:
        if row["cat"] != "tm.recv":
            continue
        if row["f"].get("seq") in reporting_observations:
            continue                      # family F4 evidence, never F3
        truth_positive = row["t"] in positives
        has_alarm = row["f"].get("seq") in alarmed
        if truth_positive and has_alarm:
            tp += 1
        elif truth_positive:
            fn += 1
        elif has_alarm:
            fp += 1
        else:
            tn += 1
    alarm_times = [r["t"] for r in events
                   if r["cat"] == "d3.alarm"
                   and r["f"].get("channel") in DIRECT_CHANNELS
                   and r["f"].get("tmSeq") not in reporting_observations]
    detected, claimed = state.credit_alarms(alarm_times, effect_events)
    block = metrics.confusion(tp, fp, fn, tn, "received_telemetry_observation",
                              len(effect_events) or None, detected)
    block["result_family"] = "F3_direct_detection"
    # The ONE credit pass is published so that any per-subtype view partitions
    # THIS result instead of re-running the credit. Re-running it per subtype
    # would let a single alarm be credited twice.
    block["credited_effect_indices"] = sorted(claimed)
    return block


A4_SUBTYPE_OF_EFFECT = {"received_modified_observation_effect": "modification",
                        "received_delayed_observation_effect": "delay"}
A4_SUBTYPE_OF_ACTION = {"tamper_telemetry": "modification",
                        "delay_telemetry": "delay",
                        "drop_telemetry": "drop"}


class SubtypePartitionError(Exception):
    """The per-subtype partition does not account for the credit pass exactly."""


def a4_subtype_detection(scenario, effect_events, credited_effect_indices,
                         telemetry_actions):
    """EST-A4-L2-02: per-subtype detection, partitioning ONE credit pass.

    Two different decision units are at stake and must not be mixed:

      * D3's unit is the received telemetry observation. A dropped packet never
        creates one, so EVERY drop lacks a D3 decision opportunity. The figure
        published here is therefore the whole drop population.
      * D2's unit is the 60 s flow window, which partitions the same drops into
        native / no-native opportunity classes. That partition belongs to
        EST-A4-L3-02 and is never read here.

    `credited_effect_indices` comes from direct_detection_d3, so an alarm that
    credited one effect event cannot be counted again under another subtype.
    """
    if scenario != "A4":
        return {"applicable": False, "evaluation_unit": "attack_action",
                "result_family": "F3_direct_detection",
                "reason": "the A4 subtype layer applies to A4 runs only"}

    actions = {"modification": 0, "delay": 0, "drop": 0}
    for a in telemetry_actions:
        key = A4_SUBTYPE_OF_ACTION.get(a["action"])
        if key:
            actions[key] += 1

    credited = sorted(set(credited_effect_indices))
    detected = {"modification": 0, "delay": 0}
    for i in credited:
        if i < 0 or i >= len(effect_events):
            raise SubtypePartitionError(
                "credited effect index %d is outside the effect-event list of "
                "length %d" % (i, len(effect_events)))
        kind = effect_events[i]["kind"]
        key = A4_SUBTYPE_OF_EFFECT.get(kind)
        if key is None:
            raise SubtypePartitionError(
                "credited effect %d has kind %r, which is neither a "
                "modification nor a delay effect; an A4 credit cannot be "
                "attributed to any subtype" % (i, kind))
        detected[key] += 1

    total = detected["modification"] + detected["delay"]
    if total != len(credited):
        raise SubtypePartitionError(
            "the subtype partition accounts for %d credits but the single "
            "credit pass produced %d; every credited effect event must land in "
            "exactly one subtype" % (total, len(credited)))

    out = {"applicable": True, "evaluation_unit": "attack_action",
           "result_family": "F3_direct_detection",
           "credit_semantics": ("one alarm credits at most one effect event; the "
                                "per-subtype split partitions that single credit "
                                "pass exactly and never re-credits"),
           "credited_effect_events": len(credited),
           "subtypes": {}}
    for key in ("modification", "delay"):
        num, den = detected[key], actions[key]
        value, code = metrics.ratio(num, den, metrics.NO_POSITIVES)
        out["subtypes"][key] = {"actions": den, "detected": num,
                                "numerator": num, "denominator": den,
                                "value": value, "undefined_reason_code": code}
    out["subtypes"]["drop"] = {
        "actions": actions["drop"], "detected": None,
        "numerator": None, "denominator": None, "value": None,
        "rate_published": False,
        # EVERY drop lacks a D3 decision opportunity. This is deliberately the
        # whole drop count and is NOT read from the D2 opportunity classes.
        "no_decision_opportunity": actions["drop"],
        "no_decision_opportunity_basis": (
            "received_telemetry_observation is never instantiated by a dropped "
            "packet, so all drop actions lack a D3 decision opportunity"),
        "undefined_reason_code": "structurally_not_applicable_no_decision_point",
        "reason": ("D3 is arrival-driven; a dropped packet never instantiates a "
                   "received telemetry observation, so no detection rate exists "
                   "for this subtype (ISS-05).")}
    out["partition_check"] = {
        "sum_of_subtype_detections": total,
        "credited_effect_events": len(credited),
        "exact": total == len(credited)}
    return out


def direct_detection_rnd(events, effect_events):
    """F3 for the random detector, joined on the ARRIVAL ORDINAL.

    The producer emits `rnd.alarm,n=<1-based observation ordinal>`; the consumer
    joins on the position of the `tm.recv` row, not on `seq`. See rndjoin for
    the registered producer/consumer fields, the join key, and why `seq` is
    provenance and never a key.

    The binding's conservation equation travels with the block: every raw alarm
    row carries exactly one terminal disposition, so a silent drop shows up as
    arithmetic rather than as a missing number.
    """
    positives = {e["start"] for e in effect_events
                 if e["kind"].startswith("received_")}
    binding = rndjoin.bind(events)
    alarmed = binding.alarmed_ordinals
    tp = fp = fn = tn = 0
    ordinal = 0
    for row in events:
        if row["cat"] != "tm.recv":
            continue
        ordinal += 1
        truth_positive = row["t"] in positives
        has_alarm = ordinal in alarmed
        if truth_positive and has_alarm:
            tp += 1
        elif truth_positive:
            fn += 1
        elif has_alarm:
            fp += 1
        else:
            tn += 1
    detected, _ = state.credit_alarms(
        [r["t"] for r in events if r["cat"] == "rnd.alarm"], effect_events)
    block = metrics.confusion(tp, fp, fn, tn, "received_telemetry_observation",
                              len(effect_events) or None, detected)
    block["result_family"] = "F3_direct_detection"
    block["random_alarm_conservation"] = binding.conservation
    return block


def direct_detection_d2(events, telemetry_actions):
    """F3 for the flow detector: one decision per non-empty 60 s window."""
    opportunities, alarm_windows = windows.decision_set(events)
    mappings = windows.flow_observable_mappings(events, telemetry_actions)
    truth_windows = {m["window"] for m in mappings} & opportunities
    tp = len(truth_windows & alarm_windows)
    fn = len(truth_windows - alarm_windows)
    fp = len(alarm_windows - truth_windows)
    tn = len(opportunities - truth_windows - alarm_windows)
    block = metrics.confusion(tp, fp, fn, tn, "flow_window_60s",
                              len(truth_windows) or None, tp)
    block["result_family"] = "F3_direct_detection"
    block["decision_units"] = len(opportunities)
    block["action_window_mappings"] = len(mappings)
    block["unique_truth_positive_windows"] = len(truth_windows)
    block["reporting_grace_s"] = 0.0
    block["unresolved_boundary_observations"] = len(
        windows.assert_no_boundary_observation(events))
    return block


def f4_applicable(scenario, defence):
    """Contract applicability: F4 needs BOTH D1 and the twin, i.e. a D3 cell.

    Without the twin there is no observer of the rejection counter, so the family
    is not_applicable rather than a run of zero-scoring evidence events.
    """
    return scenario in ("A1", "A2", "A3", "A2v") and defence == "D3"


def not_applicable_reporting():
    return {"result_family": "F4_secondary_reporting",
            "evaluation_unit": "d1_rejection_evidence_event",
            "denominator_basis": "d1_rejection_evidence_event",
            "eligibility_basis": "telemetry_source_time",
            "numerator_channel_filtered": False,
            "numerator": 0, "denominator": 0, "reported": 0, "not_reported": 0,
            "no_reporting_opportunity": 0, "unresolved": 0,
            "value": None,
            "undefined_reason_code": metrics.NOT_APPLICABLE,
            "defined_value_qualifier_code": None,
            "outcomes_supported": ["reported", "not_reported",
                                   "no_reporting_opportunity", "unresolved"]}, set()


def _observations_with_counter(events):
    """Received observations ordered by source time, with the reported counter.

    A missing or non-integer `rej` field is recorded as None: the chain cannot be
    verified through it, and every evidence event attributed to such an
    observation is `unresolved` rather than reported.
    """
    rows = []
    for row in events:
        if row["cat"] != "tm.recv":
            continue
        raw = row["f"].get("rej")
        try:
            counter = int(raw)
        except (TypeError, ValueError):
            counter = None
        rows.append({"seq": row["f"].get("seq"), "recv": row["t"],
                     "src": telemetry_source_time(row), "rej": counter,
                     "idx": row["idx"]})
    rows.sort(key=lambda o: (o["src"], o["seq"], o["idx"]))
    return rows


def secondary_reporting(events, command_records):
    """F4: was evidence generated by D1 subsequently seen by the ground?

    The denominator is built from D1 rejection EVIDENCE events, never from
    observed counter transitions, so `not_reported` stays reachable. Eligibility
    runs on telemetry source time, and the numerator is not filtered on the
    alarm's selected channel label.

    The counter is verified against an ABSOLUTE expectation anchored once, before
    the first rejection:

        expected(observation) = baseline
                              + |{rejections whose timestamp precedes the
                                  observation's source time}|

    because each rejection increments the onboard rejected-command counter by
    exactly one. An observation confirms its group only when the observed counter
    equals that absolute value.

    Anchoring the expectation ONCE is what keeps a broken chain broken. A relative
    baseline taken from the most recent syntactically valid observation would let
    a mismatched, malformed or missing observation silently become the new
    reference, so the very next observation would "agree" again and manufacture a
    reporting success out of a chain that had already failed. Under the absolute
    rule a mismatch never re-anchors anything, and an evidence event already
    ruled `unresolved` can never be converted into `reported` by a later
    observation.

      observed == expected, alarm on the same callback -> group reported
      observed == expected, no alarm                   -> group not_reported
      observed != expected, missing, malformed, or no
      anchorable baseline                              -> group unresolved
      no eligible observation at all                   -> no_reporting_opportunity

    `reporting_observations` contains only observations whose absolute
    expectation was confirmed.
    """
    rejections = sorted(r["outcome_t"] for r in command_records
                        if r["outcome"] == "rejected")
    observations = _observations_with_counter(events)
    alarm_seqs = {r["f"].get("tmSeq") for r in events if r["cat"] == "d3.alarm"}

    counts = {"reported": 0, "not_reported": 0, "no_reporting_opportunity": 0,
              "unresolved": 0}
    reporting_observations = set()
    if not rejections:
        return _reporting_block(counts), reporting_observations

    # Anchor once: the last verifiable counter strictly before the first
    # rejection. It is never updated afterwards.
    baseline = None
    first_rejection = rejections[0]
    for row in observations:
        if row["src"] >= first_rejection:
            break
        if row["rej"] is not None:
            baseline = row["rej"]

    # Group the rejections by their first source-time eligible observation.
    groups = {}
    for rejection_t in rejections:
        position = next((i for i, o in enumerate(observations)
                         if o["src"] > rejection_t), None)
        if position is None:
            counts["no_reporting_opportunity"] += 1
            continue
        groups.setdefault(position, []).append(rejection_t)

    for position, members in sorted(groups.items()):
        observation = observations[position]
        if baseline is None or observation["rej"] is None:
            counts["unresolved"] += len(members)
            continue
        preceding = sum(1 for t in rejections if t < observation["src"])
        expected_absolute = baseline + preceding
        if observation["rej"] != expected_absolute:
            # Skipped, repeated, decreasing, stalled or otherwise unexplained:
            # the chain is broken here and is NOT re-anchored.
            counts["unresolved"] += len(members)
            continue
        reporting_observations.add(observation["seq"])
        if observation["seq"] in alarm_seqs:
            counts["reported"] += len(members)
        else:
            counts["not_reported"] += len(members)

    return _reporting_block(counts), reporting_observations


def _reporting_block(counts):
    denominator = counts["reported"] + counts["not_reported"]
    value, code = metrics.ratio(counts["reported"], denominator,
                                metrics.NO_OPPORTUNITY)
    block = {"result_family": "F4_secondary_reporting",
             "evaluation_unit": "d1_rejection_evidence_event",
             "denominator_basis": "d1_rejection_evidence_event",
             "eligibility_basis": "telemetry_source_time",
             "counter_verification": "absolute_expected_counter_anchored_once",
             "numerator_channel_filtered": False,
             "numerator": counts["reported"], "denominator": denominator,
             "value": value, "undefined_reason_code": code,
             "defined_value_qualifier_code": None,
             "outcomes_supported": ["reported", "not_reported",
                                    "no_reporting_opportunity", "unresolved"]}
    block.update(counts)
    return block
